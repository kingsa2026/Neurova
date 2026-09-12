"""
任务跟踪器单元测试（asyncio 任务注册表）

B-12（2026-09-11 登记项清尾）：同步任务路径整体删除——start_tracking/
update_progress/complete_task/fail_task/pause/resume/stop/get_task_status/
get_all_tasks/get_tasks_by_status、TaskInfo/TaskStatus 数据模型、清理线程
全部随零调用方的死路径消亡（_tasks 写入口唯 start_tracking 一处）。
存活面 = P0-2 asyncio 注册表（register_async_task / lookup /
request_session_stop / snapshot）+ 单例管理。本文件锁存死路径不得复活。
"""
import pytest
import asyncio

from neurova.core.task_tracker import (
    TaskTracker,
    get_task_tracker,
    reset_task_tracker,
)


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


class TestAsyncTaskRegistry:
    """P0-2：asyncio 任务注册表（/console/chat/stop 真取消的根基）。

    旧 stop_task 只翻状态不取消任何 asyncio Task——空壳假停止。
    register_async_task / request_session_stop 提供真取消能力。
    """

    def test_register_and_lookup(self):
        tracker = TaskTracker()

        async def scenario():
            async def work():
                await asyncio.sleep(10)

            task = asyncio.create_task(work())
            entry = tracker.register_async_task("s1", task, kind="chat")
            assert entry["session_id"] == "s1"
            assert entry["kind"] == "chat"
            assert len(tracker.lookup_async_tasks("s1")) == 1
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(scenario())

    def test_request_session_stop_cancels_running_task(self):
        tracker = TaskTracker()

        async def scenario():
            hit = {"cancelled": False}

            async def work():
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    hit["cancelled"] = True
                    raise

            task = asyncio.create_task(work())
            tracker.register_async_task("s1", task, kind="chat")
            await asyncio.sleep(0)  # 让 task 先启动进入 await 点（首步前取消不进协程体）
            n = tracker.request_session_stop("s1")
            assert n == 1
            with pytest.raises(asyncio.CancelledError):
                await task
            assert hit["cancelled"] is True

        asyncio.run(scenario())

    def test_request_session_stop_unknown_returns_zero(self):
        assert TaskTracker().request_session_stop("nope") == 0

    def test_done_callback_auto_removes(self):
        tracker = TaskTracker()

        async def scenario():
            async def quick():
                return 1

            task = asyncio.create_task(quick())
            tracker.register_async_task("s1", task)
            await task
            await asyncio.sleep(0)
            assert tracker.lookup_async_tasks("s1") == []

        asyncio.run(scenario())

    def test_snapshot_reports_running_tasks(self):
        tracker = TaskTracker()

        async def scenario():
            async def work():
                await asyncio.sleep(10)

            task = asyncio.create_task(work())
            tracker.register_async_task("s1", task, kind="chat")
            snap = tracker.snapshot_async_tasks()
            assert len(snap) == 1
            assert snap[0]["session_id"] == "s1"
            assert snap[0]["kind"] == "chat"
            assert snap[0]["duration"] >= 0
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(scenario())


class TestSyncPathAntiRevival:
    """B-12 锁存：同步任务路径（TaskInfo/TaskStatus/同步方法）不得复活。"""

    def test_removed_symbols_stay_removed(self):
        import neurova.core.task_tracker as tt

        for name in (
            "start_tracking", "update_progress", "complete_task", "fail_task",
            "pause_task", "resume_task", "stop_task", "get_task_status",
            "get_all_tasks", "get_tasks_by_status", "subscribe",
            "cleanup_old_tasks", "get_statistics", "TaskInfo", "TaskStatus",
        ):
            assert not hasattr(tt, name), f"已删除的同步路径符号复活: {name}"
            assert not hasattr(tt.TaskTracker, name), f"TaskTracker.{name} 复活"

    def test_no_background_cleanup_thread(self):
        """清理线程只服务已删除的 _tasks——异步注册表自清，不应有线程。"""
        tracker = TaskTracker()
        assert not hasattr(tracker, "_cleanup_thread")
        assert not hasattr(tracker, "_tasks")
