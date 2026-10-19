#!/usr/bin/env python3
"""
对话状态管理器 - 追踪和管理对话状态
用于解决多轮对话场景下的状态管理问题
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
import json
import threading


class ConversationPhase(Enum):
    """对话阶段"""
    INITIAL = "initial"                    # 初始阶段
    GREETING = "greeting"                  # 问候阶段
    REQUIREMENT_GATHERING = "requirement_gathering"  # 需求收集
    TOOL_EXECUTING = "tool_executing"      # 工具执行中
    RESULT_PRESENTING = "result_presenting" # 结果展示
    UPLOAD_WAITING = "upload_waiting"      # 等待上传
    CLARIFICATION = "clarification"        # 需要澄清
    COMPLETION = "completion"              # 对话完成


class IntentType(Enum):
    """用户意图类型"""
    QUERY = "query"                        # 查询
    IMPUTATION = "imputation"             # 数据填充
    ANALYSIS = "analysis"                 # 分析
    UPLOAD = "upload"                     # 上传
    HELP = "help"                         # 帮助
    GREETING = "greeting"                 # 问候
    UNKNOWN = "unknown"                   # 未知


@dataclass
class Intent:
    """用户意图"""
    type: IntentType
    confidence: float
    entities: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class Message:
    """对话消息"""
    role: str  # user / assistant / system / tool
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    intent: Optional[Intent] = None
    tool_calls: List[Dict] = field(default_factory=list)
    tool_results: List[Dict] = field(default_factory=list)


@dataclass
class ConversationContext:
    """对话上下文"""
    # 当前工作区
    current_workspace_id: Optional[str] = None
    
    # 当前任务
    current_task_id: Optional[str] = None
    
    # 收集到的参数
    collected_params: Dict[str, Any] = field(default_factory=dict)
    
    # 待确认的参数
    pending_confirmations: List[str] = field(default_factory=list)
    
    # 已查询的数据缓存
    data_cache: Dict[str, Any] = field(default_factory=dict)
    
    # 用户偏好
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    
    def set_workspace(self, workspace_id: str):
        """设置当前工作区"""
        self.current_workspace_id = workspace_id
        
    def set_param(self, key: str, value: Any):
        """设置参数"""
        self.collected_params[key] = value
        
    def get_param(self, key: str, default=None):
        """获取参数"""
        return self.collected_params.get(key, default)
    
    def cache_data(self, key: str, data: Any):
        """缓存数据"""
        self.data_cache[key] = {
            'data': data,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def get_cached_data(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        cached = self.data_cache.get(key)
        if cached:
            return cached['data']
        return None


@dataclass
class ConversationSession:
    """对话会话"""
    session_id: str
    phase: ConversationPhase = ConversationPhase.INITIAL
    messages: List[Message] = field(default_factory=list)
    context: ConversationContext = field(default_factory=ConversationContext)
    
    # 统计
    message_count: int = 0
    tool_call_count: int = 0
    turn_count: int = 0
    
    # 时间戳
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # 配置
    max_history: int = 20
    
    def add_message(self, message: Message):
        """添加消息"""
        self.messages.append(message)
        self.message_count += 1
        self.last_activity = datetime.now(timezone.utc)
        
        # 限制历史记录长度
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def get_recent_messages(self, n: int = 5) -> List[Message]:
        """获取最近n条消息"""
        return self.messages[-n:] if len(self.messages) >= n else self.messages
    
    def update_phase(self, new_phase: ConversationPhase):
        """更新对话阶段"""
        old_phase = self.phase
        self.phase = new_phase
        print(f"[Session {self.session_id}] Phase: {old_phase.value} -> {new_phase.value}")
    
    def increment_turn(self):
        """增加轮次计数"""
        self.turn_count += 1
        self.tool_call_count = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'phase': self.phase.value,
            'message_count': self.message_count,
            'turn_count': self.turn_count,
            'tool_call_count': self.tool_call_count,
            'current_workspace': self.context.current_workspace_id,
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat()
        }


class ConversationStateManager:
    """
    对话状态管理器
    
    功能：
    1. 管理所有对话会话
    2. 追踪对话阶段和意图
    3. 提供上下文管理
    4. 支持多轮对话状态保持
    """
    
    def __init__(self, session_ttl_minutes: int = 60):
        self.session_ttl_minutes = session_ttl_minutes
        self._sessions: Dict[str, ConversationSession] = {}
        self._lock = threading.RLock()
    
    def get_or_create_session(self, session_id: str) -> ConversationSession:
        """获取或创建会话"""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = ConversationSession(session_id=session_id)
                print(f"[ConversationManager] 创建新会话: {session_id}")
            return self._sessions[session_id]
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """获取会话"""
        with self._lock:
            return self._sessions.get(session_id)
    
    def delete_session(self, session_id: str):
        """删除会话"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                print(f"[ConversationManager] 删除会话: {session_id}")
    
    def detect_intent(self, message: str, context: ConversationContext) -> Intent:
        """
        检测用户意图
        
        使用简单的规则匹配，实际可接入LLM进行更准确的识别
        """
        message_lower = message.lower()
        
        # 数据填充相关关键词
        imputation_keywords = ['填充', 'imputation', 'impute', '基因型', 'genotype', '补全']
        if any(kw in message_lower for kw in imputation_keywords):
            return Intent(
                type=IntentType.IMPUTATION,
                confidence=0.9,
                raw_text=message
            )
        
        # 查询相关关键词
        query_keywords = ['查询', '搜索', '查找', 'query', 'search', 'find', '查']
        if any(kw in message_lower for kw in query_keywords):
            return Intent(
                type=IntentType.QUERY,
                confidence=0.85,
                raw_text=message
            )
        
        # 分析相关关键词
        analysis_keywords = ['分析', '统计', '关联', 'analysis', 'analyze', 'correlation']
        if any(kw in message_lower for kw in analysis_keywords):
            return Intent(
                type=IntentType.ANALYSIS,
                confidence=0.85,
                raw_text=message
            )
        
        # 上传相关关键词
        upload_keywords = ['上传', 'upload', '文件', 'file']
        if any(kw in message_lower for kw in upload_keywords):
            return Intent(
                type=IntentType.UPLOAD,
                confidence=0.8,
                raw_text=message
            )
        
        # 帮助相关关键词
        help_keywords = ['帮助', 'help', '怎么用', '说明', '文档']
        if any(kw in message_lower for kw in help_keywords):
            return Intent(
                type=IntentType.HELP,
                confidence=0.9,
                raw_text=message
            )
        
        # 问候相关关键词
        greeting_keywords = ['你好', 'hello', 'hi', 'hey', '您好']
        if any(kw in message_lower for kw in greeting_keywords):
            return Intent(
                type=IntentType.GREETING,
                confidence=0.95,
                raw_text=message
            )
        
        return Intent(
            type=IntentType.UNKNOWN,
            confidence=0.5,
            raw_text=message
        )
    
    def should_transition_phase(
        self,
        session: ConversationSession,
        intent: Intent
    ) -> Optional[ConversationPhase]:
        """
        判断是否应转换对话阶段
        
        Returns:
            新的阶段，如果不需要转换则返回None
        """
        current_phase = session.phase
        
        # 从初始阶段转换
        if current_phase == ConversationPhase.INITIAL:
            if intent.type == IntentType.GREETING:
                return ConversationPhase.GREETING
            elif intent.type == IntentType.IMPUTATION:
                return ConversationPhase.REQUIREMENT_GATHERING
            elif intent.type in [IntentType.QUERY, IntentType.ANALYSIS]:
                return ConversationPhase.TOOL_EXECUTING
            else:
                return ConversationPhase.CLARIFICATION
        
        # 从问候阶段转换
        if current_phase == ConversationPhase.GREETING:
            if intent.type == IntentType.IMPUTATION:
                return ConversationPhase.REQUIREMENT_GATHERING
            elif intent.type in [IntentType.QUERY, IntentType.ANALYSIS]:
                return ConversationPhase.TOOL_EXECUTING
        
        # 从需求收集阶段转换
        if current_phase == ConversationPhase.REQUIREMENT_GATHERING:
            # 检查是否已收集足够信息
            if self._has_sufficient_params(session.context, intent):
                return ConversationPhase.UPLOAD_WAITING if intent.type == IntentType.IMPUTATION else ConversationPhase.TOOL_EXECUTING
        
        # 从工具执行阶段转换
        if current_phase == ConversationPhase.TOOL_EXECUTING:
            return ConversationPhase.RESULT_PRESENTING
        
        # 从结果展示阶段转换
        if current_phase == ConversationPhase.RESULT_PRESENTING:
            return ConversationPhase.AWAITING_USER
        
        # 从等待上传阶段转换
        if current_phase == ConversationPhase.UPLOAD_WAITING:
            # 检查上传是否完成
            if session.context.current_workspace_id:
                return ConversationPhase.TOOL_EXECUTING
        
        return None
    
    def _has_sufficient_params(
        self,
        context: ConversationContext,
        intent: Intent
    ) -> bool:
        """检查是否已收集足够参数"""
        if intent.type == IntentType.IMPUTATION:
            # 数据填充至少需要知道参考面板
            return 'ref_panel' in context.collected_params or context.current_workspace_id
        
        if intent.type == IntentType.QUERY:
            # 查询至少需要查询目标
            return bool(intent.entities) or bool(context.collected_params.get('query_target'))
        
        return True
    
    def build_system_prompt(
        self,
        session: ConversationSession,
        intent: Optional[Intent] = None
    ) -> str:
        """
        构建系统提示词
        
        根据当前对话阶段和意图动态构建提示词
        """
        base_prompt = """你是鸡基因组SV数据库智能助手，专门帮助研究人员查询和分析鸡基因组中的结构变异数据。

当前对话阶段: {phase}
对话轮次: {turn_count}
已调用工具次数: {tool_call_count}

"""
        
        phase_prompts = {
            ConversationPhase.INITIAL: """用户刚开始对话，请先了解用户的需求。""",
            
            ConversationPhase.GREETING: """用户正在问候，请友好回应并询问用户需要什么帮助。""",
            
            ConversationPhase.REQUIREMENT_GATHERING: """用户需要数据填充服务，请收集以下信息：
1. 参考面板选择（如未指定，询问用户偏好）
2. 确认是否需要创建新工作区
3. 准备触发文件上传流程

当前已收集参数: {params}""",
            
            ConversationPhase.TOOL_EXECUTING: """正在执行工具调用，请等待结果。""",
            
            ConversationPhase.RESULT_PRESENTING: """工具执行完成，请向用户清晰展示结果，并询问是否需要进一步操作。""",
            
            ConversationPhase.UPLOAD_WAITING: """正在等待用户上传文件，请告知用户查看页面上方的上传对话框完成操作。
工作区ID: {workspace_id}""",
            
            ConversationPhase.CLARIFICATION: """用户意图不明确，请礼貌地询问用户具体需要什么帮助。""",
            
            ConversationPhase.COMPLETION: """对话即将结束，询问用户是否还有其他问题。"""
        }
        
        phase_specific = phase_prompts.get(session.phase, "")
        
        prompt = base_prompt.format(
            phase=session.phase.value,
            turn_count=session.turn_count,
            tool_call_count=session.tool_call_count
        )
        
        if phase_specific:
            prompt += phase_specific.format(
                params=json.dumps(session.context.collected_params, ensure_ascii=False),
                workspace_id=session.context.current_workspace_id or "未创建"
            )
        
        # 添加工具使用指南
        prompt += """

工具使用指南:
1. 数据填充流程: create_imputation_workspace -> request_file_upload -> validate_workspace_files -> run_workspace_imputation
2. 查询SV数据: query_sv (支持按基因、区域、ID查询)
3. 品种分析: query_breed_profile, analyze_breed_association

重要提示:
- 工具调用超过5次后应暂停，等待用户确认
- 数据填充必须先创建工作区并触发上传对话框
- 只输出正文，不要暴露内部工具调用细节
"""
        
        return prompt
    
    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """获取所有会话信息"""
        with self._lock:
            return [session.to_dict() for session in self._sessions.values()]
    
    def cleanup_expired_sessions(self):
        """清理过期会话"""
        with self._lock:
            now = datetime.now(timezone.utc)
            expired = []
            
            for session_id, session in self._sessions.items():
                if (now - session.last_activity).total_seconds() > (self.session_ttl_minutes * 60):
                    expired.append(session_id)
            
            for session_id in expired:
                del self._sessions[session_id]
                print(f"[ConversationManager] 清理过期会话: {session_id}")
            
            return len(expired)


# 全局管理器实例
conversation_manager = ConversationStateManager()


if __name__ == '__main__':
    # 测试代码
    manager = ConversationStateManager()
    
    session_id = "test_session_001"
    session = manager.get_or_create_session(session_id)
    
    # 测试意图识别
    test_messages = [
        "你好",
        "我想填充基因型数据",
        "查询BRCA1基因的SV",
        "分析一下品种关联",
        "help"
    ]
    
    for msg in test_messages:
        intent = manager.detect_intent(msg, session.context)
        print(f"\n消息: {msg}")
        print(f"意图: {intent.type.value}, 置信度: {intent.confidence}")
        
        # 添加消息到会话
        message = Message(role="user", content=msg, intent=intent)
        session.add_message(message)
        
        # 检查阶段转换
        new_phase = manager.should_transition_phase(session, intent)
        if new_phase:
            session.update_phase(new_phase)
    
    print("\n会话状态:", session.to_dict())
    print("\n系统提示词:", manager.build_system_prompt(session))
