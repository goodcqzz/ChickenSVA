"""
异步任务队列模块

提供高性能异步任务处理系统：
- 任务优先级管理
- 失败重试机制
- 进度跟踪
- 结果回调

适用于耗时的基因型填充任务
"""

from app.tasks.queue import TaskQueue, Task, TaskStatus, TaskPriority, init_task_queue, get_task_queue
from app.tasks.worker import TaskWorker, WorkerPool
from app.tasks.imputation_task import ImputationTaskHandler, ImputationTaskConfig, handle_imputation_task

__all__ = [
    "TaskQueue",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "TaskWorker",
    "WorkerPool",
    "ImputationTaskHandler",
    "ImputationTaskConfig",
    "handle_imputation_task",
    "init_task_queue",
    "get_task_queue",
]
