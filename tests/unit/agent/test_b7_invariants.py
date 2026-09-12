"""B-7 Phase 2 不变量锁存（立项 v2 §8.3.4 + §6 验收标准 3）

锁存 stop() 收口契约——关停后不得有任何存活重试工作：
1. 两模式：未决重试（task / future）全部被取消、引用集清空、无第二次执行
2. shared：常驻重试循环被 close、线程停止、无悬空 future
3. legacy：stop() 不触碰常驻重试循环（legacy 契约 = B-7 之前的行为，
   kill switch 回滚语义）
4. 整链自然收口（max_attempts 封顶）+ stop()：无未决、无悬空 future
"""

import asyncio
import threading
import time
from typing import Any, Dict, List

import pytest

import neurova.agent.scheduler as sched_mod
from neurova.agent.scheduler import (
    AutomationTask,
    RetryPolicy,
    TaskRequest,
    TaskScheduler,
    TaskStatus,
    TaskType,
)

RETRY_THREAD_NAME = "neurova-scheduler-retry-loop"
# OS 级真实等待（run_in_executor 桥接）：Windows loop.time() 粗粒度下
# asyncio.sleep 定时器会因时钟刻度跳变提前到期，不能作跨线程收口等待。
_REAL_TIME_SLEEP = time.sleep


async def _real_yield(seconds: float = 0.01):
    await asyncio.get_running_loop().run_in_executor(None, _REAL_TIME_SLEEP, seconds)


async def _wait_until(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await _real_yield(0.01)
    return predicate()


class FailingExecutor:
    """始终失败的假执行体——绝不触碰真实 agent.chat / LLM。"""

    def __init__(self):
        self.calls = 0
        self.calls_lock = threading.Lock()

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        with self.calls_lock:
            self.calls += 1
        return {"success": False, "error": "boom"}


def _make_retry_task(task_id: str, max_attempts: int, delay) -> AutomationTask:
    return AutomationTask(
        id=task_id,
        name=f"task-{task_id}",
        type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        retry_policy=RetryPolicy(
            enabled=True, max_attempts=max_attempts,
            retry_delay_seconds=delay, exponential_backoff=False,
        ),
    )


def _retry_loop_thread_alive() -> bool:
    return any(t.name == RETRY_THREAD_NAME and t.is_alive()
               for t in threading.enumerate())


@pytest.fixture(params=["legacy", "shared"])
def scheduler(request, monkeypatch):
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", request.param)
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    for t in list(s._pending_retry_tasks):
        t.cancel()
    for f in list(getattr(s, "_pending_retry_futures", ())):
        f.cancel()
    sched_mod._shutdown_retry_loop()
    TaskScheduler._instance = None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "shared"])
async def test_stop_latch_no_live_retry_work(mode, monkeypatch):
    """stop() 锁存：未决重试全收口、引用集清空、无第二次执行。"""
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", mode)
    TaskScheduler._instance = None
    scheduler = TaskScheduler()
    executor = FailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    # 真实 sleep(1) 挂住第一跳，制造"未决"
    scheduler.add_task(_make_retry_task("t-latch-stop", max_attempts=3, delay=1))
    try:
        execution = await asyncio.wait_for(
            scheduler.execute_task("t-latch-stop"), timeout=5
        )
        assert execution.status == TaskStatus.FAILED

        tasks_pending = [t for t in scheduler._pending_retry_tasks if not t.done()]
        futures = list(getattr(scheduler, "_pending_retry_futures", ()))
        futures_pending = [f for f in futures if not f.done()]
        if mode == "shared":
            assert len(tasks_pending) == 0 and len(futures_pending) == 1, \
                "shared：未决重试必须是常驻循环上的 1 个 future"
        else:
            assert len(tasks_pending) == 1 and len(futures_pending) == 0, \
                "legacy：未决重试必须是本循环上的 1 个 task"

        entry_before_stop = sched_mod._retry_loop_holder.get("entry")

        scheduler.stop()

        # 锁存 1：所有未决重试工作完成（取消）——cancel 是异步生效的
        # （CancelledError 须由其所属循环处理），轮询等待而非即断
        assert await _wait_until(
            lambda: all(t.done() for t in tasks_pending)
            and all(f.done() for f in futures_pending)
        ), "stop() 后未决重试工作必须全部完成（取消）"
        # 锁存 2：引用集清空（无悬空 task / future）
        assert await _wait_until(
            lambda: not scheduler._pending_retry_tasks
            and not getattr(scheduler, "_pending_retry_futures", set())
        ), "stop() 后引用集必须被 done_callback 清空"
        # 锁存 3：无第二次执行（重试被取消，不是被吞）
        assert executor.calls == 1

        if mode == "shared":
            # 锁存 4（shared）：常驻重试循环已 close、线程停止
            assert not sched_mod._retry_loop_holder, "holder 必须弹出条目"
            assert not _retry_loop_thread_alive(), "重试循环线程必须已停止"
        else:
            # 锁存 4（legacy）：stop() 不触碰常驻重试循环（B-7 前的契约）
            entry_after_stop = sched_mod._retry_loop_holder.get("entry")
            assert entry_after_stop is entry_before_stop, "legacy stop() 不得收口常驻重试循环"
    finally:
        for t in list(scheduler._pending_retry_tasks):
            t.cancel()
        for f in list(getattr(scheduler, "_pending_retry_futures", ())):
            f.cancel()
        sched_mod._shutdown_retry_loop()
        TaskScheduler._instance = None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "shared"])
async def test_completed_chain_then_stop_leaves_no_dangling_work(mode, monkeypatch):
    """整链收口（max_attempts 封顶）+ stop()：无未决、无悬空 future。"""
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", mode)
    TaskScheduler._instance = None
    scheduler = TaskScheduler()
    executor = FailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    # 0.05s 退避 ×2（max_attempts=3），高于 Windows 时钟粗粒度
    scheduler.add_task(_make_retry_task("t-latch-chain", max_attempts=3, delay=0.05))
    try:
        await asyncio.wait_for(scheduler.execute_task("t-latch-chain"), timeout=5)
        await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)

        assert executor.calls == 3, "整链必须跑到 max_attempts 封顶"
        # 引用集清空（done_callback 收口）
        assert await _wait_until(
            lambda: not scheduler._pending_retry_tasks
            and not getattr(scheduler, "_pending_retry_futures", set())
        ), "整链收口后引用集必须清空"
        assert not scheduler._running_executions

        scheduler.stop()
        assert not scheduler._pending_retry_tasks
        assert not getattr(scheduler, "_pending_retry_futures", set())
        assert executor.calls == 3, "链已封顶，stop() 不得引发额外执行"
        if mode == "shared":
            assert not _retry_loop_thread_alive(), "shared stop() 后重试循环线程必须停止"
    finally:
        for t in list(scheduler._pending_retry_tasks):
            t.cancel()
        for f in list(getattr(scheduler, "_pending_retry_futures", ())):
            f.cancel()
        sched_mod._shutdown_retry_loop()
        TaskScheduler._instance = None


def test_legacy_stop_does_not_touch_retry_loop(monkeypatch):
    """legacy 契约：stop() 不关闭常驻重试循环（不归它管；kill switch 回滚语义）。

    （shared 模式的"stop 后循环已 close"锁存在 test_stop_latch_no_live_retry_work。）
    """
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", "legacy")
    TaskScheduler._instance = None
    try:
        loop = sched_mod._get_retry_loop()  # 预置一个存活循环（模拟先前 shared 期残留）
        scheduler = TaskScheduler()
        scheduler._apscheduler = None

        scheduler.stop()

        entry = sched_mod._retry_loop_holder.get("entry")
        assert entry is not None and entry[0] is loop, "legacy stop() 不得关闭常驻重试循环"
        assert not loop.is_closed()
    finally:
        sched_mod._shutdown_retry_loop()
