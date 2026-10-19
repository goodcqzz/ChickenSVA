"""
Agent核心决策引擎

实现ReAct(Reasoning + Acting)决策循环：
1. 思考(Thought): 分析用户意图，决定下一步行动
2. 行动(Action): 调用工具执行操作
3. 观察(Observation): 获取工具执行结果
4. 循环直到任务完成或达到步数限制

防循环机制：
- 最大步数限制
- 重复工具调用检测
- 语义相似度去重
"""

import asyncio
import json
import logging
import re
import uuid
from typing import AsyncIterator, Callable, Awaitable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.base import (
    BaseLLMProvider,
    LLMConfig,
    LLMMessage,
    LLMResponse,
    MessageRole,
    StreamToken,
    ToolDefinition as LLMToolDefinition,
)
from app.llm.factory import LLMFactory
from app.agent.tool_registry import ToolRegistry
from app.agent.memory import ConversationMemory
from app.config import settings

logger = logging.getLogger(__name__)

def _load_default_system_prompt() -> str:
    prompt_path = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "prompts"
        / "Agent_prompt.md"
    )
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return "你是鸡基因组结构变异分析助手，优先使用 query_sv、query_annotation 和填充工作流。"


DEFAULT_SYSTEM_PROMPT = _load_default_system_prompt()


@dataclass
class AgentStep:
    step_number: int
    thought: str = ""
    action: Optional[str] = None
    action_input: Optional[Dict[str, Any]] = None
    observation: str = ""
    answer: str = ""


@dataclass
class AgentResult:
    answer: str
    steps: List[AgentStep] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0


class AgentCore:
    """
    Agent核心决策引擎

    实现ReAct决策循环，协调LLM推理和工具执行
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        tool_registry: Optional[ToolRegistry] = None,
        memory: Optional[ConversationMemory] = None,
        max_steps: int = 10,
        max_execution_time: int = 120,
        on_token: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.llm_config = llm_config
        self.llm: BaseLLMProvider = LLMFactory.create(llm_config)
        self.tool_registry = tool_registry or ToolRegistry()
        self.memory = memory or ConversationMemory(
            max_tokens=settings.agent_memory_max_tokens,
            preserve_min_messages=settings.agent_memory_preserve_min_messages,
        )
        self.max_steps = max_steps
        self.max_execution_time = max_execution_time
        self.on_token = on_token

        self._step_history: List[str] = []
        self._preferred_language: str = "zh"
        self._current_user_message: str = ""

    async def run(
        self,
        user_message: str,
        session_id: str,
        stream: bool = True,
    ) -> AgentResult:
        """
        执行Agent决策循环

        Args:
            user_message: 用户消息
            session_id: 会话ID
            stream: 是否流式输出

        Returns:
            Agent执行结果
        """
        self.memory.add_message(MessageRole.USER, user_message)
        self._step_history = []
        self._current_user_message = user_message
        self._preferred_language = self._detect_preferred_language(user_message)

        result = AgentResult(answer="")

        tools = self._get_llm_tools()
        system_prompt = self._build_system_prompt(tools, self._preferred_language)

        try:
            result = await asyncio.wait_for(
                self._run_loop(system_prompt, tools, session_id, stream, result),
                timeout=self.max_execution_time,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Agent执行超时({self.max_execution_time}s)，强制终止")
            result.answer = result.answer or self._msg(
                f"⚠️ 执行超时（{self.max_execution_time}秒），已强制终止。请尝试简化您的问题。",
                f"⚠️ Execution timed out ({self.max_execution_time}s) and was stopped. Please try a simpler request.",
            )
        if not result.answer and result.tool_calls:
            result.answer = self._build_tool_only_fallback_answer(result.tool_calls[-1])

        if not result.answer:
            result.answer = self._msg(
                "抱歉，我无法完成这个任务。请尝试重新描述您的需求。",
                "Sorry, I could not complete this task. Please try rephrasing your request.",
            )

        forced_empty = self._forced_empty_result_answer(result.tool_calls)
        if forced_empty is not None:
            result.answer = forced_empty
        else:
            result.answer = self._append_query_sv_default_summary(
                result.answer, result.tool_calls, user_message
            )
            result.answer = self._correct_misaligned_gwas_answer(
                result.answer, result.tool_calls, user_message
            )
            result.answer = self._append_genome_scan_full_hits(result.answer, result.tool_calls, user_message)
        result.answer = await self._normalize_answer_language(result.answer)
        self.memory.add_message(MessageRole.ASSISTANT, result.answer)
        return result

    def _get_llm_call_kwargs(self) -> Dict[str, Any]:
        """提取当前 LLM 配置中的可调用参数，传递给 provider"""
        cfg = self.llm_config
        kwargs: Dict[str, Any] = {
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "top_p": cfg.top_p,
            "frequency_penalty": cfg.frequency_penalty,
            "presence_penalty": cfg.presence_penalty,
            "enable_online_search": cfg.enable_online_search,
        }
        return kwargs

    # 数据类工具：返回空/未匹配时，禁止模型续写特征描述（硬拦截）
    _DATA_TOOLS = frozenset({
        "query_sv",
        "query_breed_profile",
        "query_annotation",
        "analyze_breed_association",
        "genome_wide_association_scan",
    })

    @staticmethod
    def _is_empty_data_result(result: Any) -> bool:
        """判断单个数据工具结果是否为空/未匹配/失败。"""
        if not isinstance(result, dict):
            return not bool(result)

        status = str(result.get("status", "")).lower()
        if status in ("error", "not_found", "empty", "fail", "failed"):
            return True
        if result.get("found") is False or result.get("matched") is False:
            return True

        # 计数字段为 0 视为空
        for key in ("total", "hit_count", "count", "match_count", "matched_count"):
            val = result.get(key)
            if isinstance(val, (int, float)) and val == 0:
                return True

        # 数据载荷字段：若存在但全部为空，则视为空结果
        any_payload = False
        nonempty_payload = False
        for key in ("results", "hits", "genes", "data", "matches", "records", "rows"):
            if key in result:
                val = result[key]
                if isinstance(val, (list, dict)):
                    any_payload = True
                    if len(val) > 0:
                        nonempty_payload = True
                elif val is not None:
                    any_payload = True
                    nonempty_payload = True
        if any_payload and not nonempty_payload:
            return True
        return False

    def _forced_empty_result_answer(self, tool_calls: List[Dict[str, Any]]) -> Optional[str]:
        """
        空结果硬拦截：当本轮调用过数据类工具，且所有数据类工具均返回空/未匹配时，
        强制返回「未找到记录」模板，阻止模型基于名称字面或既往记忆续写品种特征/频率/结论。

        - 仅在调用过数据类工具时生效（纯闲聊/边界拒答不触发）。
        - 只要有任意一个数据类工具返回了非空结果，则不拦截（存在可用数据）。
        """
        if not getattr(settings, "empty_result_hard_block", True):
            return None
        if not tool_calls:
            return None

        data_tool_called = False
        all_empty = True
        for call in tool_calls:
            tool = call.get("tool", {})
            name = ""
            if isinstance(tool, dict):
                name = tool.get("function", {}).get("name", "") or tool.get("name", "")
            if name not in self._DATA_TOOLS:
                continue
            data_tool_called = True
            if not self._is_empty_data_result(call.get("result")):
                all_empty = False
                break

        if not data_tool_called or not all_empty:
            return None

        return self._msg(
            "数据库中未找到匹配记录。可能原因：名称拼写有误、使用了未收录的别名，或该品种/位点尚未收录。"
            "请确认名称后重试，或换用已收录的品种、基因名、染色体区域（如 1:1000000-2000000）或 SV 编号查询。",
            "No matching records were found in the database. Possible reasons: a misspelled name, "
            "an alias that is not indexed, or the breed/locus is not yet included. Please verify the "
            "name and retry, or query with an indexed breed, gene name, genomic region "
            "(e.g. 1:1000000-2000000), or SV ID.",
        )

    async def _run_stream_step(
        self,
        system_prompt: str,
        tools: List[LLMToolDefinition],
        session_id: str,
        step: AgentStep,
    ) -> LLMResponse:
        """执行一个流式推理步骤"""
        messages = self.memory.get_messages()
        formatted = self._format_messages(messages, system_prompt)

        full_content = ""
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
        finish_reason = None

        async for token in self.llm.chat_stream(formatted, tools, **self._get_llm_call_kwargs()):
            if token.content and self.on_token:
                await self.on_token(
                    session_id,
                    {
                        "type": "token",
                        "payload": {"content": token.content},
                    },
                )
                full_content += token.content

            if token.tool_calls:
                for tc in token.tool_calls:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.get("id"):
                        tool_calls_buffer[idx]["id"] = tc["id"]
                    func = tc.get("function", {})
                    if func.get("name"):
                        tool_calls_buffer[idx]["function"]["name"] += func["name"]
                    if func.get("arguments"):
                        tool_calls_buffer[idx]["function"][
                            "arguments"
                        ] += func.get("arguments", "")

            if token.finish_reason:
                finish_reason = token.finish_reason

        final_tool_calls = None
        if tool_calls_buffer:
            final_tool_calls = [
                tool_calls_buffer[i]
                for i in sorted(tool_calls_buffer.keys())
            ]
            for tc in final_tool_calls:
                if not tc.get("id"):
                    tc["id"] = f"call_{uuid.uuid4().hex[:12]}"
            self.memory.add_assistant_message(
                content=full_content, tool_calls=final_tool_calls
            )
        else:
            self.memory.add_message(MessageRole.ASSISTANT, full_content)

        return LLMResponse(
            content=full_content,
            finish_reason=finish_reason or "stop",
            tool_calls=final_tool_calls,
        )

    async def _run_loop(
        self,
        system_prompt: str,
        tools: List[Dict[str, Any]],
        session_id: str,
        stream: bool,
        result: "AgentResult",
    ) -> "AgentResult":
        for step_num in range(1, self.max_steps + 1):
            step = AgentStep(step_number=step_num)
            llm_retried = False

            while True:
                try:
                    if stream:
                        response = await self._run_stream_step(
                            system_prompt, tools, session_id, step
                        )
                    else:
                        response = await self._run_step(system_prompt, tools)
                    break
                except Exception as e:
                    if not llm_retried and self._is_tool_chain_llm_error(e):
                        repaired = self.memory.repair_tool_chain()
                        rolled = self.memory.rollback_incomplete_tool_rounds()
                        if repaired or rolled:
                            logger.warning(
                                "tool 消息链异常，已修复(repair=%s rollback=%s)并重试步骤 %s",
                                repaired,
                                rolled,
                                step_num,
                            )
                            llm_retried = True
                            continue
                    raise

            try:
                if response.tool_calls:
                    step.action = "tool_call"
                    step.thought = response.content or ""

                    for tool_call in response.tool_calls:
                        tool_result = await self._execute_tool_call(
                            tool_call, session_id
                        )
                        result.tool_calls.append(
                            {
                                "tool": tool_call,
                                "result": tool_result,
                            }
                        )
                        tool_name = tool_call.get("function", {}).get("name", "")
                        tool_result_text = self._serialize_tool_result_for_memory(tool_name, tool_result)

                        self.memory.add_tool_message(
                            tool_call_id=tool_call.get("id", ""),
                            content=tool_result_text,
                            name=tool_name or None,
                        )

                        step.observation += tool_result_text

                    action_sig = self._get_action_signature(response.tool_calls)
                    if self._is_repeated_action(action_sig):
                        logger.warning(f"检测到重复工具调用，终止循环: {action_sig}")
                        result.answer = await self._force_final_answer(
                            system_prompt, tools, session_id, stream
                        )
                        break

                    self._step_history.append(action_sig)
                else:
                    result.answer = response.content or ""
                    step.answer = result.answer
                    result.steps.append(step)
                    break

            except Exception as e:
                logger.error(f"Agent步骤{step_num}出错: {e}", exc_info=True)
                error_msg = str(e)
                if "Illegal header value" in error_msg or "Bearer" in error_msg:
                    result.answer = self._msg(
                        "⚠️ API Key 未配置或无效。请在前端「大模型配置」页面中输入有效的 API Key 后重试。",
                        "⚠️ API key is missing or invalid. Please update it in the model settings and try again.",
                    )
                elif "401" in error_msg or "Unauthorized" in error_msg:
                    result.answer = self._msg(
                        "⚠️ API Key 无效或已过期，请检查并更新 API Key。",
                        "⚠️ API key is invalid or expired. Please update your API key.",
                    )
                elif "429" in error_msg or "rate_limit" in error_msg.lower():
                    result.answer = self._msg(
                        "⚠️ API 调用频率超限，请稍后重试。",
                        "⚠️ Rate limit exceeded. Please try again later.",
                    )
                elif self._is_tool_chain_llm_error(e):
                    self.memory.repair_tool_chain()
                    self.memory.rollback_incomplete_tool_rounds()
                    result.answer = self._msg(
                        "⚠️ 对话上下文异常，已尝试自动修复。请重新发送您的问题；若仍失败请新建对话。",
                        "⚠️ Conversation context was corrupted and has been repaired. "
                        "Please resend your question, or start a new chat if the issue persists.",
                    )
                elif "timeout" in error_msg.lower():
                    result.answer = self._msg(
                        "⚠️ 请求超时，请稍后重试。",
                        "⚠️ Request timed out. Please try again later.",
                    )
                else:
                    result.answer = self._msg(
                        f"处理过程中出现错误: {error_msg}",
                        f"An error occurred while processing your request: {error_msg}",
                    )
                break

            result.steps.append(step)

        if not result.answer and result.tool_calls:
            logger.warning("达到最大步骤限制(%s)，使用工具结果生成兜底回答", self.max_steps)
            result.answer = self._build_tool_only_fallback_answer(result.tool_calls[-1])

        return result

    async def _run_step(
        self,
        system_prompt: str,
        tools: List[LLMToolDefinition],
    ) -> LLMResponse:
        """执行一个非流式推理步骤"""
        messages = self.memory.get_messages()
        formatted = self._format_messages(messages, system_prompt)

        response = await self.llm.chat(formatted, tools, **self._get_llm_call_kwargs())

        if response.tool_calls:
            self.memory.add_assistant_message(
                content=response.content, tool_calls=response.tool_calls
            )
        else:
            self.memory.add_message(MessageRole.ASSISTANT, response.content or "")

        return response

    async def _execute_tool_call(
        self, tool_call: Dict[str, Any], session_id: str
    ) -> Dict[str, Any]:
        """执行工具调用"""
        func = tool_call.get("function", {})
        tool_name = func.get("name", "")
        try:
            arguments = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}

        logger.info(f"执行工具: {tool_name}, 参数: {arguments}")

        if tool_name == "query_literature_kb" and not self._needs_literature_kb(
            self._current_user_message
        ):
            logger.info("跳过 query_literature_kb：当前问题不需要文献知识库")
            skipped = {
                "skipped": True,
                "hit_count": 0,
                "hits": [],
                "reason": self._msg(
                    "本轮为数据库结构化查询，无需调用文献知识库。请直接基于 query_sv、"
                    "query_annotation、analyze_breed_association 等已返回的数据作答，"
                    "不要引用未检索到的文献片段。",
                    "This turn is a structured database query; literature KB is not needed. "
                    "Answer only from data tools already called (query_sv, query_annotation, "
                    "analyze_breed_association, etc.) and do not cite literature that was not retrieved.",
                ),
            }
            if self.on_token:
                await self.on_token(
                    session_id,
                    {
                        "type": "tool_call",
                        "payload": {
                            "tool_name": tool_name,
                            "arguments": arguments,
                        },
                    },
                )
                await self.on_token(
                    session_id,
                    {
                        "type": "tool_result",
                        "payload": {"tool_name": tool_name, "result": skipped},
                    },
                )
            return skipped

        if self.on_token:
            await self.on_token(
                session_id,
                {
                    "type": "tool_call",
                    "payload": {
                        "tool_name": tool_name,
                        "arguments": arguments,
                    },
                },
            )

        result = await self.tool_registry.execute(tool_name, arguments, session_id)

        if self.on_token:
            await self.on_token(
                session_id,
                {
                    "type": "tool_result",
                    "payload": {
                        "tool_name": tool_name,
                        "result": result,
                    },
                },
            )

        return result

    async def _force_final_answer(
        self,
        system_prompt: str,
        tools: List[LLMToolDefinition],
        session_id: str,
        stream: bool,
    ) -> str:
        """强制生成最终回答（防循环）"""
        force_prompt = self._msg(
            "请根据已有的工具调用结果，直接给出最终回答，不要再调用任何工具。",
            "Based on the existing tool results, provide the final answer directly and do not call any more tools.",
        )
        self.memory.add_message(MessageRole.USER, force_prompt)

        if stream:
            full_content = ""
            formatted = self._format_messages(
                self.memory.get_messages(), system_prompt
            )
            async for token in self.llm.chat_stream(formatted, tools):
                if token.content and self.on_token:
                    await self.on_token(
                        session_id,
                        {"type": "token", "payload": {"content": token.content}},
                    )
                    full_content += token.content
            self.memory.add_message(MessageRole.ASSISTANT, full_content)
            return full_content
        else:
            formatted = self._format_messages(
                self.memory.get_messages(), system_prompt
            )
            response = await self.llm.chat(formatted, tools)
            self.memory.add_message(
                MessageRole.ASSISTANT, response.content or ""
            )
            return response.content or ""

    def _serialize_tool_result_for_memory(self, tool_name: str, tool_result: Any) -> str:
        compact_result = self._compact_tool_result_for_memory(tool_name, tool_result)
        try:
            result_text = json.dumps(compact_result, ensure_ascii=False)
        except Exception:
            result_text = str(compact_result)

        max_chars = (
            settings.agent_tool_result_gwas_max_chars
            if tool_name == "genome_wide_association_scan"
            else settings.agent_tool_result_max_chars
        )
        if len(result_text) > max_chars:
            result_text = result_text[:max_chars] + "...(truncated for memory)"
        return result_text

    @staticmethod
    def _is_tool_chain_llm_error(exc: BaseException) -> bool:
        text = str(exc).lower()
        if "messages with role 'tool'" in text:
            return True
        if "tool_calls" in text and ("400" in text or "invalid_request_error" in text):
            return True
        return False

    def _compact_tool_result_for_memory(self, tool_name: str, tool_result: Any) -> Any:
        if not isinstance(tool_result, dict):
            return tool_result

        if tool_name == "query_sv":
            results = tool_result.get("results")
            if isinstance(results, list):
                preview_items = []
                for item in results[:5]:
                    if not isinstance(item, dict):
                        continue
                    compact_item = {
                        "id": item.get("id"),
                        "chr": item.get("chr"),
                        "start": item.get("start"),
                        "end": item.get("end"),
                        "type": item.get("type"),
                        "gene": item.get("gene"),
                        "mean_frequency": item.get("mean_frequency"),
                        "top_breed_frequencies": (item.get("top_breed_frequencies") or [])[:5],
                    }
                    if item.get("domestication_summary"):
                        compact_item["domestication_summary"] = item.get("domestication_summary")
                    if item.get("frequency_tier_summary"):
                        compact_item["frequency_tier_summary"] = item.get("frequency_tier_summary")
                    preview_items.append(compact_item)

                compact_payload = {
                    "status": tool_result.get("status"),
                    "query": tool_result.get("query"),
                    "total": tool_result.get("total"),
                    "has_more": tool_result.get("has_more"),
                    "data_source": tool_result.get("data_source"),
                    "results_preview": preview_items,
                    "preview_count": len(preview_items),
                    "omitted_result_count": max(0, len(results) - len(preview_items)),
                }
                if tool_result.get("frequency_tier_summary"):
                    compact_payload["frequency_tier_summary"] = tool_result.get("frequency_tier_summary")
                return compact_payload

        if tool_name == "genome_wide_association_scan":
            data = tool_result.get("data")
            if isinstance(data, dict):
                top_hits = data.get("top_hits")
                if isinstance(top_hits, list):
                    try:
                        requested_hits = int(data.get("returned_top_n") or len(top_hits))
                    except (TypeError, ValueError):
                        requested_hits = len(top_hits)

                    target_count = min(200, max(5, requested_hits))
                    compact_hits = []
                    seen_sv_ids = set()

                    for hit in top_hits:
                        if not isinstance(hit, dict):
                            continue

                        sv_id = hit.get("sv_id")
                        sv_key = str(sv_id or "").strip()
                        if sv_key:
                            if sv_key in seen_sv_ids:
                                continue
                            seen_sv_ids.add(sv_key)

                        p_value = hit.get("p_value")
                        fdr = hit.get("fdr")
                        try:
                            p_value_sci = f"{float(p_value):.3e}" if p_value is not None else None
                        except (TypeError, ValueError):
                            p_value_sci = None
                        try:
                            fdr_sci = f"{float(fdr):.3e}" if fdr is not None else None
                        except (TypeError, ValueError):
                            fdr_sci = None

                        compact_hits.append(
                            {
                                "rank": len(compact_hits) + 1,
                                "sv_id": sv_id,
                                "gene": hit.get("gene"),
                                "chromosome": hit.get("chromosome"),
                                "position": hit.get("position"),
                                "sv_type": hit.get("sv_type"),
                                "correlation": hit.get("correlation"),
                                "p_value_sci": p_value_sci,
                                "fdr_sci": fdr_sci,
                            }
                        )
                        if len(compact_hits) >= target_count:
                            break

                    compact_data = {k: v for k, v in data.items() if k != "top_hits"}
                    compact_data["top_hits_compact"] = compact_hits
                    compact_data["top_hits_preview"] = compact_hits[:target_count]
                    compact_data["compact_hit_count"] = len(compact_hits)
                    compact_data["omitted_top_hits"] = max(0, len(top_hits) - len(compact_hits))

                    compact_result = {k: v for k, v in tool_result.items() if k != "data"}
                    compact_result["data"] = compact_data
                    return compact_result

        if tool_name == "query_literature_kb":
            hits = tool_result.get("hits")
            if isinstance(hits, list):
                compact_hits = []
                for hit in hits[:2]:
                    if not isinstance(hit, dict):
                        continue
                    content = hit.get("content") or ""
                    compact_hits.append(
                        {
                            "document_name": hit.get("document_name"),
                            "score": hit.get("score"),
                            "content": content[:600] + ("..." if len(content) > 600 else ""),
                        }
                    )
                return {
                    "query": tool_result.get("query"),
                    "hit_count": tool_result.get("hit_count"),
                    "hits_preview": compact_hits,
                    "omitted_hit_count": max(0, len(hits) - len(compact_hits)),
                }

        return tool_result

    def _build_tool_only_fallback_answer(self, latest_tool_call: Dict[str, Any]) -> str:
        tool_meta = latest_tool_call.get("tool", {})
        tool_func = tool_meta.get("function", {}) if isinstance(tool_meta, dict) else {}
        tool_name = tool_func.get("name", "")
        tool_result = latest_tool_call.get("result", {})

        if tool_name == "query_sv" and isinstance(tool_result, dict):
            query_info = (
                tool_result.get("query", {})
                if isinstance(tool_result.get("query"), dict)
                else {}
            )
            query_text = query_info.get("value") or self._msg("(未提供查询值)", "(query value not provided)")
            total = tool_result.get("total")
            result_rows = (
                tool_result.get("results")
                if isinstance(tool_result.get("results"), list)
                else []
            )
            shown_count = len(result_rows)

            lines = [self._msg(f"已完成 SV 区间查询：{query_text}", f"SV region query completed: {query_text}")]
            if total is not None:
                lines.append(
                    self._msg(
                        f"命中总数：{total}，当前返回：{shown_count} 条。",
                        f"Total hits: {total}, currently returned: {shown_count} rows.",
                    )
                )

            preview = []
            preview_limit = min(len(result_rows), 20)
            for row in result_rows[:preview_limit]:
                if not isinstance(row, dict):
                    continue
                sv_id = row.get("id", "")
                sv_type = row.get("type", "")
                chrom = row.get("chr", "")
                start = row.get("start", "")
                end = row.get("end", "")
                gene = row.get("gene", "-")
                preview.append(
                    f"- {sv_id} ({sv_type}) Chr{chrom}:{start}-{end}, gene={gene}"
                )

            if preview:
                lines.append(self._msg(f"前{len(preview)}条结果摘要：", f"Top {len(preview)} result summary:"))
                lines.extend(preview)

            lines.append(
                self._msg(
                    "如果你希望，我可以继续按SV类型、基因名或品种频率阈值做二次筛选。",
                    "If you want, I can further filter these by SV type, gene name, or breed-frequency threshold.",
                )
            )
            return "\n".join(lines)

        if tool_name == "genome_wide_association_scan" and isinstance(tool_result, dict):
            data = (
                tool_result.get("data", {})
                if isinstance(tool_result.get("data"), dict)
                else {}
            )
            tested = data.get("tested_variant_count")
            returned = data.get("returned_top_n")
            phenotype = data.get("phenotype_name")
            if not phenotype:
                phenotype = "目标表型"

            tested_variant_count = (
                data.get("tested_variant_count")
                or data.get("total_tests")
                or data.get("tested_variants")
                or "-"
            )
            significant_variant_count = (
                data.get("significant_variant_count")
                or data.get("significant_hits")
                or data.get("significant_loci")
                or "-"
            )

            top_hits = data.get("top_hits", [])
            target_n = returned if returned is not None else 10
            strongest_hit = data.get("top_hit")
            if not isinstance(strongest_hit, dict):
                strongest_hit = top_hits[0] if top_hits and isinstance(top_hits[0], dict) else {}

            strongest_sv_id = strongest_hit.get("sv_id") or strongest_hit.get("id") or "-"
            strongest_p = strongest_hit.get("p_value_sci") or strongest_hit.get("p_value") or "-"
            strongest_fdr = strongest_hit.get("fdr_sci") or strongest_hit.get("fdr") or "-"

            lines = [
                self._msg(
                    f"## 全基因组SV关联扫描结果（P值最低前{target_n}位点）",
                    f"## Genome-wide SV association scan results (top {target_n} loci by p-value)",
                ),
                self._msg(
                    f"已完成对表型“{phenotype}”的全基因组关联扫描，以下按P值升序直接列出前{target_n}个候选位点。该结果是品种聚合层面的相关分析，不代表个体因果结论。",
                    f"Completed a genome-wide association scan for phenotype '{phenotype}'. The following list shows the top {target_n} candidate loci sorted directly by p-value. This is a breed-aggregated association analysis, not an individual-level causal conclusion.",
                ),
            ]

            if tested_variant_count != "-" or significant_variant_count != "-":
                lines.append(
                    self._msg(
                        f"关键统计：测试位点数={tested_variant_count}，显著关联位点数={significant_variant_count}，最强关联信号={strongest_sv_id}（P={strongest_p}，FDR={strongest_fdr}）。",
                        f"Key stats: tested variants={tested_variant_count}, significant loci={significant_variant_count}, strongest signal={strongest_sv_id} (P={strongest_p}, FDR={strongest_fdr}).",
                    )
                )

            table_header = self._msg(
                "排名	SV ID	染色体	位置	类型	关联基因	相关系数	P值	FDR",
                "Rank	SV ID	Chromosome	Position	Type	Gene	Correlation	P-value	FDR",
            )

            lines.extend(["", table_header])

            for idx, hit in enumerate(top_hits[:target_n], start=1):
                if not isinstance(hit, dict):
                    continue

                rank = hit.get("rank") or idx
                sv_id = hit.get("sv_id") or "-"
                chrom = hit.get("chromosome") or "-"
                position = hit.get("position") or "-"
                sv_type = hit.get("sv_type") or "-"
                gene = hit.get("gene") or "-"

                corr_raw = hit.get("correlation")
                try:
                    corr_text = f"{float(corr_raw):+.6f}"
                except (TypeError, ValueError):
                    corr_text = "-"

                p_sci = hit.get("p_value_sci")
                if not p_sci:
                    p_raw = hit.get("p_value")
                    try:
                        p_sci = f"{float(p_raw):.3e}"
                    except (TypeError, ValueError):
                        p_sci = "-"

                fdr_sci = hit.get("fdr_sci")
                if not fdr_sci:
                    fdr_raw = hit.get("fdr")
                    try:
                        fdr_sci = f"{float(fdr_raw):.3e}"
                    except (TypeError, ValueError):
                        fdr_sci = "-"

                lines.append(
                    f"{rank}	{sv_id}	{chrom}	{position}	{sv_type}	{gene}	{corr_text}	{p_sci}	{fdr_sci}"
                )

            report = "\n".join(lines).rstrip()
            if report:
                return report
            return ""

        return ""

    def _append_query_sv_default_summary(
        self,
        answer: str,
        tool_calls: List[Dict[str, Any]],
        user_message: str = "",
    ) -> str:
        answer_lower = answer.lower()
        asks_distribution = self._user_asks_frequency_distribution(user_message)
        if not asks_distribution and ("驯化程度" in answer or "domestication" in answer_lower):
            return answer

        target_summary = None
        target_tier_summary = None
        target_sv_id = None
        for call in reversed(tool_calls):
            if not isinstance(call, dict):
                continue

            tool_meta = call.get("tool", {})
            tool_func = tool_meta.get("function", {}) if isinstance(tool_meta, dict) else {}
            tool_name = tool_func.get("name")
            if tool_name != "query_sv":
                continue

            args: Dict[str, Any] = {}
            try:
                args = json.loads(tool_func.get("arguments", "{}"))
            except Exception:
                args = {}

            query_type = str(args.get("query_type", "")).strip().lower()
            if query_type not in {"id", "sv_id"}:
                continue

            tool_result = call.get("result", {})
            if not isinstance(tool_result, dict) or tool_result.get("status") != "success":
                continue

            rows = tool_result.get("results")
            if not isinstance(rows, list) or not rows:
                continue

            first_row = rows[0]
            if not isinstance(first_row, dict):
                continue

            target_sv_id = first_row.get("id")
            tier_summary = first_row.get("frequency_tier_summary") or tool_result.get("frequency_tier_summary")
            if isinstance(tier_summary, dict) and tier_summary.get("available"):
                target_tier_summary = tier_summary

            domestication_summary = first_row.get("domestication_summary")
            if isinstance(domestication_summary, dict) and domestication_summary.get("available"):
                target_summary = {
                    "sv_id": target_sv_id,
                    "summary": domestication_summary,
                }
            if target_tier_summary or target_summary:
                break

        lines: List[str] = []

        if target_tier_summary and (asks_distribution or "品种频率分布" not in answer):
            sv_id = target_sv_id or "-"
            lines.extend(
                [
                    self._msg(
                        f"## {sv_id} 品种频率分布（工具结果）",
                        f"## Breed frequency distribution for {sv_id} (from tool data)",
                    ),
                    self._msg(
                        f"- 平均频率: {target_tier_summary.get('mean_frequency', '-')}",
                        f"- Mean frequency: {target_tier_summary.get('mean_frequency', '-')}",
                    ),
                    self._msg(
                        f"- 覆盖品种数: {target_tier_summary.get('breed_total', '-')}",
                        f"- Breeds covered: {target_tier_summary.get('breed_total', '-')}",
                    ),
                ]
            )
            for tier in target_tier_summary.get("tiers", [])[:5]:
                if not isinstance(tier, dict):
                    continue
                label = tier.get("label", tier.get("tier", "-"))
                count = tier.get("breed_count", "-")
                samples = tier.get("sample_breeds") or []
                sample_text = ", ".join(
                    f"{item.get('breed')}({item.get('frequency')})"
                    for item in samples[:5]
                    if isinstance(item, dict)
                )
                omitted = tier.get("omitted_count") or 0
                suffix = self._msg(f"，其余 {omitted} 个未展开", f", {omitted} more omitted") if omitted else ""
                lines.append(
                    self._msg(
                        f"- {label}: {count} 个品种" + (f" — {sample_text}{suffix}" if sample_text else ""),
                        f"- {label}: {count} breeds" + (f" — {sample_text}{suffix}" if sample_text else ""),
                    )
                )

        if not target_summary:
            if lines:
                return answer.rstrip() + "\n\n" + "\n".join(lines).strip()
            return answer

        sv_id = target_summary.get("sv_id") or "-"
        summary = target_summary["summary"]
        groups = summary.get("groups") if isinstance(summary.get("groups"), list) else []
        if not groups and not lines:
            return answer

        if groups:
            lines.append(
                self._msg(
                    f"### 按驯化程度分类（SV={sv_id}）",
                    f"### By domestication category (SV={sv_id})",
                )
            )

        for group in groups[:3]:
            if not isinstance(group, dict):
                continue
            category = group.get("category", "-")
            mean_freq = group.get("mean_frequency", "-")
            breed_count = group.get("breed_count", "-")
            top_breeds = group.get("top_breeds", [])
            top_text = ""
            if isinstance(top_breeds, list) and top_breeds:
                top_tokens = []
                for item in top_breeds[:2]:
                    if not isinstance(item, dict):
                        continue
                    bname = item.get("breed", "-")
                    bfreq = item.get("frequency", "-")
                    top_tokens.append(f"{bname}({bfreq})")
                if top_tokens:
                    top_text = ", ".join(top_tokens)

            lines.append(
                self._msg(
                    f"- {category}: 平均频率={mean_freq}, 品种数={breed_count}" + (f"，代表品种={top_text}" if top_text else ""),
                    f"- {category}: mean frequency={mean_freq}, breed count={breed_count}" + (f", representative breeds={top_text}" if top_text else ""),
                )
            )

        observation = summary.get("observation")
        if observation:
            lines.append(self._msg(f"- 观察: {observation}", f"- Observation: {observation}"))

        appendix = "\n".join(lines).strip()
        if not appendix:
            return answer

        return answer.rstrip() + "\n\n" + appendix


    def _user_asks_frequency_distribution(self, user_message: str) -> bool:
        if not user_message:
            return False
        text = user_message.lower()
        zh_markers = ["频率分布", "分布规律", "分布特征", "分布模式", "频率分层", "频率模式"]
        en_markers = [
            "frequency distribution",
            "distribution pattern",
            "breed frequency",
            "frequency pattern",
            "frequency profile",
        ]
        return any(m in user_message for m in zh_markers) or any(m in text for m in en_markers)

    _SV_ID_PATTERN = re.compile(r"\d+_\d+_(?:DEL|INS)", re.IGNORECASE)

    def _user_asks_gwas_scan(self, user_message: str) -> bool:
        if not user_message:
            return False
        text = user_message.lower()
        zh_markers = [
            "全基因组",
            "关联扫描",
            "gwas",
            "top50",
            "top 50",
            "候选位点",
            "候选 sv",
        ]
        en_markers = [
            "genome-wide",
            "genome wide",
            "association scan",
            "gwas",
            "top candidate",
            "candidate sv",
        ]
        return any(m in user_message.lower() or m in text for m in zh_markers + en_markers)

    def _needs_literature_kb(self, user_message: str) -> bool:
        if not user_message:
            return False
        text = user_message.lower()

        explicit_kb_markers = [
            "文献",
            "知识库",
            "论文",
            "期刊",
            "研究进展",
            "研究背景",
            "有没有研究",
            "结合文献",
            "文献证据",
            "文献支持",
            "literature",
            "publication",
            "journal",
            "prior study",
            "citation",
        ]
        if any(m in user_message or m in text for m in explicit_kb_markers):
            if self._user_asks_frequency_distribution(user_message):
                interpret_markers = ["解释", "机制", "功能", "explain", "function", "mechanism"]
                if not any(m in user_message or m in text for m in interpret_markers):
                    return False
            return True

        if self._user_asks_frequency_distribution(user_message):
            return False
        if self._user_asks_gwas_scan(user_message):
            return False
        if self._SV_ID_PATTERN.search(user_message):
            data_only_markers = [
                "频率",
                "分布",
                "查询",
                "位点",
                "变异",
                "注释",
                "关联",
                "相关",
                "frequency",
                "distribution",
                "query",
                "variant",
                "annotation",
                "correlation",
            ]
            if any(m in user_message or m in text for m in data_only_markers):
                interpret_markers = [
                    "机制",
                    "功能",
                    "解释",
                    "mechanism",
                    "function",
                    "explain",
                ]
                if not any(m in user_message or m in text for m in interpret_markers):
                    return False

        block_markers = [
            "频率",
            "分布",
            "query_sv",
            "位点查询",
            "区域查询",
            "注释",
            "填充",
            "imputation",
            "工作区",
            "workspace",
            "数据库统计",
            "有多少",
            "相关系数",
            "p值",
            "p-value",
            "frequency",
            "distribution",
            "annotation",
            "imputation",
            "correlation",
            "coefficient",
        ]
        allow_markers = [
            "方法学",
            "原理",
            "methodology",
            "基因功能",
            "生物学意义",
            "生物学解释",
            "机制",
            "为什么",
            "gene function",
            "biological",
            "mechanism",
            "why does",
            "why is",
        ]
        breed_markers = [
            "品种特征",
            "品种介绍",
            "什么特征",
            "羽色",
            "肤色",
            "胫色",
            "产地",
            "起源",
            "历史",
            "breed characteristic",
            "breed origin",
            "breed history",
            "feather color",
            "shank color",
        ]

        has_block = any(m in user_message or m in text for m in block_markers)
        has_allow = any(m in user_message or m in text for m in allow_markers)
        has_breed = any(m in user_message or m in text for m in breed_markers)

        if has_breed and not has_block:
            return True
        if has_allow and not has_block:
            return True
        return False

    def _has_genome_scan_tool_call(self, tool_calls: List[Dict[str, Any]]) -> bool:
        for call in tool_calls or []:
            if not isinstance(call, dict):
                continue
            tool_meta = call.get("tool", {})
            tool_func = tool_meta.get("function", {}) if isinstance(tool_meta, dict) else {}
            if tool_func.get("name") == "genome_wide_association_scan":
                return True
        return False

    def _find_latest_query_sv_id_result(
        self, tool_calls: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        for call in reversed(tool_calls or []):
            if not isinstance(call, dict):
                continue
            tool_meta = call.get("tool", {})
            tool_func = tool_meta.get("function", {}) if isinstance(tool_meta, dict) else {}
            if tool_func.get("name") != "query_sv":
                continue
            try:
                args = json.loads(tool_func.get("arguments", "{}"))
            except Exception:
                args = {}
            if str(args.get("query_type", "")).strip().lower() not in {"id", "sv_id"}:
                continue
            tool_result = call.get("result", {})
            if isinstance(tool_result, dict) and tool_result.get("status") == "success":
                return tool_result
        return None

    def _answer_looks_like_gwas_report(self, answer: str) -> bool:
        if not answer:
            return False
        lowered = answer.lower()
        markers = [
            "genome-wide association",
            "全基因组",
            "top 50 candidate",
            "candidate svs associated",
            "p-value",
            "rank\tsv id",
        ]
        return sum(1 for m in markers if m in lowered or m in answer) >= 2

    def _correct_misaligned_gwas_answer(
        self,
        answer: str,
        tool_calls: List[Dict[str, Any]],
        user_message: str,
    ) -> str:
        if self._has_genome_scan_tool_call(tool_calls):
            return answer
        if not self._answer_looks_like_gwas_report(answer):
            return answer

        if self._user_asks_gwas_scan(user_message):
            notice = self._msg(
                "（说明：本轮未执行 genome_wide_association_scan，以下 GWAS 排行不能作为真实结果。"
                "如需全基因组候选位点，请明确调用该工具。）",
                "(Note: genome_wide_association_scan was not run; any GWAS ranking below is not "
                "from tool output. Call that tool for real genome-wide candidates.)",
            )
            return notice + "\n\n" + answer

        sv_result = self._find_latest_query_sv_id_result(tool_calls)
        if not sv_result:
            return answer

        rows = sv_result.get("results") or []
        first_row = rows[0] if rows and isinstance(rows[0], dict) else {}
        sv_id = first_row.get("id") or sv_result.get("query", {}).get("value") or "target SV"
        tier_summary = first_row.get("frequency_tier_summary") or sv_result.get("frequency_tier_summary")

        notice = self._msg(
            "（说明：本轮未执行全基因组关联扫描；以下根据 query_sv 返回的品种频率数据回答。）",
            "(Note: no genome-wide association scan was run in this turn; answer based on query_sv breed frequencies.)",
        )
        rebuilt = self._append_query_sv_default_summary("", tool_calls, user_message).strip()
        if rebuilt:
            return f"{notice}\n\n{rebuilt}"
        if isinstance(tier_summary, dict) and tier_summary.get("available"):
            return f"{notice}\n\n{sv_id} mean frequency: {tier_summary.get('mean_frequency')}"
        return notice + "\n\n" + answer

    def _extract_requested_top_n(self, user_message: str) -> Optional[int]:
        if not user_message:
            return None

        lowered = user_message.lower()
        patterns = [
            r"top\s*([1-9]\d{0,3})",
            r"前\s*([1-9]\d{0,3})\s*(?:个|条|位|名)?",
        ]

        for pattern in patterns:
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue

        return None

    def _append_genome_scan_full_hits(
        self,
        answer: str,
        tool_calls: List[Dict[str, Any]],
        user_message: str,
    ) -> str:
        if not tool_calls:
            return answer

        latest_call: Optional[Dict[str, Any]] = None
        latest_args: Dict[str, Any] = {}

        for call in reversed(tool_calls):
            if not isinstance(call, dict):
                continue
            tool_meta = call.get("tool", {})
            tool_func = tool_meta.get("function", {}) if isinstance(tool_meta, dict) else {}
            tool_name = tool_func.get("name")
            if tool_name != "genome_wide_association_scan":
                continue

            tool_result = call.get("result", {})
            if not isinstance(tool_result, dict) or tool_result.get("status") != "success":
                continue

            data = tool_result.get("data", {})
            top_hits = None
            if isinstance(data, dict):
                top_hits = data.get("top_hits") or data.get("top_hits_compact") or data.get("top_hits_preview")
            if not isinstance(top_hits, list) or not top_hits:
                continue

            latest_call = call
            try:
                latest_args = json.loads(tool_func.get("arguments", "{}"))
            except Exception:
                latest_args = {}
            break

        if not latest_call:
            return answer

        tool_result = latest_call.get("result", {})
        data = tool_result.get("data", {}) if isinstance(tool_result, dict) else {}
        top_hits = None
        if isinstance(data, dict):
            top_hits = data.get("top_hits") or data.get("top_hits_compact") or data.get("top_hits_preview")
        if not isinstance(top_hits, list) or not top_hits:
            return answer

        requested_values: List[int] = []
        for raw in (
            latest_args.get("top_n"),
            data.get("returned_top_n"),
            self._extract_requested_top_n(user_message),
        ):
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue
            if val > 0:
                requested_values.append(val)

        if not requested_values:
            return answer

        requested_n = max(requested_values)
        target_n = min(len(top_hits), requested_n)
        if target_n <= 10:
            return answer

        phenotype = data.get("phenotype_name") or self._infer_phenotype_from_message(user_message)
        tested_variant_count = (
            data.get("tested_variant_count")
            or data.get("total_tests")
            or data.get("tested_variants")
            or "-"
        )
        significant_variant_count = (
            data.get("significant_variant_count")
            or data.get("significant_hits")
            or data.get("significant_loci")
            or "-"
        )

        strongest_hit = data.get("top_hit")
        if not isinstance(strongest_hit, dict):
            strongest_hit = top_hits[0] if top_hits and isinstance(top_hits[0], dict) else {}

        strongest_sv_id = strongest_hit.get("sv_id") or strongest_hit.get("id") or "-"
        strongest_p = strongest_hit.get("p_value_sci") or strongest_hit.get("p_value") or "-"
        strongest_fdr = strongest_hit.get("fdr_sci") or strongest_hit.get("fdr") or "-"

        lines = [
            self._msg(
                f"## 全基因组SV关联扫描结果（P值最低前{target_n}位点）",
                f"## Genome-wide SV association scan results (top {target_n} loci by p-value)",
            ),
            self._msg(
                f"已完成对表型“{phenotype}”的全基因组关联扫描，以下按P值升序直接列出前{target_n}个候选位点。该结果是品种聚合层面的相关分析，不代表个体因果结论。",
                f"Completed a genome-wide association scan for phenotype '{phenotype}'. The following list shows the top {target_n} candidate loci sorted directly by p-value. This is a breed-aggregated association analysis, not an individual-level causal conclusion.",
            ),
        ]

        if tested_variant_count != "-" or significant_variant_count != "-":
            lines.append(
                self._msg(
                    f"关键统计：测试位点数={tested_variant_count}，显著关联位点数={significant_variant_count}，最强关联信号={strongest_sv_id}（P={strongest_p}，FDR={strongest_fdr}）。",
                    f"Key stats: tested variants={tested_variant_count}, significant loci={significant_variant_count}, strongest signal={strongest_sv_id} (P={strongest_p}, FDR={strongest_fdr}).",
                )
            )

        table_header = self._msg(
            "排名	SV ID	染色体	位置	类型	关联基因	相关系数	P值	FDR",
            "Rank	SV ID	Chromosome	Position	Type	Gene	Correlation	P-value	FDR",
        )

        lines.extend(["", table_header])

        for idx, hit in enumerate(top_hits[:target_n], start=1):
            if not isinstance(hit, dict):
                continue

            rank = hit.get("rank") or idx
            sv_id = hit.get("sv_id") or "-"
            chrom = hit.get("chromosome") or "-"
            position = hit.get("position") or "-"
            sv_type = hit.get("sv_type") or "-"
            gene = hit.get("gene") or "-"

            corr_raw = hit.get("correlation")
            try:
                corr_text = f"{float(corr_raw):+.6f}"
            except (TypeError, ValueError):
                corr_text = "-"

            p_sci = hit.get("p_value_sci")
            if not p_sci:
                p_raw = hit.get("p_value")
                try:
                    p_sci = f"{float(p_raw):.3e}"
                except (TypeError, ValueError):
                    p_sci = "-"

            fdr_sci = hit.get("fdr_sci")
            if not fdr_sci:
                fdr_raw = hit.get("fdr")
                try:
                    fdr_sci = f"{float(fdr_raw):.3e}"
                except (TypeError, ValueError):
                    fdr_sci = "-"

            lines.append(
                f"{rank}	{sv_id}	{chrom}	{position}	{sv_type}	{gene}	{corr_text}	{p_sci}	{fdr_sci}"
            )

        report = "\n".join(lines).rstrip()
        if report:
            return report

        return answer

    def _count_cjk_chars(self, text: str) -> int:
        return sum(1 for ch in text if "一" <= ch <= "鿿")

    def _count_ascii_letters(self, text: str) -> int:
        return sum(1 for ch in text if ("a" <= ch.lower() <= "z"))

    def _detect_preferred_language(self, user_message: str) -> str:
        if not user_message:
            return "zh"

        lowered = user_message.lower()
        english_markers = [
            "in english",
            "answer in english",
            "respond in english",
            "english please",
            "use english",
        ]
        chinese_markers = ["用中文", "中文回答", "请用中文", "中文"]

        if any(marker in lowered for marker in english_markers):
            return "en"
        if any(marker in user_message for marker in chinese_markers):
            return "zh"

        cjk_count = self._count_cjk_chars(user_message)
        ascii_count = self._count_ascii_letters(user_message)

        if ascii_count > 0 and cjk_count == 0:
            return "en"
        if cjk_count > 0 and ascii_count == 0:
            return "zh"

        if ascii_count >= cjk_count * 2:
            return "en"
        return "zh"

    def _msg(self, zh_text: str, en_text: str) -> str:
        return en_text if self._preferred_language == "en" else zh_text

    def _needs_english_rewrite(self, answer: str) -> bool:
        if self._preferred_language != "en":
            return False
        cjk_count = self._count_cjk_chars(answer)
        if cjk_count == 0:
            return False
        ascii_count = self._count_ascii_letters(answer)
        return cjk_count >= 8 or cjk_count > ascii_count

    async def _normalize_answer_language(self, answer: str) -> str:
        if not answer:
            return answer
        if not self._needs_english_rewrite(answer):
            return answer

        try:
            rewrite_messages = [
                LLMMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Rewrite the following answer into fluent English only. "
                        "Do not add new facts, do not omit key details, and keep numeric values unchanged."
                    ),
                ),
                LLMMessage(role=MessageRole.USER, content=answer),
            ]
            rewritten = await self.llm.chat(rewrite_messages, tools=None, temperature=0.0)
            rewritten_text = (rewritten.content or "").strip()
            if rewritten_text:
                return rewritten_text
        except Exception:
            logger.warning("语言重写失败，保留原回答", exc_info=True)

        return answer

    def _get_llm_tools(self) -> List[LLMToolDefinition]:
        """获取LLM格式的工具定义"""
        return self.tool_registry.get_llm_tool_definitions()

    def _build_system_prompt(
        self,
        tools: List[LLMToolDefinition],
        preferred_language: Optional[str] = None,
    ) -> str:
        """构建系统提示词"""
        tools_desc = ""
        for t in tools:
            tools_desc += f"\n- {t.name}: {t.description}"
            if t.parameters.get("properties"):
                params = list(t.parameters["properties"].keys())
                tools_desc += f" (参数: {', '.join(params)})"

        custom_prompt = self.llm_config.system_prompt
        prompt_template = custom_prompt if custom_prompt else DEFAULT_SYSTEM_PROMPT

        lang = preferred_language or self._preferred_language
        if lang == "en":
            language_guard = (
                "\n\n## Response Language\n"
                "- The latest user message is in English.\n"
                "- Respond entirely in English.\n"
                "- Do not mix Chinese unless the user explicitly asks for bilingual output."
            )
        else:
            language_guard = (
                "\n\n## 回复语言\n"
                "- 当前用户主要使用中文。\n"
                "- 默认使用中文完整回答。\n"
                "- 只有用户明确要求英文或双语时才切换语言。"
            )
        if "{tools_description}" in prompt_template:
            base_prompt = prompt_template.format(tools_description=tools_desc)
        else:
            base_prompt = prompt_template + "\n\n## 可用工具\n" + tools_desc

        if lang == "en":
            origin_guard = (
                "\n\n## Breed Origin Guard\n"
                "- Never infer a breed's country/region/province from its name, transliteration, or memory.\n"
                "- Do not infer country from latitude/longitude alone.\n"
                "- If no explicit country/admin field or citation exists, state that country attribution is unavailable and provide only returned structured fields (e.g., coordinates, categories).\n"
                "- If the user explicitly provides origin information and there is no conflict with tool evidence, keep the user-provided fact."
            )
        else:
            origin_guard = (
                "\n\n## 品种归属防幻觉约束\n"
                "- 严禁根据品种名称、译名或记忆直接推断所属国家/地区/省份。\n"
                "- 严禁仅凭经纬度自动反推国家归属。\n"
                "- 若工具结果没有明确国家/行政区字段或可引用证据，必须明确写“国家归属暂无直接字段证据”，并仅报告返回的结构化字段（如经纬度、分类）。\n"
                "- 若用户明确提供归属信息且与工具结果不冲突，优先采用用户提供的事实。"
            )

        kb_guard = (
            "\n\n## 文献知识库边界\n"
            "- query_literature_kb 仅用于文献/方法学/品种背景/基因功能解释类问题。\n"
            "- SV 查询、频率分布、注释、关联分析、GWAS 扫描、填充工作区等问题禁止调用 query_literature_kb。\n"
            "- 未调用 genome_wide_association_scan 时，禁止输出 GWAS Top 排行榜或编造相关系数/P 值。\n"
            "- 回答必须优先使用已调用工具的真实返回；知识库片段不得覆盖或污染数据库结果。"
        )
        if lang == "en":
            kb_guard = (
                "\n\n## Literature KB Guard\n"
                "- Use query_literature_kb only for literature, methodology, breed background, "
                "or gene-function questions.\n"
                "- Do NOT call it for SV lookup, frequency distribution, annotation, association, "
                "GWAS scan, or imputation workflow questions.\n"
                "- Never output a GWAS ranking or fabricated correlation/p-values unless "
                "genome_wide_association_scan was executed.\n"
                "- Tool outputs take precedence; KB snippets must not override database results."
            )

        return base_prompt + language_guard + origin_guard + kb_guard

    def _format_messages(
        self, messages: List[LLMMessage], system_prompt: str
    ) -> List[LLMMessage]:
        """格式化消息列表，添加系统提示词"""
        formatted = [LLMMessage(role=MessageRole.SYSTEM, content=system_prompt)]
        for msg in messages:
            if msg.role != MessageRole.SYSTEM:
                formatted.append(msg)
        return formatted

    def _get_action_signature(self, tool_calls: List[Dict[str, Any]]) -> str:
        """生成工具调用的签名，用于重复检测"""
        sigs = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str)
                sorted_args = json.dumps(args, sort_keys=True)
            except json.JSONDecodeError:
                sorted_args = args_str
            sigs.append(f"{name}:{sorted_args}")
        return "|".join(sigs)

    def _is_repeated_action(self, action_sig: str) -> bool:
        """检测是否为重复的工具调用"""
        return action_sig in self._step_history

    async def close(self):
        """清理资源"""
        if hasattr(self.llm, "close"):
            await self.llm.close()
