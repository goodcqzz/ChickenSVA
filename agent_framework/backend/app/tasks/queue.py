"""
任务队列实现

提供异步任务队列管理：
- 优先级队列
- 任务状态管理
- 持久化存储
- 进度跟踪
"""

import json
import logging
import asyncio
import uuid
from typing import Dict, Any, Optional, List, Callable, Coroutine
from sqlalchemy import func
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from collections import deque
import aiosqlite
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"           # 等待执行
    RUNNING = "running"           # 执行中
    PAUSED = "paused"             # 暂停
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 取消
    RETRYING = "retrying"         # 重试中


class TaskPriority(Enum):
    """任务优先级"""
    CRITICAL = 0     # 紧急
    HIGH = 1         # 高
    NORMAL = 2       # 正常
    LOW = 3          # 低
    BACKGROUND = 4   # 后台


@dataclass
class TaskProgress:
    """任务进度"""
    current: int = 0
    total: int = 100
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def percentage(self) -> float:
        """完成百分比"""
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current": self.current,
            "total": self.total,
            "percentage": self.percentage,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class Task:
    """任务定义"""
    id: str
    type: str
    payload: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 执行信息
    worker_id: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    # 结果和进度
    result: Optional[Any] = None
    error: Optional[str] = None
    progress: TaskProgress = field(default_factory=TaskProgress)
    
    # 回调
    on_progress: Optional[Callable[[str, TaskProgress], Coroutine]] = None
    on_complete: Optional[Callable[[str, Any], Coroutine]] = None
    on_error: Optional[Callable[[str, str], Coroutine]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "worker_id": self.worker_id,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "result": self.result,
            "error": self.error,
            "progress": self.progress.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从字典创建"""
        return cls(
            id=data["id"],
            type=data["type"],
            payload=data["payload"],
            priority=TaskPriority(data.get("priority", 2)),
            status=TaskStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            worker_id=data.get("worker_id"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            result=data.get("result"),
            error=data.get("error"),
            progress=TaskProgress(**data.get("progress", {})),
        )


class TaskQueue:
    """
    异步任务队列
    
    特性：
    - 优先级队列
    - 持久化存储
    - 任务状态管理
    - 进度回调
    """
    
    def __init__(
        self,
        db_path: str = "./data/tasks.db",
        max_concurrent: int = 3
    ):
        self.db_path = db_path
        self.max_concurrent = max_concurrent
        
        # 内存队列（按优先级）
        self._queues: Dict[TaskPriority, deque] = {
            priority: deque() for priority in TaskPriority
        }
        
        # 活跃任务
        self._running_tasks: Dict[str, Task] = {}
        
        # 锁
        self._lock = asyncio.Lock()
        
        # 数据库连接
        self._db: Optional[sqlite3.Connection] = None
        
        # 统计
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        
        logger.info(f"TaskQueue 初始化: max_concurrent={max_concurrent}")
    
    async def start(self):
        """启动队列"""
        # 初始化数据库
        await self._init_db()
        
        # 恢复未完成的任务
        await self._recover_tasks()
        
        logger.info("TaskQueue 已启动")
    
    async def stop(self):
        """停止队列"""
        # 取消所有运行中的任务
        async with self._lock:
            for task in self._running_tasks.values():
                task.status = TaskStatus.CANCELLED
            
            self._running_tasks.clear()
        
        # 关闭数据库
        if self._db:
            await self._db.close()
            self._db = None
        
        logger.info("TaskQueue 已停止")
    
    async def submit(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
        on_progress: Optional[Callable[[str, TaskProgress], Coroutine]] = None,
        on_complete: Optional[Callable[[str, Any], Coroutine]] = None,
        on_error: Optional[Callable[[str, str], Coroutine]] = None,
    ) -> str:
        """
        提交任务
        
        Args:
            task_type: 任务类型
            payload: 任务数据
            priority: 优先级
            max_retries: 最大重试次数
            on_progress: 进度回调
            on_complete: 完成回调
            on_error: 错误回调
            
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        
        task = Task(
            id=task_id,
            type=task_type,
            payload=payload,
            priority=priority,
            max_retries=max_retries,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )
        
        async with self._lock:
            # 加入内存队列
            self._queues[priority].append(task)
            
            # 持久化
            await self._persist_task(task)
        
        self._stats["submitted"] += 1
        logger.info(f"任务已提交 [{task_id}]: type={task_type}, priority={priority.name}")
        
        return task_id
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        # 先检查内存
        async with self._lock:
            if task_id in self._running_tasks:
                return self._running_tasks[task_id]
            
            for queue in self._queues.values():
                for task in queue:
                    if task.id == task_id:
                        return task
        
        # 从数据库查询
        return await self._load_task(task_id)
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        async with self._lock:
            # 检查是否在队列中
            for priority, queue in self._queues.items():
                for i, task in enumerate(queue):
                    if task.id == task_id:
                        if task.status == TaskStatus.PENDING:
                            queue.remove(task)
                            task.status = TaskStatus.CANCELLED
                            await self._persist_task(task)
                            self._stats["cancelled"] += 1
                            logger.info(f"任务已取消 [{task_id}]")
                            return True
                        return False
            
            # 检查是否运行中
            if task_id in self._running_tasks:
                # 运行中的任务需要特殊处理
                task = self._running_tasks[task_id]
                task.status = TaskStatus.CANCELLED
                await self._persist_task(task)
                logger.info(f"运行中任务标记为取消 [{task_id}]")
                return True
        
        return False
    
    async def get_next_task(self) -> Optional[Task]:
        """获取下一个待执行的任务"""
        async with self._lock:
            # 按优先级获取
            for priority in sorted(TaskPriority, key=lambda p: p.value):
                queue = self._queues[priority]
                while queue:
                    task = queue.popleft()
                    if task.status == TaskStatus.PENDING:
                        task.status = TaskStatus.RUNNING
                        task.started_at = datetime.utcnow()
                        self._running_tasks[task.id] = task
                        await self._persist_task(task)
                        return task
        
        return None
    
    async def complete_task(self, task_id: str, result: Any):
        """完成任务"""
        async with self._lock:
            if task_id in self._running_tasks:
                task = self._running_tasks.pop(task_id)
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                task.result = result
                await self._persist_task(task)
                
                self._stats["completed"] += 1
                
                # 回调
                if task.on_complete:
                    try:
                        await task.on_complete(task_id, result)
                    except Exception as e:
                        logger.error(f"完成回调失败 [{task_id}]: {e}")
                
                logger.info(f"任务完成 [{task_id}]")
    
    async def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        async with self._lock:
            if task_id in self._running_tasks:
                task = self._running_tasks.pop(task_id)
                task.error = error
                
                # 检查是否需要重试
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = TaskStatus.RETRYING
                    task.progress.message = f"第 {task.retry_count} 次重试..."
                    
                    # 重新加入队列
                    self._queues[task.priority].append(task)
                    logger.warning(f"任务失败，准备重试 [{task_id}]: {error}")
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.utcnow()
                    self._stats["failed"] += 1
                    
                    # 回调
                    if task.on_error:
                        try:
                            await task.on_error(task_id, error)
                        except Exception as e:
                            logger.error(f"错误回调失败 [{task_id}]: {e}")
                    
                    logger.error(f"任务失败 [{task_id}]: {error}")
                
                await self._persist_task(task)
    
    async def update_progress(self, task_id: str, progress: TaskProgress):
        """更新任务进度"""
        async with self._lock:
            if task_id in self._running_tasks:
                task = self._running_tasks[task_id]
                task.progress = progress
                
                # 回调
                if task.on_progress:
                    try:
                        await task.on_progress(task_id, progress)
                    except Exception as e:
                        logger.error(f"进度回调失败 [{task_id}]: {e}")
                
                # 定期持久化（每10%）
                if int(progress.percentage) % 10 == 0:
                    await self._persist_task(task)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        pending_count = sum(len(q) for q in self._queues.values())
        
        return {
            **self._stats,
            "pending": pending_count,
            "running": len(self._running_tasks),
            "queue_sizes": {
                priority.name: len(queue)
                for priority, queue in self._queues.items()
            },
        }
    
    async def _init_db(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._db = await aiosqlite.connect(self.db_path)
        
        # 创建表
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                worker_id TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                result TEXT,
                error TEXT,
                progress TEXT
            )
        """)
        
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)
        """)
        
        await self._db.commit()
        logger.info(f"任务数据库已初始化: {self.db_path}")
    
    async def _persist_task(self, task: Task):
        """持久化任务"""
        if not self._db:
            return
        
        try:
            await self._db.execute("""
                INSERT OR REPLACE INTO tasks 
                (id, type, payload, priority, status, created_at, started_at, 
                 completed_at, worker_id, retry_count, max_retries, result, error, progress)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id,
                task.type,
                json.dumps(task.payload),
                task.priority.value,
                task.status.value,
                task.created_at.isoformat(),
                task.started_at.isoformat() if task.started_at else None,
                task.completed_at.isoformat() if task.completed_at else None,
                task.worker_id,
                task.retry_count,
                task.max_retries,
                json.dumps(task.result) if task.result else None,
                task.error,
                json.dumps(task.progress.to_dict()),
            ))
            await self._db.commit()
        except Exception as e:
            logger.error(f"任务持久化失败 [{task.id}]: {e}")
    
    async def _load_task(self, task_id: str) -> Optional[Task]:
        """从数据库加载任务"""
        if not self._db:
            return None
        
        try:
            cursor = await self._db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                return Task.from_dict({
                    "id": row[0],
                    "type": row[1],
                    "payload": json.loads(row[2]),
                    "priority": row[3],
                    "status": row[4],
                    "created_at": row[5],
                    "started_at": row[6],
                    "completed_at": row[7],
                    "worker_id": row[8],
                    "retry_count": row[9],
                    "max_retries": row[10],
                    "result": json.loads(row[11]) if row[11] else None,
                    "error": row[12],
                    "progress": json.loads(row[13]) if row[13] else {},
                })
        except Exception as e:
            logger.error(f"任务加载失败 [{task_id}]: {e}")
        
        return None
    
    async def _recover_tasks(self):
        """恢复未完成的任务"""
        if not self._db:
            return
        
        try:
            # 查找运行中的任务（上次崩溃时正在运行的）
            cursor = await self._db.execute(
                "SELECT * FROM tasks WHERE status IN (?, ?)",
                (TaskStatus.RUNNING.value, TaskStatus.RETRYING.value)
            )
            
            rows = await cursor.fetchall()
            recovered = 0
            
            for row in rows:
                task = Task.from_dict({
                    "id": row[0],
                    "type": row[1],
                    "payload": json.loads(row[2]),
                    "priority": row[3],
                    "status": TaskStatus.PENDING.value,  # 重置为待执行
                    "created_at": row[5],
                    "started_at": None,
                    "completed_at": row[7],
                    "worker_id": None,
                    "retry_count": row[9],
                    "max_retries": row[10],
                    "result": None,
                    "error": row[12],
                    "progress": json.loads(row[13]) if row[13] else {},
                })
                
                # 加入队列
                self._queues[task.priority].append(task)
                recovered += 1
            
            if recovered > 0:
                logger.info(f"已恢复 {recovered} 个未完成任务")
                
        except Exception as e:
            logger.error(f"任务恢复失败: {e}")


# 全局队列实例
_task_queue: Optional[TaskQueue] = None


def init_task_queue(**kwargs) -> TaskQueue:
    """初始化全局任务队列"""
    global _task_queue
    _task_queue = TaskQueue(**kwargs)
    return _task_queue


def get_task_queue() -> Optional[TaskQueue]:
    """获取全局任务队列"""
    return _task_queue
