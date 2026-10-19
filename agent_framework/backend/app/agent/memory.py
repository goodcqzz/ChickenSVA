"""
对话记忆管理

管理 Agent 的对话上下文，支持：
- 短期记忆（当前对话）
- 按「用户轮次」成对裁剪（不破坏 assistant/tool_calls + tool 链）
- 超长 tool 结果优先缩内容而非删消息
- 发送前修复孤儿 tool 消息
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.llm.base import LLMMessage, MessageRole

logger = logging.getLogger(__name__)

# 默认上限：现代模型（DeepSeek 等）上下文远大于早期 8K 设计；仍留安全边际避免极端 payload
DEFAULT_MAX_CONTEXT_TOKENS = 128_000
TOKEN_RATIO = 1.5
DEFAULT_PRESERVE_MIN_MESSAGES = 8
TOOL_CONTENT_SHRINK_TARGET_CHARS = 4000


@dataclass
class MessageRecord:
    role: MessageRole
    content: str
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ConversationMemory:
    """对话记忆管理器"""

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        preserve_min_messages: int = DEFAULT_PRESERVE_MIN_MESSAGES,
    ):
        self._messages: List[MessageRecord] = []
        self._max_tokens = max(1_000, int(max_tokens))
        self._preserve_min_messages = max(4, int(preserve_min_messages))

    def add_message(
        self,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = MessageRecord(
            role=role,
            content=content,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata or {},
        )
        self._messages.append(record)
        self._trim_if_needed()

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        record = MessageRecord(
            role=MessageRole.ASSISTANT,
            content=content,
            timestamp=datetime.utcnow().isoformat(),
            tool_calls=tool_calls,
        )
        self._messages.append(record)
        self._trim_if_needed()

    def add_tool_message(
        self,
        tool_call_id: str,
        content: str,
        name: Optional[str] = None,
    ) -> None:
        record = MessageRecord(
            role=MessageRole.TOOL,
            content=content,
            timestamp=datetime.utcnow().isoformat(),
            tool_call_id=tool_call_id or None,
            name=name,
        )
        self._messages.append(record)
        self._trim_if_needed()

    def get_messages(self) -> List[LLMMessage]:
        """获取格式化消息列表（发送 LLM 前自动修复 tool 链）"""
        self.repair_tool_chain()
        return [
            LLMMessage(
                role=record.role,
                content=record.content,
                tool_calls=record.tool_calls,
                tool_call_id=record.tool_call_id,
                name=record.name,
            )
            for record in self._messages
        ]

    def get_message_count(self) -> int:
        return len(self._messages)

    def get_recent_messages(self, n: int = 10) -> List[LLMMessage]:
        recent = self._messages[-n:]
        return [
            LLMMessage(
                role=r.role,
                content=r.content,
                tool_calls=r.tool_calls,
                tool_call_id=r.tool_call_id,
                name=r.name,
            )
            for r in recent
        ]

    def clear(self) -> None:
        self._messages.clear()

    def estimate_tokens(self) -> int:
        total = 0
        for msg in self._messages:
            total += int(len(msg.content) / TOKEN_RATIO)
            if msg.tool_calls:
                total += int(len(str(msg.tool_calls)) / TOKEN_RATIO)
        return total

    def repair_tool_chain(self) -> int:
        """
        修复 assistant(tool_calls) 与 tool 结果的不完整配对。
        返回修复/移除的消息条数。
        """
        if not self._messages:
            return 0

        before = len(self._messages)
        cleaned: List[MessageRecord] = []
        i = 0
        while i < len(self._messages):
            msg = self._messages[i]

            if msg.role == MessageRole.TOOL:
                logger.warning("移除孤儿 tool 消息（前无 assistant tool_calls）")
                i += 1
                continue

            if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                required_ids = [
                    tc.get("id")
                    for tc in (msg.tool_calls or [])
                    if tc.get("id")
                ]
                cleaned.append(msg)
                i += 1

                tool_batch: List[MessageRecord] = []
                while i < len(self._messages) and self._messages[i].role == MessageRole.TOOL:
                    tool_batch.append(self._messages[i])
                    i += 1

                if not required_ids:
                    if tool_batch:
                        logger.warning(
                            "移除无 tool_call id 的 assistant 及其 %s 条 tool 结果",
                            len(tool_batch),
                        )
                        cleaned.pop()
                    continue

                by_id = {
                    t.tool_call_id: t
                    for t in tool_batch
                    if t.tool_call_id
                }
                if all(rid in by_id for rid in required_ids):
                    for rid in required_ids:
                        cleaned.append(by_id[rid])
                    extras = [t for t in tool_batch if t.tool_call_id not in required_ids]
                    if extras:
                        logger.debug("忽略 %s 条多余 tool 结果", len(extras))
                else:
                    missing = [rid for rid in required_ids if rid not in by_id]
                    logger.warning(
                        "移除不完整工具轮次（缺少 tool 响应: %s）",
                        missing[:3],
                    )
                    cleaned.pop()
                continue

            cleaned.append(msg)
            i += 1

        self._messages = cleaned
        removed = before - len(self._messages)
        if removed:
            logger.info("tool 消息链修复完成: 移除/整理 %s 条", removed)
        return removed

    def rollback_incomplete_tool_rounds(self) -> int:
        """回滚末尾尚未执行工具的 assistant(tool_calls)（工具结果尚未写入）。"""
        before = len(self._messages)
        if (
            self._messages
            and self._messages[-1].role == MessageRole.ASSISTANT
            and self._messages[-1].tool_calls
        ):
            self._messages.pop()
        removed = before - len(self._messages)
        if removed:
            logger.warning("已回滚末尾 %s 条未完成的 assistant(tool_calls) 消息", removed)
        return removed

    def _trim_if_needed(self) -> None:
        """超出上限时：优先按完整用户轮次删除旧历史，其次压缩旧 tool 内容。"""
        guard = 0
        while (
            self.estimate_tokens() > self._max_tokens
            and len(self._messages) > self._preserve_min_messages
            and guard < 200
        ):
            guard += 1
            if self._pop_oldest_user_turn():
                continue
            if self._shrink_oldest_tool_content():
                continue
            break

        if guard and self.estimate_tokens() > self._max_tokens:
            logger.warning(
                "对话仍超过 token 上限 (%s > %s)，已尽力裁剪",
                self.estimate_tokens(),
                self._max_tokens,
            )

    def _user_turn_boundaries(self) -> List[int]:
        return [i for i, msg in enumerate(self._messages) if msg.role == MessageRole.USER]

    def _pop_oldest_user_turn(self) -> bool:
        """
        删除最早的一个完整用户轮次：从第一个 user 到下一个 user 之前（不含）。
        保证 assistant(tool_calls)+tool 作为整块随轮次一起删除。
        """
        user_idxs = self._user_turn_boundaries()
        if len(user_idxs) < 2:
            return False

        start = user_idxs[0]
        end = user_idxs[1]
        if end - start <= 0:
            return False

        removed = end - start
        del self._messages[start:end]
        logger.info("裁剪最早用户轮次: 删除 %s 条消息", removed)
        return True

    def _shrink_oldest_tool_content(self) -> bool:
        """将最早的超长 tool 结果缩为摘要，避免破坏消息链。"""
        for msg in self._messages:
            if msg.role != MessageRole.TOOL:
                continue
            if len(msg.content) <= TOOL_CONTENT_SHRINK_TARGET_CHARS:
                continue
            original = len(msg.content)
            msg.content = (
                msg.content[:TOOL_CONTENT_SHRINK_TARGET_CHARS]
                + f"\n...(memory 压缩: 原 {original} 字符，已保留前 {TOOL_CONTENT_SHRINK_TARGET_CHARS} 字符)"
            )
            logger.info(
                "压缩 tool 结果 [%s]: %s -> %s 字符",
                msg.tool_call_id or msg.name,
                original,
                len(msg.content),
            )
            return True
        return False

    def to_dict(self) -> List[Dict[str, Any]]:
        return [
            {
                "role": r.role.value,
                "content": r.content,
                "timestamp": r.timestamp,
                "tool_calls": r.tool_calls,
                "tool_call_id": r.tool_call_id,
            }
            for r in self._messages
        ]

    def from_dict(self, data: List[Dict[str, Any]]) -> None:
        self._messages.clear()
        for item in data:
            role = MessageRole(item["role"])
            record = MessageRecord(
                role=role,
                content=item["content"],
                timestamp=item.get("timestamp", ""),
                tool_calls=item.get("tool_calls"),
                tool_call_id=item.get("tool_call_id"),
            )
            self._messages.append(record)
        self.repair_tool_chain()
