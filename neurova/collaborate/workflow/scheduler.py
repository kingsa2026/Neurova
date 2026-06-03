# -*- coding: utf-8 -*-
"""
Agent 调度器

提供 Agent 任务调度和执行管理功能。
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from .models import ScheduledTask, FlowContext

logger = logging.getLogger(__name__)

class AgentScheduler:
    """Agent 调度器

    负责管理和执行计划任务。
    """

    _instance: Optional["AgentScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self._tasks: Dict[str, ScheduledTask] = {}
        self._task_handlers: Dict[str, Callable] = {}  # action -> handler
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._task_lock = threading.Lock()
        self._event_handlers: List[Callable] = []

        logger.info("AgentScheduler initialized")

    def register_handler(self, action: str, handler: Callable) -> None:
        """注册任务处理器

        Args:
            action: 动作名称
            handler: 处理函数，签名: (task: ScheduledTask, context: FlowContext) -> Any
        """
        self._task_handlers[action] = handler
        logger.info(f"Registered handler for action: {action}")

    def add_task(self, task: ScheduledTask) -> bool:
        """添加任务

        Args:
            task: 计划任务

        Returns:
            是否添加成功
        """
        with self._task_lock:
            if task.task_id in self._tasks:
                logger.warning(f"Task already exists: {task.task_id}")
                return False

            self._tasks[task.task_id] = task
            logger.info(f"Task added: {task.task_id} ({task.name})")
            self._emit_event("task_added", task)
            return True

    def remove_task(self, task_id: str) -> bool:
        """移除任务

        Args:
            task_id: 任务ID

        Returns:
            是否移除成功
        """
        with self._task_lock:
            if task_id not in self._tasks:
                return False

            task = self._tasks.pop(task_id)
            logger.info(f"Task removed: {task_id} ({task.name})")
            self._emit_event("task_removed", task)
            return True

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, status: str = None) -> List[ScheduledTask]:
        """列出任务

        Args:
            status: 按状态过滤

        Returns:
            任务列表
        """
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def schedule_task(self, name: str, action: str, agent_id: str = "",
                     scheduled_at: float = None, interval_seconds: int = None,
                     parameters: Dict[str, Any] = None) -> ScheduledTask:
        """创建并添加任务

        Args:
            name: 任务名称
            action: 执行的动作
            agent_id: 执行的 Agent ID
            scheduled_at: 计划执行时间
            interval_seconds: 重复间隔（秒）
            parameters: 动作参数

        Returns:
            创建的任务
        """
        task = ScheduledTask(
            name=name,
            action=action,
            agent_id=agent_id,
            scheduled_at=scheduled_at,
            interval_seconds=interval_seconds,
            parameters=parameters or {},
        )
        self.add_task(task)
        return task

    def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self._running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
            self._scheduler_thread = None
        logger.info("Scheduler stopped")

    def _scheduler_loop(self) -> None:
        """调度器主循环"""
        while self._running:
            try:
                self._check_and_execute_tasks()
                time.sleep(1)  # 每秒检查一次
            except Exception as e:
                logger.exception(f"Error in scheduler loop: {e}")
                time.sleep(5)  # 出错后等待更长时间

    def _check_and_execute_tasks(self) -> None:
        """检查并执行到期任务"""
        with self._task_lock:
            due_tasks = [task for task in self._tasks.values() if task.is_due()]

        for task in due_tasks:
            self._execute_task(task)

    def _execute_task(self, task: ScheduledTask) -> None:
        """执行任务"""
        handler = self._task_handlers.get(task.action)
        if not handler:
            logger.error(f"No handler registered for action: {task.action}")
            task.mark_failed(f"No handler for action: {task.action}")
            return

        task.mark_running()
        self._emit_event("task_started", task)

        try:
            # 创建执行上下文
            context = FlowContext()

            # 执行处理器
            result = handler(task, context)

            task.mark_completed(result)
            self._emit_event("task_completed", task)
            logger.info(f"Task completed: {task.task_id} ({task.name})")

        except Exception as e:
            task.mark_failed(str(e))
            self._emit_event("task_failed", task, {"error": str(e)})
            logger.exception(f"Task failed: {task.task_id} ({task.name}): {e}")

    def add_event_handler(self, handler: Callable) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)

    def _emit_event(self, event_type: str, task: ScheduledTask, data: Dict[str, Any] = None) -> None:
        """触发事件"""
        event_data = {
            "event_type": event_type,
            "task_id": task.task_id,
            "task_name": task.name,
            "timestamp": time.time(),
            **(data or {}),
        }

        for handler in self._event_handlers:
            try:
                handler(event_data)
            except Exception as e:
                logger.exception(f"Error in event handler: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        tasks = list(self._tasks.values())
        return {
            "total_tasks": len(tasks),
            "pending_tasks": len([t for t in tasks if t.status == "pending"]),
            "running_tasks": len([t for t in tasks if t.status == "running"]),
            "completed_tasks": len([t for t in tasks if t.status == "completed"]),
            "failed_tasks": len([t for t in tasks if t.status == "failed"]),
            "cancelled_tasks": len([t for t in tasks if t.status == "cancelled"]),
            "is_running": self._running,
        }

# 全局调度器实例
_global_scheduler: Optional[AgentScheduler] = None

def get_scheduler() -> AgentScheduler:
    """获取全局调度器"""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = AgentScheduler()
    return _global_scheduler