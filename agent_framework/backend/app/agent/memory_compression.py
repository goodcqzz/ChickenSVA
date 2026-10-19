"""
对话历史压缩模块

提供智能对话摘要功能：
- 自动检测对话长度阈值
- 保留关键信息和语义连贯性
- 支持多种压缩策略
- 可配置的压缩触发条件

使用示例:
    compressor = MemoryCompressor()
    
    # 检查是否需要压缩
    if compressor.should_compress(messages):
        summary = await compressor.compress(messages)
        messages = compressor.replace_with_summary(messages, summary)
"""

import json
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib

from app.llm.base import LLMConfig, LLMMessage, MessageRole
from app.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


@dataclass
class CompressionConfig:
    """压缩配置"""
    # 触发条件
    max_messages: int = 20           # 最大消息数，超过则触发压缩
    max_tokens: int = 4000           # 最大token数（估算）
    max_chars: int = 15000           # 最大字符数
    
    # 压缩策略
    strategy: str = "summary"        # 压缩策略: summary, extraction, hybrid
    preserve_recent: int = 4         # 保留最近N条消息不压缩
    
    # 摘要生成
    summary_model: str = "qwen-turbo"  # 用于摘要的轻量级模型
    summary_max_tokens: int = 500      # 摘要最大长度
    summary_temperature: float = 0.3   # 摘要温度（低温度更稳定）
    
    # 高级选项
    enable_entity_extraction: bool = True   # 是否提取关键实体
    enable_intent_preservation: bool = True # 是否保留用户意图
    compress_code_blocks: bool = True       # 是否压缩代码块


@dataclass
class CompressionResult:
    """压缩结果"""
    original_count: int
    compressed_count: int
    summary: str
    preserved_messages: List[Dict[str, str]]
    compression_ratio: float
    entities: List[str]
    key_points: List[str]


class MemoryCompressor:
    """
    对话历史压缩器
    
    实现智能对话摘要，在保留关键信息的同时减少上下文长度
    """
    
    def __init__(self, config: Optional[CompressionConfig] = None):
        self.config = config or CompressionConfig()
        self._llm = None
        
        # 压缩统计
        self._compression_count = 0
        self._total_saved_tokens = 0
    
    async def _get_llm(self):
        """获取或创建 LLM 实例"""
        if self._llm is None:
            config = LLMConfig(
                provider="qwen",
                model=self.config.summary_model,
                temperature=self.config.summary_temperature,
                max_tokens=self.config.summary_max_tokens,
            )
            self._llm = LLMFactory.create(config)
        return self._llm
    
    def should_compress(self, messages: List[Dict[str, str]]) -> bool:
        """
        检查是否需要压缩
        
        Args:
            messages: 消息列表
            
        Returns:
            是否需要压缩
        """
        if len(messages) <= self.config.preserve_recent:
            return False
        
        # 检查消息数
        if len(messages) > self.config.max_messages:
            return True
        
        # 检查字符数
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars > self.config.max_chars:
            return True
        
        # 估算token数（粗略估算：1 token ≈ 4 chars for Chinese）
        estimated_tokens = total_chars / 4
        if estimated_tokens > self.config.max_tokens:
            return True
        
        return False
    
    async def compress(
        self,
        messages: List[Dict[str, str]],
        context: Optional[str] = None
    ) -> CompressionResult:
        """
        压缩对话历史
        
        Args:
            messages: 消息列表
            context: 额外上下文信息（可选）
            
        Returns:
            压缩结果
        """
        if not self.should_compress(messages):
            return CompressionResult(
                original_count=len(messages),
                compressed_count=len(messages),
                summary="",
                preserved_messages=messages,
                compression_ratio=1.0,
                entities=[],
                key_points=[]
            )
        
        try:
            # 分离需要压缩和保留的消息
            messages_to_compress = messages[:-self.config.preserve_recent]
            preserved_messages = messages[-self.config.preserve_recent:]
            
            # 根据策略选择压缩方法
            if self.config.strategy == "summary":
                summary = await self._generate_summary(messages_to_compress, context)
            elif self.config.strategy == "extraction":
                summary = await self._extract_key_points(messages_to_compress)
            else:  # hybrid
                summary = await self._hybrid_compress(messages_to_compress, context)
            
            # 提取实体
            entities = []
            if self.config.enable_entity_extraction:
                entities = await self._extract_entities(messages_to_compress)
            
            # 计算压缩比
            original_chars = sum(len(m.get("content", "")) for m in messages_to_compress)
            compressed_chars = len(summary)
            compression_ratio = compressed_chars / original_chars if original_chars > 0 else 1.0
            
            # 更新统计
            self._compression_count += 1
            self._total_saved_tokens += int((original_chars - compressed_chars) / 4)
            
            logger.info(
                f"对话历史已压缩: {len(messages_to_compress)} -> 1 条摘要, "
                f"压缩比: {compression_ratio:.2%}"
            )
            
            return CompressionResult(
                original_count=len(messages),
                compressed_count=1 + len(preserved_messages),
                summary=summary,
                preserved_messages=preserved_messages,
                compression_ratio=compression_ratio,
                entities=entities,
                key_points=self._extract_key_points_simple(messages_to_compress)
            )
            
        except Exception as e:
            logger.error(f"对话压缩失败: {e}")
            # 压缩失败，返回原始消息
            return CompressionResult(
                original_count=len(messages),
                compressed_count=len(messages),
                summary="",
                preserved_messages=messages,
                compression_ratio=1.0,
                entities=[],
                key_points=[]
            )
    
    def replace_with_summary(
        self,
        messages: List[Dict[str, str]],
        result: CompressionResult
    ) -> List[Dict[str, str]]:
        """
        用摘要替换原始消息
        
        Args:
            messages: 原始消息列表
            result: 压缩结果
            
        Returns:
            替换后的消息列表
        """
        if not result.summary:
            return messages
        
        # 构建摘要消息
        summary_content = f"【历史对话摘要】\n{result.summary}"
        
        if result.entities:
            summary_content += f"\n\n【关键实体】\n{', '.join(result.entities)}"
        
        summary_message = {
            "role": "system",
            "content": summary_content
        }
        
        # 组合：摘要 + 保留的消息
        return [summary_message] + result.preserved_messages
    
    async def _generate_summary(
        self,
        messages: List[Dict[str, str]],
        context: Optional[str] = None
    ) -> str:
        """生成对话摘要"""
        llm = await self._get_llm()
        
        # 构建提示词
        conversation_text = self._format_conversation(messages)
        
        prompt = f"""请对以下对话历史进行摘要，保留关键信息和上下文：

{conversation_text}

请生成一个简洁的摘要，包含：
1. 用户的主要意图和需求
2. 已经讨论过的关键信息
3. 当前的进展状态
4. 待解决或待确认的问题

摘要要求：
- 使用第三人称客观描述
- 保留具体的数据、名称、参数等重要信息
- 长度控制在 300 字以内
- 使用中文输出"""

        if context:
            prompt = f"【上下文】{context}\n\n{prompt}"
        
        try:
            response = await llm.chat([
                LLMMessage(role=MessageRole.SYSTEM, content="你是一个专业的对话摘要助手。"),
                LLMMessage(role=MessageRole.USER, content=prompt)
            ])
            
            return response.content.strip()
        except Exception as e:
            logger.error(f"摘要生成失败: {e}")
            return self._fallback_summary(messages)
    
    async def _extract_key_points(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """提取关键要点"""
        llm = await self._get_llm()
        
        conversation_text = self._format_conversation(messages)
        
        prompt = f"""请从以下对话中提取关键要点：

{conversation_text}

请以 bullet points 形式列出：
- 用户的每个请求或问题
- 系统提供的每个重要回答或结果
- 做出的每个决定或共识
- 需要后续跟进的事项"""

        try:
            response = await llm.chat([
                LLMMessage(role=MessageRole.SYSTEM, content="你是一个关键信息提取助手。"),
                LLMMessage(role=MessageRole.USER, content=prompt)
            ])
            
            return response.content.strip()
        except Exception as e:
            logger.error(f"要点提取失败: {e}")
            return self._fallback_summary(messages)
    
    async def _hybrid_compress(
        self,
        messages: List[Dict[str, str]],
        context: Optional[str] = None
    ) -> str:
        """混合压缩策略"""
        # 先生成摘要，再提取要点
        summary = await self._generate_summary(messages, context)
        key_points = await self._extract_key_points(messages)
        
        return f"摘要：\n{summary}\n\n关键要点：\n{key_points}"
    
    async def _extract_entities(
        self,
        messages: List[Dict[str, str]]
    ) -> List[str]:
        """提取关键实体"""
        # 简单的实体提取（可扩展为使用 NER 模型）
        entities = set()
        
        for msg in messages:
            content = msg.get("content", "")
            
            # 提取基因名（大写字母+数字）
            import re
            genes = re.findall(r'\b[A-Z]{2,}[0-9]*\b', content)
            entities.update(genes)
            
            # 提取染色体位置
            positions = re.findall(r'chr\d+:\d+-\d+', content, re.IGNORECASE)
            entities.update(positions)
            
            # 提取品种名（引号内）
            breeds = re.findall(r'["\']([^"\']*?鸡[^"\']*?)["\']', content)
            entities.update(breeds)
        
        return list(entities)[:20]  # 限制数量
    
    def _extract_key_points_simple(
        self,
        messages: List[Dict[str, str]]
    ) -> List[str]:
        """简单的关键要点提取（无需 LLM）"""
        key_points = []
        
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")[:100]  # 截取前100字符
                if content:
                    key_points.append(f"用户: {content}...")
            elif msg.get("role") == "assistant":
                content = msg.get("content", "")[:100]
                if content and len(content) > 20:  # 过滤太短的回复
                    key_points.append(f"助手: {content}...")
        
        return key_points[:10]  # 限制数量
    
    def _format_conversation(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """格式化对话为文本"""
        lines = []
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
            elif role == "system":
                lines.append(f"系统: {content}")
        
        return "\n\n".join(lines)
    
    def _fallback_summary(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """备用摘要方法（当 LLM 失败时使用）"""
        # 提取用户消息作为摘要
        user_messages = [
            m.get("content", "")[:100]
            for m in messages
            if m.get("role") == "user"
        ]
        
        if user_messages:
            return "历史对话涉及: " + "; ".join(user_messages[:3])
        
        return f"共 {len(messages)} 条历史消息"
    
    def get_stats(self) -> Dict[str, Any]:
        """获取压缩统计"""
        return {
            "compression_count": self._compression_count,
            "total_saved_tokens": self._total_saved_tokens,
            "config": {
                "max_messages": self.config.max_messages,
                "strategy": self.config.strategy,
                "preserve_recent": self.config.preserve_recent,
            }
        }


class SlidingWindowMemory:
    """
    滑动窗口对话管理
    
    简单的窗口截断策略，保留最近 N 条消息
    """
    
    def __init__(self, max_messages: int = 20, preserve_system: bool = True):
        self.max_messages = max_messages
        self.preserve_system = preserve_system
    
    def process(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        应用滑动窗口
        
        Args:
            messages: 消息列表
            
        Returns:
            截断后的消息列表
        """
        if len(messages) <= self.max_messages:
            return messages
        
        if self.preserve_system:
            # 保留系统消息
            system_messages = [m for m in messages if m.get("role") == "system"]
            other_messages = [m for m in messages if m.get("role") != "system"]
            
            # 保留最近的 N 条非系统消息
            kept_other = other_messages[-(self.max_messages - len(system_messages)):]
            
            return system_messages + kept_other
        else:
            # 直接截断
            return messages[-self.max_messages:]


# 全局压缩器实例
_memory_compressor: Optional[MemoryCompressor] = None


def init_memory_compressor(config: Optional[CompressionConfig] = None) -> MemoryCompressor:
    """初始化全局记忆压缩器"""
    global _memory_compressor
    _memory_compressor = MemoryCompressor(config)
    return _memory_compressor


def get_memory_compressor() -> Optional[MemoryCompressor]:
    """获取全局记忆压缩器"""
    return _memory_compressor
