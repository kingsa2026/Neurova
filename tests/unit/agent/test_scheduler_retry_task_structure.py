"""台账 #7（2026-09-11）防回归：重试链必须为独立任务结构

旧实现：_handle_retry 在初始 execute_task 帧内 await 整条重试链——
- 内层 execution 的 finally 先入历史 → history append 顺序与执行顺序相反
- 外层 execution 的 ended_at/duration_ms 跨越整条重试链
- _running_executions 注册跨整条链

新契约：
1. execute_task 返回时其 ended_at/duration 只覆盖自己那次执行
2. history append 顺序 == 执行顺序（初始 → retry → ...）
3. 未决重试任务被持引用（_pending_retry_tasks），shutdown（stop()）时被 cancel
4. max_attempts 封顶与退避语义由 test_scheduler_retry_propagation.py 承接
"""

import asyncio
from typing import Any, Dict

import pytest

from neurova.agent.scheduler import (
    AutomationTask,
    RetryPolicy,
    TaskRequest,
    TaskScheduler,
    TaskStatus,
    TaskType,
)


@pytest.fixture
def scheduler():
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    # 收尾：清掉可能残留的未决重试任务，防跨测试泄漏
    for t in list(s._pending_retry_tasks):
        t.cancel()
    TaskScheduler._instance = None


class FlakyThenFailingExecutor:
    """记录每次执行的起止时刻；始终失败（触发重试链）"""

    def __init__(self):
        self.records = []  # [(phase, execution_id, timestamp)]

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        self.records.append(("execute_start", execution.id, asyncio.get_event_loop().time()))
        await asyncio.sleep(0)
        self.records.append(("execute_end", execution.id, asyncio.get_event_loop().time()))
        return {"success": False, "error": "boom"}


def _make_task(task_id: str = "t-struct", max_attempts: int = 3) -> AutomationTask:
    return AutomationTask(
        id=task_id,
        name=f"task-{task_id}",
        type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        retry_policy=RetryPolicy(
            enabled=True,
            max_attempts=max_attempts,
            retry_delay_seconds=1,
            exponential_backoff=True,
        ),
    )


@pytest.mark.asyncio
async def test_outer_duration_covers_only_own_execution(scheduler, monkeypatch):
    """外层 execution 的 ended_at/duration 不得跨越重试链

    旧实现：初始 execute_task 的 finally 在整条链结束才跑 → 外层
    ended_at 晚于所有重试。新契约：外层 ended_at 早于每一次重试。
    """
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-dur", max_attempts=3))

    async def fake_sleep(_delay):
        return  # 注意：asyncio.sleep 已被 patch，体内不得再调它（自递归）

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    execution = await asyncio.wait_for(scheduler.execute_task("t-dur"), timeout=5)
    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)

    history = scheduler.get_execution_history("t-dur")
    assert len(history) == 3
    outer, *retries = history
    assert outer.id == execution.id
    assert outer.status == TaskStatus.FAILED
    assert outer.ended_at is not None and outer.duration_ms is not None
    # 新契约锚点：外层 ended_at 不晚于任何重试的 ended_at。
    # 用 <= 而非 <：sleep 已 patch 成 no-op，Windows datetime.now() 粒度
    # （~15.6ms）下瞬时重试与外层收尾会落在同一时钟刻度；旧实现外层
    # ended_at 在链尾（全部重试之后）落定，对它连 <= 都必红，甄别力不减。
    assert all(outer.ended_at <= r.ended_at for r in retries)


@pytest.mark.asyncio
async def test_history_append_order_matches_execution_order(scheduler, monkeypatch):
    """history append 顺序 == 执行顺序（旧实现为反序）"""
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-order", max_attempts=3))

    async def fake_sleep(_delay):
        return  # 注意：asyncio.sleep 已被 patch，体内不得再调它（自递归）

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    await asyncio.wait_for(scheduler.execute_task("t-order"), timeout=5)
    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)

    history = scheduler.get_execution_history("t-order")
    assert len(history) == 3
    assert [e.triggered_by for e in history] == ["manual", "retry", "retry"]
    # 执行顺序（executor.records 的 start 序）与 history 顺序一致
    exec_start_ids = [r[1] for r in executor.records if r[0] == "execute_start"]
    assert exec_start_ids == [e.id for e in history]


@pytest.mark.asyncio
async def test_running_executions_not_held_across_retry_chain(scheduler, monkeypatch):
    """初始 execution 返回后即从 _running_executions 清理，不跨链注册"""
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-run", max_attempts=3))

    async def fake_sleep(_delay):
        return  # 注意：asyncio.sleep 已被 patch，体内不得再调它（自递归）

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    execution = await asyncio.wait_for(scheduler.execute_task("t-run"), timeout=5)
    assert execution.id not in scheduler._running_executions

    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)
    assert len(scheduler._running_executions) == 0


@pytest.mark.asyncio
async def test_stop_cancels_pending_retry_tasks(scheduler, monkeypatch):
    """stop() 必须取消未决重试任务（shutdown 收口）"""
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-stop", max_attempts=3))

    # 不 patch sleep：让第一跳重试真实 sleep(1) 挂着，制造"未决"状态
    execution = await asyncio.wait_for(scheduler.execute_task("t-stop"), timeout=5)
    assert execution.status == TaskStatus.FAILED

    # execute_task 返回时应有 1 个未决重试任务（正在 sleep）
    pending = [t for t in scheduler._pending_retry_tasks if not t.done()]
    assert len(pending) == 1, "execute_task 返回后必须存在持引用的未决重试任务"

    scheduler.stop()  # 无 apscheduler 也应安全执行取消逻辑

    # 取消后 done_callback（discard）在循环调度中清空引用集
    for _ in range(50):
        if not scheduler._pending_retry_tasks:
            break
        await asyncio.sleep(0)
    assert all(t.done() for t in pending), "stop() 后未决重试任务必须被取消"
    assert not scheduler._pending_retry_tasks, "done_callback 必须清空引用集"
    # 第一跳重试被取消 → 永远不会执行第二次 execute
    assert len([r for r in executor.records if r[0] == "execute_start"]) == 1


@pytest.mark.asyncio
async def test_drain_pending_retries_waits_full_chain(scheduler, monkeypatch):
    """drain_pending_retries 必须等待整条链（含链中新增的下一跳）"""
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-drain", max_attempts=4))

    real_sleep = asyncio.sleep  # 先捕获真 sleep，供测试内 flush 调度

    async def fake_sleep(_delay):
        return  # 注意：asyncio.sleep 已被 patch，体内不得再调它（自递归）

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    await asyncio.wait_for(scheduler.execute_task("t-drain"), timeout=5)
    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)

    # max_attempts=4 → 共 4 次执行；drain 后无非 done 重试任务
    assert len([r for r in executor.records if r[0] == "execute_start"]) == 4
    assert all(t.done() for t in scheduler._pending_retry_tasks)
    # 真 sleep 让一轮循环调度跑完 done_callback（discard）→ 引用集清空
    await real_sleep(0)
    assert not scheduler._pending_retry_tasks
