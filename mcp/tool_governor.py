#!/usr/bin/env python3
"""
工具调用治理器 - 防止工具调用循环
用于解决Dify Agent多轮对话后的工具调用循环问题
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
import threading
import time


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    tool_name: str
    arguments_hash: str
    timestamp: datetime
    result_summary: str = ""


@dataclass
class SessionState:
    """会话状态"""
    session_id: str
    call_history: list = field(default_factory=list)
    turn_count: int = 0
    last_tool_name: Optional[str] = None
    consecutive_same_tool: int = 0
    expecting_input: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def update_activity(self):
        """更新最后活动时间"""
        self.last_activity = datetime.now(timezone.utc)


class ToolCallGovernor:
    """
    工具调用治理器
    
    功能：
    1. 限制每轮对话的工具调用次数
    2. 防止同一工具的重复调用
    3. 检测和阻止循环调用模式
    4. 提供调用建议
    """
    
    def __init__(
        self,
        max_calls_per_turn: int = 15,  # 放宽：从5改为15
        max_consecutive_same_tool: int = 3,  # 放宽：从2改为3
        call_timeout_seconds: int = 60,
        session_ttl_minutes: int = 30,
        enable_circular_detection: bool = False  # 新增：关闭循环检测（填充流程需要）
    ):
        self.max_calls_per_turn = max_calls_per_turn
        self.max_consecutive_same_tool = max_consecutive_same_tool
        self.call_timeout_seconds = call_timeout_seconds
        self.session_ttl_minutes = session_ttl_minutes
        self.enable_circular_detection = enable_circular_detection
        
        # 会话存储
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.RLock()
        
        # 启动清理线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_expired_sessions, daemon=True)
        self._cleanup_thread.start()
    
    def _get_session(self, session_id: str) -> SessionState:
        """获取或创建会话状态"""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState(session_id=session_id)
            return self._sessions[session_id]
    
    def check_and_record(
        self,
        session_id: str,
        tool_name: str,
        arguments: Optional[Dict] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        检查并记录工具调用
        
        Args:
            session_id: 会话ID
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            (是否允许, 原因, 元数据)
        """
        session = self._get_session(session_id)
        
        with self._lock:
            session.update_activity()
            
            # 1. 检查调用频率（1分钟内）
            now = datetime.now(timezone.utc)
            recent_calls = [
                call for call in session.call_history
                if (now - call.timestamp).total_seconds() < self.call_timeout_seconds
            ]
            
            if len(recent_calls) >= self.max_calls_per_turn:
                return False, (
                    f"工具调用频率过高（最近{self.call_timeout_seconds}秒内已调用"
                    f"{len(recent_calls)}次）。请等待当前操作完成或稍后再试。"
                ), {
                    'reason': 'rate_limited',
                    'recent_calls': len(recent_calls),
                    'limit': self.max_calls_per_turn
                }
            
            # 2. 检查连续相同工具调用
            if tool_name == session.last_tool_name:
                session.consecutive_same_tool += 1
                if session.consecutive_same_tool >= self.max_consecutive_same_tool:
                    return False, (
                        f"工具 '{tool_name}' 已被连续调用 {session.consecutive_same_tool} 次，"
                        f"可能存在循环调用。请先处理已有结果。"
                    ), {
                        'reason': 'consecutive_limit',
                        'tool': tool_name,
                        'count': session.consecutive_same_tool
                    }
            else:
                session.consecutive_same_tool = 1
            
            # 3. 检查循环调用模式（A->B->A->B）- 可选，默认关闭
            if self.enable_circular_detection and len(session.call_history) >= 3:
                last_three = [c.tool_name for c in session.call_history[-3:]]
                if len(set(last_three)) == 2 and last_three[0] == last_three[2]:
                    return False, (
                        f"检测到工具调用循环模式: {' -> '.join(last_three)}。"
                        f"请明确您的需求或等待当前操作完成。"
                    ), {
                        'reason': 'circular_pattern',
                        'pattern': last_three
                    }
            
            # 4. 检查参数重复（防止相同参数的重复调用）
            if arguments:
                import hashlib
                args_str = str(sorted(arguments.items()))
                args_hash = hashlib.md5(args_str.encode()).hexdigest()[:16]
                
                same_args_calls = [
                    call for call in recent_calls
                    if call.tool_name == tool_name and call.arguments_hash == args_hash
                ]
                
                if same_args_calls:
                    return False, (
                        f"工具 '{tool_name}' 已被使用相同参数调用过。"
                        f"请修改参数或等待当前操作完成。"
                    ), {
                        'reason': 'duplicate_arguments',
                        'tool': tool_name
                    }
            else:
                args_hash = ""
            
            # 记录调用
            record = ToolCallRecord(
                tool_name=tool_name,
                arguments_hash=args_hash,
                timestamp=now
            )
            session.call_history.append(record)
            session.last_tool_name = tool_name
            session.turn_count += 1
            
            return True, "允许调用", {
                'call_number': len(recent_calls) + 1,
                'total_calls': len(session.call_history),
                'session_turn': session.turn_count
            }
    
    def record_result(
        self,
        session_id: str,
        tool_name: str,
        result: Dict[str, Any]
    ):
        """记录工具调用结果"""
        session = self._get_session(session_id)
        
        with self._lock:
            # 更新最后一条记录的结果
            if session.call_history and session.call_history[-1].tool_name == tool_name:
                has_data = bool(result.get('data') or result.get('results'))
                success = result.get('success', False)
                session.call_history[-1].result_summary = (
                    f"success={success}, has_data={has_data}"
                )
                
                # 如果有数据，标记为期待用户输入
                if has_data:
                    session.expecting_input = True
    
    def reset_turn(self, session_id: str):
        """
        重置轮次计数（当收到新用户消息时调用）
        
        Args:
            session_id: 会话ID
        """
        session = self._get_session(session_id)
        
        with self._lock:
            session.turn_count = 0
            session.consecutive_same_tool = 0
            session.expecting_input = False
            session.last_tool_name = None
    
    def should_stop_calling(self, session_id: str) -> Tuple[bool, str]:
        """
        判断是否应停止调用工具
        
        Returns:
            (是否停止, 原因)
        """
        session = self._get_session(session_id)
        
        with self._lock:
            # 如果已有数据且调用次数超过阈值
            if session.expecting_input and session.turn_count >= 3:
                return True, "已获取足够数据，应等待用户输入"
            
            # 如果调用次数过多
            if session.turn_count >= self.max_calls_per_turn:
                return True, f"已达到最大调用次数限制({self.max_calls_per_turn})"
            
            return False, ""
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """获取会话统计信息"""
        session = self._get_session(session_id)
        
        with self._lock:
            tool_counts = {}
            for call in session.call_history:
                tool_counts[call.tool_name] = tool_counts.get(call.tool_name, 0) + 1
            
            return {
                'session_id': session_id,
                'total_calls': len(session.call_history),
                'turn_count': session.turn_count,
                'tool_distribution': tool_counts,
                'expecting_input': session.expecting_input,
                'created_at': session.created_at.isoformat(),
                'last_activity': session.last_activity.isoformat()
            }
    
    def _cleanup_expired_sessions(self):
        """清理过期会话"""
        while True:
            time.sleep(300)  # 每5分钟清理一次
            
            with self._lock:
                now = datetime.now(timezone.utc)
                expired = []
                
                for session_id, session in self._sessions.items():
                    if (now - session.last_activity).total_seconds() > (self.session_ttl_minutes * 60):
                        expired.append(session_id)
                
                for session_id in expired:
                    del self._sessions[session_id]
                    print(f"[ToolGovernor] 清理过期会话: {session_id}")
    
    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计信息"""
        with self._lock:
            return {
                'active_sessions': len(self._sessions),
                'max_calls_per_turn': self.max_calls_per_turn,
                'sessions': [
                    self.get_session_stats(sid) for sid in self._sessions.keys()
                ]
            }


# 全局治理器实例
tool_governor = ToolCallGovernor()


if __name__ == '__main__':
    # 测试代码
    governor = ToolCallGovernor(max_calls_per_turn=3)
    
    session_id = "test_session_001"
    
    # 测试正常调用
    for i in range(3):
        allowed, reason, meta = governor.check_and_record(
            session_id, "query_sv", {"gene": "BRCA1"}
        )
        print(f"Call {i+1}: allowed={allowed}, reason={reason}, meta={meta}")
    
    # 测试频率限制
    allowed, reason, meta = governor.check_and_record(
        session_id, "query_sv", {"gene": "TP53"}
    )
    print(f"Call 4 (should fail): allowed={allowed}, reason={reason}")
    
    # 测试重复调用检测
    time.sleep(1)
    governor.reset_turn(session_id)
    
    for i in range(3):
        allowed, reason, meta = governor.check_and_record(
            session_id, "same_tool", {}
        )
        print(f"Same tool call {i+1}: allowed={allowed}, reason={reason}")
    
    print("\nStats:", governor.get_session_stats(session_id))
