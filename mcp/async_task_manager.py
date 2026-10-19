#!/usr/bin/env python3
"""Lightweight async task manager for MCP tool execution."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AsyncTaskManager:
    """In-process async task manager with best-effort cancellation and retry."""

    def __init__(self, worker_count: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(worker_count)))
        self._lock = threading.RLock()
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def submit(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        execute_fn: Callable[[str, Dict[str, Any], str, str], Dict[str, Any]],
        data_version: str,
        max_retries: int = 1,
        retry_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        now = _utc_now_iso()

        task = {
            'task_id': task_id,
            'trace_id': trace_id,
            'status': 'queued',
            'tool_name': tool_name,
            'arguments_snapshot': deepcopy(arguments),
            'created_at': now,
            'started_at': None,
            'finished_at': None,
            'cancel_requested': False,
            'attempt': 1,
            'max_retries': max(0, int(max_retries)),
            'retry_of': retry_of,
            'result': None,
            'error': None,
            'data_version': data_version,
            'duration_seconds': None,
        }

        def _runner() -> None:
            started_ts = time.time()
            with self._lock:
                current = self._tasks.get(task_id)
                if not current:
                    return
                if current['cancel_requested']:
                    current['status'] = 'cancelled'
                    current['finished_at'] = _utc_now_iso()
                    current['duration_seconds'] = 0.0
                    return
                current['status'] = 'running'
                current['started_at'] = _utc_now_iso()

            try:
                result = execute_fn(tool_name, deepcopy(arguments), trace_id, task_id)
                with self._lock:
                    current = self._tasks.get(task_id)
                    if not current:
                        return
                    current['result'] = result
                    current['finished_at'] = _utc_now_iso()
                    current['duration_seconds'] = round(time.time() - started_ts, 4)
                    if current['cancel_requested']:
                        current['status'] = 'cancelled'
                    else:
                        current['status'] = 'succeeded'
            except Exception as exc:  # pragma: no cover - defensive
                with self._lock:
                    current = self._tasks.get(task_id)
                    if not current:
                        return
                    current['error'] = str(exc)
                    current['finished_at'] = _utc_now_iso()
                    current['duration_seconds'] = round(time.time() - started_ts, 4)
                    current['status'] = 'failed'

        with self._lock:
            self._tasks[task_id] = task
            self._executor.submit(_runner)

        return self.get_snapshot(task_id)

    def list_tasks(self, limit: int = 100) -> Dict[str, Any]:
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda item: item.get('created_at') or '', reverse=True)
        cap = max(1, min(int(limit), 500))
        return {
            'success': True,
            'total_tasks': len(tasks),
            'tasks': [self._public_task_view(item, include_result=False) for item in tasks[:cap]],
        }

    def cancel(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {'success': False, 'error': f'任务不存在: {task_id}'}
            if task['status'] in {'succeeded', 'failed', 'cancelled'}:
                return {'success': False, 'error': f"任务已结束，当前状态: {task['status']}"}
            task['cancel_requested'] = True
            if task['status'] == 'queued':
                task['status'] = 'cancelled'
                task['finished_at'] = _utc_now_iso()
                task['duration_seconds'] = 0.0
        return {'success': True, 'task_id': task_id, 'status': 'cancel_requested'}

    def retry(
        self,
        task_id: str,
        execute_fn: Callable[[str, Dict[str, Any], str, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {'success': False, 'error': f'任务不存在: {task_id}'}
            if task['status'] not in {'failed', 'cancelled'}:
                return {'success': False, 'error': f"仅失败或取消任务可重试，当前状态: {task['status']}"}
            if int(task.get('attempt', 1)) > int(task.get('max_retries', 0)):
                return {'success': False, 'error': '超过 max_retries，禁止重试'}

            tool_name = str(task['tool_name'])
            arguments = deepcopy(task['arguments_snapshot'])
            data_version = str(task['data_version'])
            max_retries = int(task.get('max_retries', 1))
            next_attempt = int(task.get('attempt', 1)) + 1

        retried = self.submit(
            tool_name=tool_name,
            arguments=arguments,
            execute_fn=execute_fn,
            data_version=data_version,
            max_retries=max_retries,
            retry_of=task_id,
        )

        with self._lock:
            new_task = self._tasks.get(retried['task_id'])
            if new_task:
                new_task['attempt'] = next_attempt

        return {'success': True, 'retry_from': task_id, 'new_task': self.get_snapshot(retried['task_id'])}

    def get_snapshot(self, task_id: str, include_result: bool = True) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {'success': False, 'error': f'任务不存在: {task_id}'}
            return self._public_task_view(task, include_result=include_result)

    def _public_task_view(self, task: Dict[str, Any], include_result: bool) -> Dict[str, Any]:
        view = {
            'success': True,
            'task_id': task['task_id'],
            'trace_id': task['trace_id'],
            'status': task['status'],
            'tool_name': task['tool_name'],
            'created_at': task['created_at'],
            'started_at': task['started_at'],
            'finished_at': task['finished_at'],
            'cancel_requested': task['cancel_requested'],
            'attempt': task['attempt'],
            'max_retries': task['max_retries'],
            'retry_of': task['retry_of'],
            'data_version': task['data_version'],
            'duration_seconds': task['duration_seconds'],
            'error': task['error'],
            'arguments_snapshot': task['arguments_snapshot'],
        }
        if include_result:
            view['result'] = task['result']
        return view
