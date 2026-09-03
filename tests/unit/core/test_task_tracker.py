"""
任务跟踪器单元测试
测试 TaskTracker 的各种功能
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from neurova.core.task_tracker import (
    TaskTracker,
    TaskStatus,
    TaskInfo,
    get_task_tracker,
    reset_task_tracker,
)


class TestTaskStatus:
    """测试任务状态枚举"""

    def test_task_status_values(self):
        """测试任务状态值"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.PAUSED.value == "paused"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"
        assert TaskStatus.TIMEOUT.value == "timeout"


class TestTaskInfo:
    """测试任务信息类"""

    def test_create_task_info(self):
        """测试创建任务信息"""
        task_info = TaskInfo(
            task_id="test-task-123",
            metadata={"type": "test", "user": "test-user"},
            status=TaskStatus.PENDING
        )
        assert task_info.task_id == "test-task-123"
        assert task_info.metadata == {"type": "test", "user": "test-user"}
        assert task_info.status == TaskStatus.PENDING
        assert task_info.progress == 0.0
        assert task_info.error_message == ""
        assert task_info.result is None
        assert task_info.created_at is not None
        assert task_info.started_at is None
        assert task_info.completed_at is None

    def test_to_dict(self):
        """测试转换为字典"""
        task_info = TaskInfo(
            task_id="test-task",
            name="test",
            metadata={"key": "value"},
            status=TaskStatus.RUNNING,
            progress=50.0,
            result={"output": "test"}
        )
        data = task_info.to_dict()
        assert data["task_id"] == "test-task"
        assert data["status"] == "running"
        assert data["progress"] == 50.0
        assert data["metadata"] == {"key": "value"}
        assert data["result"] == {"output": "test"}
        assert "created_at" in data

    def test_duration(self):
        """测试持续时间"""
        task_info = TaskInfo(task_id="test")
        assert task_info.duration is None

        task_info.started_at = datetime.now(timezone.utc)
        duration = task_info.duration
        assert duration is not None
        assert duration >= 0

    def test_is_terminal(self):
        """测试终止状态"""
        task_info = TaskInfo(task_id="test", status=TaskStatus.COMPLETED)
        assert task_info.is_terminal is True

        task_info = TaskInfo(task_id="test", status=TaskStatus.RUNNING)
        assert task_info.is_terminal is False


class TestTaskTracker:
    """测试任务跟踪器"""

    @pytest.fixture
    def tracker(self):
        """创建任务跟踪器实例"""
        t = TaskTracker()
        yield t
        t.shutdown()

    def test_start_tracking(self, tracker):
        """测试开始跟踪任务"""
        task_info = tracker.start_tracking(
            name="test-task-1",
            metadata={"type": "test", "user": "user1"}
        )
        assert task_info is not None
        assert task_info.name == "test-task-1"
        assert task_info.status == TaskStatus.RUNNING
        assert task_info.metadata == {"type": "test", "user": "user1"}
        assert task_info.task_id in tracker._tasks

    def test_start_tracking_duplicate(self, tracker):
        """测试重复跟踪任务"""
        t1 = tracker.start_tracking(name="test-task", metadata={})
        t2 = tracker.start_tracking(name="test-task", metadata={})
        assert t1 is not None
        assert t2 is not None
        assert t1.task_id != t2.task_id

    def test_update_progress(self, tracker):
        """测试更新进度"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        result = tracker.update_progress(task_info.task_id, 50.0, "Halfway done")
        assert result is True
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.progress == 50.0
        assert updated.metadata.get("progress_message") == "Halfway done"
        assert updated.status == TaskStatus.RUNNING

    def test_update_progress_clamps_value(self, tracker):
        """测试进度值被限制在0-100之间"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.update_progress(task_info.task_id, 150.0, "Too high")
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.progress == 100.0

        tracker.update_progress(task_info.task_id, -50.0, "Too low")
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.progress == 0.0

    def test_update_progress_nonexistent(self, tracker):
        """测试更新不存在的任务"""
        result = tracker.update_progress("nonexistent", 50.0, "Test")
        assert result is False

    def test_complete_task(self, tracker):
        """测试完成任务"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        result = tracker.complete_task(task_info.task_id, {"result": "success"})
        assert result is True
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.progress == 100.0
        assert updated.result == {"result": "success"}
        assert updated.completed_at is not None

    def test_complete_task_nonexistent(self, tracker):
        """测试完成不存在的任务"""
        result = tracker.complete_task("nonexistent", {})
        assert result is False

    def test_fail_task(self, tracker):
        """测试任务失败"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        result = tracker.fail_task(task_info.task_id, "Something went wrong")
        assert result is True
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.status == TaskStatus.FAILED
        assert updated.error_message == "Something went wrong"
        assert updated.completed_at is not None

    def test_fail_task_nonexistent(self, tracker):
        """测试失败不存在的任务"""
        result = tracker.fail_task("nonexistent", "Test")
        assert result is False

    def test_pause_task(self, tracker):
        """测试暂停任务"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.update_progress(task_info.task_id, 50.0, "Working")
        result = tracker.pause_task(task_info.task_id)
        assert result is True
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.status == TaskStatus.PAUSED

    def test_pause_task_wrong_status(self, tracker):
        """测试在错误状态下暂停"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.complete_task(task_info.task_id, {})
        result = tracker.pause_task(task_info.task_id)
        assert result is False

    def test_pause_task_nonexistent(self, tracker):
        """测试暂停不存在的任务"""
        result = tracker.pause_task("nonexistent")
        assert result is False

    def test_resume_task(self, tracker):
        """测试恢复任务"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.update_progress(task_info.task_id, 50.0, "Working")
        tracker.pause_task(task_info.task_id)
        result = tracker.resume_task(task_info.task_id)
        assert result is True
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.status == TaskStatus.RUNNING

    def test_resume_task_wrong_status(self, tracker):
        """测试在错误状态下恢复"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        result = tracker.resume_task(task_info.task_id)
        assert result is False

    def test_resume_task_nonexistent(self, tracker):
        """测试恢复不存在的任务"""
        result = tracker.resume_task("nonexistent")
        assert result is False

    def test_stop_task(self, tracker):
        """测试停止任务"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.update_progress(task_info.task_id, 50.0, "Working")
        result = tracker.stop_task(task_info.task_id)
        assert result is True
        updated = tracker.get_task_status(task_info.task_id)
        assert updated.status == TaskStatus.CANCELLED
        assert updated.completed_at is not None

    def test_stop_task_already_completed(self, tracker):
        """测试停止已完成的任务"""
        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.complete_task(task_info.task_id, {})
        result = tracker.stop_task(task_info.task_id)
        assert result is False

    def test_stop_task_nonexistent(self, tracker):
        """测试停止不存在的任务"""
        result = tracker.stop_task("nonexistent")
        assert result is False

    def test_get_task_status(self, tracker):
        """测试获取任务状态"""
        task_info = tracker.start_tracking(name="test-task", metadata={"key": "value"})
        retrieved = tracker.get_task_status(task_info.task_id)
        assert retrieved is not None
        assert retrieved.task_id == task_info.task_id

    def test_get_task_status_nonexistent(self, tracker):
        """测试获取不存在的任务状态"""
        task_info = tracker.get_task_status("nonexistent")
        assert task_info is None

    def test_get_all_tasks(self, tracker):
        """测试获取所有任务"""
        t1 = tracker.start_tracking(name="task1", metadata={})
        t2 = tracker.start_tracking(name="task2", metadata={})
        tasks = tracker.get_all_tasks()
        assert len(tasks) == 2
        task_ids = {t.task_id for t in tasks}
        assert t1.task_id in task_ids
        assert t2.task_id in task_ids

    def test_get_tasks_by_status(self, tracker):
        """测试按状态获取任务"""
        t1 = tracker.start_tracking(name="task1", metadata={})
        t2 = tracker.start_tracking(name="task2", metadata={})
        tracker.complete_task(t2.task_id, {})

        running_tasks = tracker.get_tasks_by_status(TaskStatus.RUNNING)
        assert len(running_tasks) == 1
        assert running_tasks[0].task_id == t1.task_id

        completed_tasks = tracker.get_tasks_by_status(TaskStatus.COMPLETED)
        assert len(completed_tasks) == 1
        assert completed_tasks[0].task_id == t2.task_id

    def test_subscribe(self, tracker):
        """测试订阅任务事件"""
        received_events = []

        def on_progress(task):
            received_events.append(("progress", task.task_id))

        def on_complete(task):
            received_events.append(("completed", task.task_id))

        tracker.subscribe("progress_update", on_progress)
        tracker.subscribe("task_completed", on_complete)

        task_info = tracker.start_tracking(name="test-task", metadata={})
        tracker.update_progress(task_info.task_id, 50.0, "Working...")
        tracker.complete_task(task_info.task_id, {"result": "done"})

        assert ("progress", task_info.task_id) in received_events
        assert ("completed", task_info.task_id) in received_events

    def test_cleanup_old_tasks(self, tracker):
        """测试清理旧任务"""
        t1 = tracker.start_tracking(name="new-task", metadata={})
        t2 = tracker.start_tracking(name="old-task", metadata={})

        tracker.complete_task(t1.task_id, {})
        tracker.complete_task(t2.task_id, {})

        old_task = tracker.get_task_status(t2.task_id)
        old_task.completed_at = datetime.now(timezone.utc).replace(
            year=2020, month=1, day=1
        )

        count = tracker.cleanup_old_tasks(max_age_hours=1)

        assert tracker.get_task_status(t1.task_id) is not None
        assert tracker.get_task_status(t2.task_id) is None

    def test_get_statistics(self, tracker):
        """测试获取统计信息"""
        tracker.start_tracking(name="task1", metadata={})
        stats = tracker.get_statistics()
        assert stats["total_tasks"] == 1

    def test_shutdown(self, tracker):
        """测试关闭"""
        tracker.shutdown()
        assert tracker._running is False


class TestGlobalTaskTracker:
    """测试全局任务跟踪器"""

    def test_get_task_tracker_singleton(self):
        """测试单例模式"""
        reset_task_tracker()
        tracker1 = get_task_tracker()
        tracker2 = get_task_tracker()
        assert tracker1 is tracker2
        reset_task_tracker()

    def test_get_task_tracker_returns_instance(self):
        """测试返回正确类型"""
        reset_task_tracker()
        tracker = get_task_tracker()
        assert isinstance(tracker, TaskTracker)
        reset_task_tracker()
