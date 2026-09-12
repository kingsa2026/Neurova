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

# B-7（2026-09-12）：shared 模式（方案 B）重试跑在常驻循环上，未决重试的
# 持引用形态是 concurrent.futures.Future（_pending_retry_futures）而非
# asyncio.Task（_pending_retry_tasks）。以下两个助手提供双模式统一的
# "未决/收口"视图——核心断言（未决数、全部收口、引用集清空）语义不变。
# 真实让出助手：经线程池执行 OS 级 time.sleep（高分辨率）。
# 不用 asyncio.sleep——Windows 上 loop.time() 粗粒度（~15.6ms）会让短
# sleep 的定时器因时钟刻度跳变提前到期（实测 0.01s sleep 34µs 返回），
# "真实让出"退化为微秒级，重试跳得以在初始执行入史前入史（跨线程
# 入史顺序竞态；生产退避为秒级不受此影响，纯测试装置问题）。
_REAL_TIME_SLEEP = time.sleep


async def _real_yield(seconds: float = 0.01):
    await asyncio.get_running_loop().run_in_executor(None, _REAL_TIME_SLEEP, seconds)



def _pending_retry_work(s) -> List[Any]:
    """双模式统一：未决重试工作（task 或 future）清单。"""
    tasks = [t for t in s._pending_retry_tasks if not t.done()]
    futures = [f for f in getattr(s, "_pending_retry_futures", ()) if not f.done()]
    return tasks + futures


def _all_retry_work_done(s) -> bool:
    tasks_done = all(t.done() for t in s._pending_retry_tasks)
    futures = getattr(s, "_pending_retry_futures", ())
    futures_done = all(f.done() for f in futures)
    return tasks_done and futures_done


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    """真实时间轮询：shared 模式 done_callback 在常驻循环线程上完成，
    跨线程收口无同步通知，deadline 兜底防永久等待。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await _real_yield()
    return predicate()


@pytest.fixture(params=["legacy", "shared"])
def scheduler(request, monkeypatch):
    # B-7：双模式参数化——env 开关全程生效（_get_exec_mode 每次读取）
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", request.param)
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    # 收尾：清掉可能残留的未决重试任务/future，防跨测试泄漏
    for t in list(s._pending_retry_tasks):
        t.cancel()
    for f in list(getattr(s, "_pending_retry_futures", ())):
        f.cancel()
    sched_mod._shutdown_retry_loop()
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
        # 注意：不得调已被 patch 的 asyncio.sleep（自递归）；经线程池真实让出
        # 10ms——shared 模式重试跳在常驻线程上，若不让出真实时间，跳可在初始
        # 执行的 finally 入史前入史（生产退避秒级无此竞态，纯装置伪影）。
        await _real_yield()

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
        # 注意：不得调已被 patch 的 asyncio.sleep（自递归）；经线程池真实让出
        # 10ms——shared 模式重试跳在常驻线程上，若不让出真实时间，跳可在初始
        # 执行的 finally 入史前入史（生产退避秒级无此竞态，纯装置伪影）。
        await _real_yield()

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
        # 注意：不得调已被 patch 的 asyncio.sleep（自递归）；经线程池真实让出
        # 10ms——shared 模式重试跳在常驻线程上，若不让出真实时间，跳可在初始
        # 执行的 finally 入史前入史（生产退避秒级无此竞态，纯装置伪影）。
        await _real_yield()

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    execution = await asyncio.wait_for(scheduler.execute_task("t-run"), timeout=5)
    assert execution.id not in scheduler._running_executions

    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)
    assert len(scheduler._running_executions) == 0


@pytest.mark.asyncio
async def test_stop_cancels_pending_retry_tasks(scheduler, monkeypatch):
    """stop() 必须取消未决重试任务（shutdown 收口）

    B-7 shared 适配：未决形态随模式为 task/future（核心断言语义不变——
    execute_task 返回后恰有 1 个持引用的未决重试；stop() 后全部收口且
    引用集清空；被取消的第一跳不得再执行）。
    """
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-stop", max_attempts=3))

    # 不 patch sleep：让第一跳重试真实 sleep(1) 挂着，制造"未决"状态
    execution = await asyncio.wait_for(scheduler.execute_task("t-stop"), timeout=5)
    assert execution.status == TaskStatus.FAILED

    # execute_task 返回时应有 1 个未决重试（正在 sleep）
    pending = _pending_retry_work(scheduler)
    assert len(pending) == 1, "execute_task 返回后必须存在持引用的未决重试任务"

    scheduler.stop()  # 无 apscheduler 也应安全执行取消逻辑

    # 收口后：全部未决完成、引用集清空（shared 回调在常驻线程上，轮询等待）
    assert await _wait_until(lambda: _all_retry_work_done(scheduler)), "stop() 后未决重试必须全部收口"
    assert await _wait_until(
        lambda: not scheduler._pending_retry_tasks
        and not getattr(scheduler, "_pending_retry_futures", set())
    ), "done_callback 必须清空引用集"
    assert all(w.done() for w in pending), "stop() 后未决重试任务必须被取消"
    # 第一跳重试被取消 → 永远不会执行第二次 execute
    assert len([r for r in executor.records if r[0] == "execute_start"]) == 1


@pytest.mark.asyncio
async def test_drain_pending_retries_waits_full_chain(scheduler, monkeypatch):
    """drain_pending_retries 必须等待整条链（含链中新增的下一跳）"""
    executor = FlakyThenFailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-drain", max_attempts=4))

    # B-7：真等待已由模块级 _real_yield 提供（经线程池 OS 级 sleep），
    # 此处可安全 patch 成短让出协程。
    async def fake_sleep(_delay):
        # 注意：不得调已被 patch 的 asyncio.sleep（自递归）；经线程池真实让出
        # 10ms——shared 模式重试跳在常驻线程上，若不让出真实时间，跳可在初始
        # 执行的 finally 入史前入史（生产退避秒级无此竞态，纯装置伪影）。
        await _real_yield()

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    await asyncio.wait_for(scheduler.execute_task("t-drain"), timeout=5)
    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)

    # max_attempts=4 → 共 4 次执行；drain 后无非 done 重试任务
    assert len([r for r in executor.records if r[0] == "execute_start"]) == 4
    assert _all_retry_work_done(scheduler)
    # 真 sleep 让一轮循环调度跑完 done_callback（discard）→ 引用集清空
    # （B-7 shared：discard 回调在常驻循环线程上完成，需真实时间轮询收口）
    assert await _wait_until(
        lambda: not scheduler._pending_retry_tasks
        and not getattr(scheduler, "_pending_retry_futures", set())
    )
