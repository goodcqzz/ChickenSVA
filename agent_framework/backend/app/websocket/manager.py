"""
WebSocket连接管理器

管理所有WebSocket连接，提供：
- 连接注册和注销（带最大连接数限制）
- 消息广播和定向发送（并行优化）
- 心跳检测和超时清理
- 会话管理和统计
- 连接池压力控制
"""

import json
import logging
import asyncio
import time
from typing import Dict, Optional, Any, List, Set
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)


class WebSocketConnection:
    """
    WebSocket连接封装类
    
    封装单个WebSocket连接，管理连接状态和心跳
    """
    
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.connected_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.is_active = True
        self.message_count = 0
        self.error_count = 0
        self._lock = asyncio.Lock()
    
    async def send(self, message: Dict[str, Any]) -> bool:
        """
        发送消息到客户端
        
        Args:
            message: 消息字典
            
        Returns:
            发送是否成功
        """
        if not self.is_active:
            return False
        
        async with self._lock:
            try:
                await self.websocket.send_json(message)
                self.message_count += 1
                return True
            except Exception as e:
                self.error_count += 1
                if self.error_count <= 3:  # 只记录前3次错误
                    logger.error(f"发送消息失败 [{self.session_id}]: {e}")
                if self.error_count >= 5:  # 5次错误后标记为不活跃
                    self.is_active = False
                    logger.warning(f"连接标记为不活跃 [{self.session_id}]: 错误次数过多")
                return False
    
    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.utcnow()
        self.error_count = 0  # 重置错误计数
    
    def is_timed_out(self, timeout: Optional[int] = None) -> bool:
        """
        检查连接是否超时
        
        Args:
            timeout: 超时时间（秒），默认使用配置值
            
        Returns:
            是否超过超时时间
        """
        if not self.is_active:
            return True
        
        elapsed = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return elapsed > (timeout or settings.ws_timeout)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取连接统计信息"""
        return {
            "session_id": self.session_id,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "is_active": self.is_active,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "idle_seconds": (datetime.utcnow() - self.last_heartbeat).total_seconds(),
        }


class WebSocketManager:
    """
    WebSocket连接管理器
    
    管理所有活动的WebSocket连接，提供连接管理和消息分发功能
    优化特性：
    - 最大连接数限制
    - 并行消息广播
    - 连接压力控制
    - 自动清理超时连接
    """
    
    def __init__(
        self,
        max_connections: int = 1000,
        broadcast_batch_size: int = 100,
        cleanup_interval: int = 60
    ):
        # 配置参数
        self._max_connections = max_connections
        self._broadcast_batch_size = broadcast_batch_size
        self._cleanup_interval = cleanup_interval
        
        # 存储所有连接: {session_id: WebSocketConnection}
        self._connections: Dict[str, WebSocketConnection] = {}
        # 存储会话元数据: {session_id: metadata}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        
        # 统计信息
        self._stats = {
            "total_connections": 0,
            "total_messages_sent": 0,
            "total_messages_failed": 0,
            "peak_connections": 0,
            "rejected_connections": 0,
        }
        
        # 后台任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        logger.info(
            f"WebSocket管理器初始化完成: max_connections={max_connections}, "
            f"broadcast_batch_size={broadcast_batch_size}"
        )
    
    async def start(self):
        """启动后台清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("WebSocket管理器后台清理任务已启动")
    
    async def stop(self):
        """停止管理器并清理所有连接"""
        self._shutdown = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 关闭所有连接
        await self.broadcast_disconnect()
        logger.info("WebSocket管理器已停止")
    
    def register(self, session_id: str, websocket: WebSocket) -> bool:
        """
        注册新的WebSocket连接
        
        Args:
            session_id: 会话唯一标识
            websocket: WebSocket对象
            
        Returns:
            是否注册成功（可能因连接数限制失败）
        """
        # 检查连接数限制
        if len(self._connections) >= self._max_connections:
            logger.warning(
                f"连接数达到上限 [{session_id}]: "
                f"{len(self._connections)}/{self._max_connections}"
            )
            self._stats["rejected_connections"] += 1
            return False
        
        # 如果已存在相同session_id的连接，标记旧连接为不活跃
        if session_id in self._connections:
            old_connection = self._connections[session_id]
            old_connection.is_active = False
            logger.warning(f"会话 [{session_id}] 已存在，标记旧连接为不活跃")
        
        # 创建新连接
        connection = WebSocketConnection(session_id, websocket)
        self._connections[session_id] = connection
        self._sessions[session_id] = {
            "created_at": datetime.utcnow().isoformat(),
            "message_count": 0,
            "remote_address": getattr(websocket.client, 'host', 'unknown') if hasattr(websocket, 'client') else 'unknown'
        }
        
        # 更新统计
        self._stats["total_connections"] += 1
        current_count = len(self._connections)
        if current_count > self._stats["peak_connections"]:
            self._stats["peak_connections"] = current_count
        
        logger.info(
            f"新连接注册 [{session_id}], "
            f"当前连接数: {current_count}/{self._max_connections}"
        )
        return True
    
    def unregister(self, session_id: str) -> None:
        """
        注销WebSocket连接
        
        Args:
            session_id: 会话唯一标识
        """
        if session_id in self._connections:
            connection = self._connections[session_id]
            connection.is_active = False
            del self._connections[session_id]
            
            # 保留会话元数据一段时间用于统计
            if session_id in self._sessions:
                self._sessions[session_id]["disconnected_at"] = datetime.utcnow().isoformat()
            
            logger.info(
                f"连接注销 [{session_id}], "
                f"当前连接数: {len(self._connections)}/{self._max_connections}"
            )
        else:
            logger.debug(f"连接不存在，跳过注销 [{session_id}]")
    
    async def send_to_session(
        self,
        session_id: str,
        message: Dict[str, Any],
        add_metadata: bool = True
    ) -> bool:
        """
        发送消息到指定会话
        
        Args:
            session_id: 目标会话ID
            message: 消息内容
            add_metadata: 是否添加元数据
            
        Returns:
            发送是否成功
        """
        if session_id not in self._connections:
            logger.debug(f"会话不存在 [{session_id}]")
            return False
        
        # 添加消息元数据
        if add_metadata:
            message_with_meta = {
                "id": self._generate_message_id(),
                "timestamp": datetime.utcnow().isoformat(),
                **message
            }
        else:
            message_with_meta = message
        
        connection = self._connections[session_id]
        success = await connection.send(message_with_meta)
        
        if success:
            self._stats["total_messages_sent"] += 1
            if session_id in self._sessions:
                self._sessions[session_id]["message_count"] += 1
        else:
            self._stats["total_messages_failed"] += 1
        
        return success
    
    async def broadcast(
        self,
        message: Dict[str, Any],
        exclude_session: Optional[str] = None,
        add_metadata: bool = True
    ) -> Dict[str, int]:
        """
        广播消息到所有连接（并行优化）
        
        Args:
            message: 消息内容
            exclude_session: 排除的会话ID
            add_metadata: 是否添加元数据
            
        Returns:
            统计信息: {"success": 成功数, "failed": 失败数, "total": 总数}
        """
        # 添加消息元数据
        if add_metadata:
            message_with_meta = {
                "id": self._generate_message_id(),
                "timestamp": datetime.utcnow().isoformat(),
                **message
            }
        else:
            message_with_meta = message
        
        # 获取活跃连接
        connections = [
            conn for sid, conn in self._connections.items()
            if conn.is_active and sid != exclude_session
        ]
        
        if not connections:
            return {"success": 0, "failed": 0, "total": 0}
        
        # 分批并行发送
        success_count = 0
        failed_count = 0
        
        for i in range(0, len(connections), self._broadcast_batch_size):
            batch = connections[i:i + self._broadcast_batch_size]
            tasks = [conn.send(message_with_meta) for conn in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    failed_count += 1
                    logger.error(f"广播消息异常: {result}")
                elif result is True:
                    success_count += 1
                else:
                    failed_count += 1
        
        self._stats["total_messages_sent"] += success_count
        self._stats["total_messages_failed"] += failed_count
        
        logger.debug(
            f"广播消息完成: success={success_count}, "
            f"failed={failed_count}, total={len(connections)}"
        )
        
        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(connections)
        }
    
    async def broadcast_disconnect(self) -> None:
        """广播服务关闭消息并断开所有连接"""
        await self.broadcast({
            "type": "server_shutdown",
            "payload": {"message": "服务器即将关闭"}
        })
        
        # 标记所有连接为不活跃
        for session_id in list(self._connections.keys()):
            self._connections[session_id].is_active = False
        
        # 等待一小段时间让客户端处理关闭消息
        await asyncio.sleep(0.5)
        
        # 清空连接
        self._connections.clear()
    
    async def handle_message(self, session_id: str, data: str) -> None:
        """
        处理收到的WebSocket消息
        
        Args:
            session_id: 会话ID
            data: 消息内容（JSON字符串）
        """
        try:
            message = json.loads(data)
            msg_type = message.get("type", "unknown")
            
            # 更新心跳
            if session_id in self._connections:
                self._connections[session_id].update_heartbeat()
            
            # 处理不同类型的消息
            if msg_type == "ping":
                await self._handle_ping(session_id, message)
            elif msg_type == "chat":
                await self._handle_chat(session_id, message)
            elif msg_type == "upload_complete":
                await self._handle_upload_complete(session_id, message)
            else:
                logger.warning(f"未知消息类型 [{session_id}]: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"消息解析失败 [{session_id}]: {e}")
            await self.send_to_session(session_id, {
                "type": "error",
                "payload": {
                    "code": "INVALID_MESSAGE",
                    "message": "消息格式错误，必须是有效的JSON"
                }
            })
        except Exception as e:
            logger.error(f"处理消息时出错 [{session_id}]: {e}")
            await self.send_to_session(session_id, {
                "type": "error",
                "payload": {
                    "code": "INTERNAL_ERROR",
                    "message": "处理消息时发生内部错误"
                }
            })
    
    async def _handle_ping(self, session_id: str, message: Dict) -> None:
        """
        处理心跳消息
        
        Args:
            session_id: 会话ID
            message: 消息内容
        """
        await self.send_to_session(session_id, {
            "type": "pong",
            "payload": {
                "timestamp": datetime.utcnow().timestamp(),
                "connections": len(self._connections)
            }
        })
    
    async def _handle_chat(self, session_id: str, message: Dict) -> None:
        """
        处理聊天消息
        
        Args:
            session_id: 会话ID
            message: 消息内容
        """
        content = message.get("payload", {}).get("content", "")
        logger.info(f"收到聊天消息 [{session_id}]: {content[:50]}...")
        
        # 发送确认消息
        await self.send_to_session(session_id, {
            "type": "message",
            "payload": {
                "role": "assistant",
                "content": f"收到消息: {content}",
                "state": "idle"
            }
        })
    
    async def _handle_upload_complete(self, session_id: str, message: Dict) -> None:
        """
        处理上传完成消息
        
        Args:
            session_id: 会话ID
            message: 消息内容
        """
        workspace_id = message.get("payload", {}).get("workspace_id", "")
        files = message.get("payload", {}).get("files", [])
        
        logger.info(f"上传完成 [{session_id}]: workspace={workspace_id}, files={len(files)}")
        
        await self.send_to_session(session_id, {
            "type": "upload_ack",
            "payload": {
                "workspace_id": workspace_id,
                "status": "received",
                "file_count": len(files)
            }
        })
    
    def _generate_message_id(self) -> str:
        """生成唯一消息ID"""
        return f"msg_{datetime.utcnow().timestamp()}_{id(self)}"
    
    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self._connections)
    
    def is_connected(self, session_id: str) -> bool:
        """检查指定会话是否已连接"""
        return session_id in self._connections and self._connections[session_id].is_active

    def touch(self, session_id: str) -> bool:
        """更新指定会话的心跳时间"""
        if session_id in self._connections:
            self._connections[session_id].update_heartbeat()
            return True
        return False

    
    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        active_connections = sum(
            1 for conn in self._connections.values() if conn.is_active
        )
        
        return {
            **self._stats,
            "current_connections": len(self._connections),
            "active_connections": active_connections,
            "max_connections": self._max_connections,
            "connection_utilization": len(self._connections) / self._max_connections if self._max_connections > 0 else 0,
        }
    
    def get_connection_details(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取连接详情列表"""
        connections = list(self._connections.values())[:limit]
        return [conn.get_stats() for conn in connections]
    
    async def _cleanup_loop(self):
        """后台清理循环"""
        while not self._shutdown:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_timed_out()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理循环异常: {e}")
    
    async def _cleanup_timed_out(self):
        """清理超时连接"""
        timed_out = []
        
        for session_id, connection in self._connections.items():
            if connection.is_timed_out():
                timed_out.append(session_id)
        
        for session_id in timed_out:
            logger.info(f"清理超时连接 [{session_id}]")
            self.unregister(session_id)
        
        if timed_out:
            logger.info(f"清理完成: 移除 {len(timed_out)} 个超时连接")
