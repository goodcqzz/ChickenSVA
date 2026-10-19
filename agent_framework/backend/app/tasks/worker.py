"""
任务工作器实现

提供异步任务执行：
- 并发控制
- 任务处理器注册
- 优雅关闭
"""

import logging
import asyncio
from typing import Dict, Callable, Coroutine, Any, List, Optional
from datetime import datetime

from app.tasks.queue import TaskQueue, Task, TaskStatus, TaskProgress

logger = logging.getLogger(__name__)


class TaskWorker:
    """
    任务工作器
    
    负责从队列获取任务并执行
    """
    
    def __init__(
        self,
        queue: TaskQueue,
        worker_id: str = None,
        poll_interval: float = 1.0
    ):
        self.queue = queue
        self.worker_id = worker_id or f"worker-{id(self)}"
        self.poll_interval = poll_interval
        
        # 任务处理器注册表
        self._handlers: Dict[str, Callable[[Task], Coroutine]] = {}
        
        # 运行状态
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 统计
        self._processed = 0
        self._failed = 0
        
        logger.info(f"TaskWorker 初始化: {self.worker_id}")
    
    def register_handler(
        self,
        task_type: str,
        handler: Callable[[Task], Coroutine]
    ):
        """注册任务处理器"""
        self._handlers[task_type] = handler
        logger.info(f"注册处理器: {task_type}")
    
    async def start(self):
        """启动工作器"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._work_loop())
        logger.info(f"TaskWorker 已启动: {self.worker_id}")
    
    async def stop(self):
        """停止工作器"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"TaskWorker 已停止: {self.worker_id}")
    
    async def _work_loop(self):
        """工作循环"""
        while self._running:
            try:
                # 获取任务
                task = await self.queue.get_next_task()
                
                if task:
                    # 设置 worker ID
                    task.worker_id = self.worker_id
                    
                    # 执行
                    await self._execute_task(task)
                else:
                    # 没有任务，等待
                    await asyncio.sleep(self.poll_interval)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                await asyncio.sleep(self.poll_interval)
    
    async def _execute_task(self, task: Task):
        """执行任务"""
        handler = self._handlers.get(task.type)
        
        if not handler:
            await self.queue.fail_task(
                task.id,
                f"未找到任务处理器: {task.type}"
            )
            return
        
        try:
            logger.info(f"开始执行任务 [{task.id}]: {task.type}")
            
            # 执行处理器
            result = await handler(task)
            
            # 检查任务是否被取消
            current_task = await self.queue.get_task(task.id)
            if current_task and current_task.status == TaskStatus.CANCELLED:
                logger.info(f"任务已被取消 [{task.id}]")
                return
            
            # 标记完成
            await self.queue.complete_task(task.id, result)
            self._processed += 1
            
            logger.info(f"任务执行成功 [{task.id}]")
            
        except Exception as e:
            logger.error(f"任务执行失败 [{task.id}]: {e}")
            await self.queue.fail_task(task.id, str(e))
            self._failed += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "worker_id": self.worker_id,
            "processed": self._processed,
            "failed": self._failed,
            "handlers": list(self._handlers.keys()),
        }


class WorkerPool:
    """
    工作器池
    
    管理多个工作器实例
    """
    
    def __init__(
        self,
        queue: TaskQueue,
        num_workers: int = 3
    ):
        self.queue = queue
        self.num_workers = num_workers
        self._workers: List[TaskWorker] = []
        
        logger.info(f"WorkerPool 初始化: num_workers={num_workers}")
    
    def register_handler(
        self,
        task_type: str,
        handler: Callable[[Task], Coroutine]
    ):
        """注册任务处理器（所有工作器）"""
        for worker in self._workers:
            worker.register_handler(task_type, handler)
    
    async def start(self):
        """启动所有工作器"""
        for i in range(self.num_workers):
            worker = TaskWorker(
                queue=self.queue,
                worker_id=f"worker-{i+1}"
            )
            self._workers.append(worker)
            await worker.start()
        
        logger.info(f"WorkerPool 已启动: {self.num_workers} 个工作器")
    
    async def stop(self):
        """停止所有工作器"""
        for worker in self._workers:
            await worker.stop()
        
        self._workers.clear()
        logger.info("WorkerPool 已停止")
    
    def get_stats(self) -> List[Dict[str, Any]]:
        """获取所有工作器统计"""
        return [w.get_stats() for w in self._workers]
