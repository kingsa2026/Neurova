from __future__ import annotations

"""
TaskTracker - 任务追踪器

实现任务的生命周期管理，支持进度追踪、状态更新和任务控制。
"""

import asyncio
from dataclasses import dataclass, field
import datetime
import enum
import logging
import typing
import uuid

from enum import Enum
import time
import threading

logger = logging.getLogger(__name__)


# ────── 数据模型 ──────

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    PAUSED = "paused"            # 暂停
    COMPLETED = "completed"      # 完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 取消
    TIMEOUT = "timeout"          # 超时


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str = ""
    name: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0  # 0-100
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    started_at: typing.Optional[datetime.datetime] = None
    completed_at: typing.Optional[datetime.datetime] = None
    error_message: str = ""
    result: typing.Optional[typing.Dict[str, typing.Any]] = None
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    parent_task_id: typing.Optional[str] = None
    subtasks: typing.List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())[:8]

    @property
    def duration(self) -> typing.Optional[float]:
        """计算任务持续时间（秒）"""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.datetime.now(datetime.timezone.utc)
        return (end_time - self.started_at).total_seconds()

    @property
    def is_terminal(self) -> bool:
        """是否为终止状态"""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration": self.duration,
            "error_message": self.error_message,
            "result": self.result,
            "metadata": self.metadata,
            "parent_task_id": self.parent_task_id,
            "subtasks": self.subtasks,
        }


# ────── 主类 ──────

class TaskTracker:
    """
    任务追踪器

    管理任务生命周期，支持：
    - 任务创建和状态管理
    - 进度追踪和更新
    - 任务订阅和通知
    - 子任务管理
    - 任务清理
    """

    def __init__(self, max_tasks: int = 10000, cleanup_interval: int = 3600):
        """
        初始化任务追踪器

        参数:
            max_tasks: 最大任务数量
            cleanup_interval: 清理间隔（秒）
        """
        self._max_tasks = max_tasks
        self._cleanup_interval = cleanup_interval
        self._lock = threading.RLock()

        # 任务存储
        self._tasks: typing.Dict[str, TaskInfo] = {}

        # 订阅者
        self._subscribers: typing.Dict[str, typing.List[typing.Callable]] = {
            "status_change": [],
            "progress_update": [],
            "task_completed": [],
            "task_failed": [],
        }

        # 清理线程
        self._cleanup_thread: typing.Optional[threading.Thread] = None
        self._running = True

        self._start_cleanup_thread()

        logger.info("TaskTracker initialized")

    def _start_cleanup_thread(self):
        """启动清理线程"""
        def cleanup_loop():
            while self._running:
                try:
                    time.sleep(self._cleanup_interval)
                    if self._running:
                        self.cleanup_old_tasks()
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def start_tracking(self, name: str, description: str = "",
                      metadata: typing.Optional[typing.Dict[str, typing.Any]] = None,
                      parent_task_id: typing.Optional[str] = None) -> TaskInfo:
        """
        开始追踪任务

        参数:
            name: 任务名称
            description: 任务描述
            metadata: 元数据
            parent_task_id: 父任务 ID

        返回:
            TaskInfo: 任务信息
        """
        with self._lock:
            task = TaskInfo(
                name=name,
                description=description,
                status=TaskStatus.RUNNING,
                started_at=datetime.datetime.now(datetime.timezone.utc),
                metadata=metadata or {},
                parent_task_id=parent_task_id,
            )

            self._tasks[task.task_id] = task

            # 添加到父任务的子任务列表
            if parent_task_id and parent_task_id in self._tasks:
                self._tasks[parent_task_id].subtasks.append(task.task_id)

            self._notify_subscribers("status_change", task)

            logger.info(f"Started tracking task: {task.task_id} - {name}")
            return task

    def update_progress(self, task_id: str, progress: float,
                       message: str = "") -> bool:
        """
        更新任务进度

        参数:
            task_id: 任务 ID
            progress: 进度 (0-100)
            message: 进度消息

        返回:
            bool: 是否更新成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.is_terminal:
                return False

            task.progress = min(100.0, max(0.0, progress))
            if message:
                task.metadata["progress_message"] = message

            self._notify_subscribers("progress_update", task)

            logger.debug(f"Task {task_id} progress: {progress:.1f}%")
            return True

    def complete_task(self, task_id: str,
                     result: typing.Optional[typing.Dict[str, typing.Any]] = None) -> bool:
        """
        完成任务

        参数:
            task_id: 任务 ID
            result: 任务结果

        返回:
            bool: 是否完成成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.is_terminal:
                return False

            task.status = TaskStatus.COMPLETED
            task.progress = 100.0
            task.completed_at = datetime.datetime.now(datetime.timezone.utc)
            task.result = result

            self._notify_subscribers("task_completed", task)
            self._notify_subscribers("status_change", task)

            logger.info(f"Task completed: {task_id}")
            return True

    def fail_task(self, task_id: str, error_message: str) -> bool:
        """
        任务失败

        参数:
            task_id: 任务 ID
            error_message: 错误信息

        返回:
            bool: 是否设置成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.is_terminal:
                return False

            task.status = TaskStatus.FAILED
            task.completed_at = datetime.datetime.now(datetime.timezone.utc)
            task.error_message = error_message

            self._notify_subscribers("task_failed", task)
            self._notify_subscribers("status_change", task)

            logger.info(f"Task failed: {task_id} - {error_message}")
            return True

    def pause_task(self, task_id: str) -> bool:
        """
        暂停任务

        参数:
            task_id: 任务 ID

        返回:
            bool: 是否暂停成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.status != TaskStatus.RUNNING:
                return False

            task.status = TaskStatus.PAUSED
            self._notify_subscribers("status_change", task)

            logger.info(f"Task paused: {task_id}")
            return True

    def resume_task(self, task_id: str) -> bool:
        """
        恢复任务

        参数:
            task_id: 任务 ID

        返回:
            bool: 是否恢复成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.status != TaskStatus.PAUSED:
                return False

            task.status = TaskStatus.RUNNING
            self._notify_subscribers("status_change", task)

            logger.info(f"Task resumed: {task_id}")
            return True

    def stop_task(self, task_id: str, reason: str = "Cancelled") -> bool:
        """
        停止任务

        参数:
            task_id: 任务 ID
            reason: 停止原因

        返回:
            bool: 是否停止成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.is_terminal:
                return False

            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.datetime.now(datetime.timezone.utc)
            task.error_message = reason

            self._notify_subscribers("status_change", task)

            logger.info(f"Task stopped: {task_id} - {reason}")
            return True

    def get_task_status(self, task_id: str) -> typing.Optional[TaskInfo]:
        """
        获取任务状态

        参数:
            task_id: 任务 ID

        返回:
            Optional[TaskInfo]: 任务信息
        """
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> typing.List[TaskInfo]:
        """
        获取所有任务

        返回:
            List[TaskInfo]: 任务列表
        """
        with self._lock:
            return list(self._tasks.values())

    def get_tasks_by_status(self, status: TaskStatus) -> typing.List[TaskInfo]:
        """
        按状态获取任务

        参数:
            status: 任务状态

        返回:
            List[TaskInfo]: 任务列表
        """
        with self._lock:
            return [task for task in self._tasks.values() if task.status == status]

    def subscribe(self, event_type: str, callback: typing.Callable) -> bool:
        """
        订阅任务事件

        参数:
            event_type: 事件类型 (status_change, progress_update, task_completed, task_failed)
            callback: 回调函数

        返回:
            bool: 是否订阅成功
        """
        if event_type not in self._subscribers:
            return False

        with self._lock:
            self._subscribers[event_type].append(callback)
            return True

    def _notify_subscribers(self, event_type: str, task: TaskInfo):
        """通知订阅者"""
        if event_type not in self._subscribers:
            return

        for callback in self._subscribers[event_type]:
            try:
                callback(task)
            except Exception as e:
                logger.error(f"Subscriber callback error: {e}")

    def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """
        清理旧任务

        参数:
            max_age_hours: 最大保留时间（小时）

        返回:
            int: 清理的任务数量
        """
        with self._lock:
            cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=max_age_hours)
            tasks_to_remove = []

            for task_id, task in self._tasks.items():
                if task.is_terminal and task.completed_at and task.completed_at < cutoff_time:
                    tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                del self._tasks[task_id]

            if tasks_to_remove:
                logger.info(f"Cleaned up {len(tasks_to_remove)} old tasks")

            return len(tasks_to_remove)

    def get_statistics(self) -> typing.Dict[str, typing.Any]:
        """
        获取统计信息

        返回:
            Dict: 统计信息
        """
        with self._lock:
            total_tasks = len(self._tasks)
            status_counts = {}

            for status in TaskStatus:
                status_counts[status.value] = 0

            for task in self._tasks.values():
                status_counts[task.status.value] += 1

            return {
                "total_tasks": total_tasks,
                "status_counts": status_counts,
                "subscribers": {
                    event_type: len(callbacks)
                    for event_type, callbacks in self._subscribers.items()
                },
            }

    def shutdown(self):
        """关闭任务追踪器"""
        self._running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)


# ────── 单例管理 ──────

_tracker_instance: typing.Optional[TaskTracker] = None
_instance_lock = threading.Lock()


def get_task_tracker(**kwargs) -> TaskTracker:
    """获取全局任务追踪器实例（单例模式）"""
    global _tracker_instance
    if _tracker_instance is None:
        with _instance_lock:
            if _tracker_instance is None:
                _tracker_instance = TaskTracker(**kwargs)
    return _tracker_instance


def reset_task_tracker():
    """重置任务追踪器单例"""
    global _tracker_instance
    with _instance_lock:
        if _tracker_instance:
            _tracker_instance.shutdown()
        _tracker_instance = None