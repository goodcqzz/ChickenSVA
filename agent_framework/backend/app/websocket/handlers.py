"""
WebSocket消息处理器

处理不同类型的WebSocket消息
"""

from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class MessageHandler:
    """
    消息处理器
    
    处理WebSocket消息的业务逻辑
    """
    
    def __init__(self):
        self._handlers = {
            "ping": self._handle_ping,
            "chat": self._handle_chat,
            "upload_complete": self._handle_upload_complete,
        }
    
    async def handle(self, msg_type: str, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理消息
        
        Args:
            msg_type: 消息类型
            session_id: 会话ID
            payload: 消息内容
            
        Returns:
            处理结果
        """
        handler = self._handlers.get(msg_type)
        if handler:
            return await handler(session_id, payload)
        else:
            logger.warning(f"未知消息类型: {msg_type}")
            return {"type": "error", "payload": {"code": "UNKNOWN_TYPE", "message": f"未知消息类型: {msg_type}"}}
    
    async def _handle_ping(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理心跳消息"""
        from datetime import datetime
        return {
            "type": "pong",
            "payload": {"timestamp": datetime.utcnow().timestamp()}
        }
    
    async def _handle_chat(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理聊天消息"""
        content = payload.get("content", "")
        logger.info(f"处理聊天消息 [{session_id}]: {content[:50]}...")
        
        return {
            "type": "message",
            "payload": {
                "role": "assistant",
                "content": f"收到: {content}",
                "state": "idle"
            }
        }
    
    async def _handle_upload_complete(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理上传完成消息"""
        workspace_id = payload.get("workspace_id", "")
        files = payload.get("files", [])
        
        logger.info(f"文件上传完成 [{session_id}]: {files}")
        
        return {
            "type": "message",
            "payload": {
                "role": "assistant",
                "content": f"文件上传完成: {', '.join(files)}",
                "state": "idle"
            }
        }
