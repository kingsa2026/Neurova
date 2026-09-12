from __future__ import annotations

"""
TaskTracker - 任务追踪器（asyncio 任务注册表）

职责：
- 运行中 asyncio.Task 的注册与查询（按会话）
- 会话级真取消（Task.cancel()，取消沿 await 点传播中断 LLM/工具协程）
- 后台任务面板快照

历史注记（B-11/B-12 清理，2026-09-11）：同步任务路径（start_tracking/
update_progress/complete_task/fail_task/pause/resume/stop/get_task_status/
get_all_tasks/get_tasks_by_status/subscribe/notify/cleanup_old_tasks/
get_statistics、TaskInfo/TaskStatus 数据模型与清理线程）随 start_tracking
（全仓零运行时调用方）一并删除——_tasks 写入口唯此一处，死路径整体消亡；
_max_tasks 上限未执行的问题同步消除。活跃路径是 asyncio 注册表
（register_async_task，done 回调自动移除，天然自清，无需上限）。
"""

import asyncio
from neurova.core.logger import get_logger
import threading
import time
import typing

logger = get_logger(__name__)


# ────── 主类 ──────


class TaskTracker:
    """运行中 asyncio 任务注册表（/console/chat/stop 真取消的根基）。

    旧 stop_task 只翻状态不取消任何 asyncio Task——空壳假停止，后端
    照常跑完整轮并消耗 token。此注册表持有运行中的 asyncio.Task，
    request_session_stop 据此 Task.cancel()，取消沿 await 点天然传播
    中断 LLM/工具协程（对齐 QwenPaw app/task_tracker.py 机制）。
    """

    def __init__(self):
        self._lock = threading.RLock()

        # P0-2：运行中 asyncio 任务注册表（session_id -> entries）
        self._async_tasks: typing.Dict[str, typing.List[typing.Dict[str, typing.Any]]] = {}

        logger.info("TaskTracker initialized")

    # ── P0-2：asyncio 任务注册表 ──────────────────────────────────────

    def register_async_task(
        self, session_id: str, task: "asyncio.Task", kind: str = "chat"
    ) -> typing.Dict[str, typing.Any]:
        """注册运行中的 asyncio 任务；完成后自动移除。"""
        entry = {
            "session_id": session_id,
            "kind": kind,
            "task": task,
            "started_at": time.time(),
        }
        with self._lock:
            self._async_tasks.setdefault(session_id, []).append(entry)
        task.add_done_callback(lambda _t: self._discard_async_task(entry))
        return {k: v for k, v in entry.items() if k != "task"}

    def _discard_async_task(self, entry: typing.Dict[str, typing.Any]) -> None:
        with self._lock:
            entries = self._async_tasks.get(entry["session_id"])
            if entries and entry in entries:
                entries.remove(entry)
            if entries is not None and not entries:
                self._async_tasks.pop(entry["session_id"], None)

    def lookup_async_tasks(self, session_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """列出会话的运行中 asyncio 任务（不含 task 对象本身）。"""
        with self._lock:
            entries = list(self._async_tasks.get(session_id, []))
        return [
            {k: v for k, v in e.items() if k != "task"}
            for e in entries
            if not e["task"].done()
        ]

    def request_session_stop(self, session_id: str) -> int:
        """取消会话的全部运行中 asyncio 任务，返回取消数量。"""
        with self._lock:
            entries = [e for e in self._async_tasks.get(session_id, []) if not e["task"].done()]
        for entry in entries:
            entry["task"].cancel()
            logger.info("会话任务已请求停止: session=%s kind=%s", session_id, entry["kind"])
        return len(entries)

    def snapshot_async_tasks(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """全部运行中 asyncio 任务快照（后台任务面板数据源）。"""
        with self._lock:
            entries = [
                e for lst in self._async_tasks.values() for e in lst if not e["task"].done()
            ]
        now = time.time()
        return [
            {
                "session_id": e["session_id"],
                "kind": e["kind"],
                "started_at": e["started_at"],
                "duration": now - e["started_at"],
            }
            for e in entries
        ]


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
        _tracker_instance = None
