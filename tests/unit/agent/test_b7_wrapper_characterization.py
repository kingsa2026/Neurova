"""B-7 Phase 1 特征化套件（docs/B7调度器事件循环统一立项_2026-09-11.md v2 §8.3.1）

目的：在重构前把 `_execute_task_wrapper` 的可观测行为钉住，作为重构全程
安全网。重构（方案 B：仅重试出循环）后本套件必须仍然全绿——Part A 的
各断言在 legacy / shared 两模式下都成立（per-job 循环隔离保留，只有重试
收口方式变化）；Part B 钉 legacy 专属的 drain 语义。

已钉行为：
1. wrapper 触发 execute_task：事件 execution_started → execution_completed
   且指向同一 execution
2. wrapper 以 triggered_by="scheduler" 传参
3. 异常包装：wrapper 吞掉异常仅落日志（Task execution wrapper failed），
   不向 APScheduler 线程传播
4. _running_executions 生命周期：execution_started 时在册，
   execution_completed 前摘除，wrapper 返回后为空
5. per-job 事件循环：每次执行新建独立循环、返回前 close（隔离性保留）
6.（legacy 专属）wrapper 在 loop.close 前 drain 整条重试链

线程上下文注：wrapper 在生产中跑在 APScheduler 工作线程上（线程内无运行
中循环，run_until_complete 合法）。pytest 测试线程上有运行中的测试循环，
直接调用会撞 "Cannot run the event loop while another loop is running"——
经 run_in_executor 在无循环线程上调用以复现生产形态。

与 test_scheduler_retry_task_structure.py 的分工：该文件从 execute_task +
drain_pending_retries 入口钉重试链结构；本文件从 wrapper（APScheduler
实际入口）钉包装行为，不重复。
"""

import asyncio
import functools
import logging
import threading
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


async def run_wrapper(scheduler, task_id: str) -> None:
    """在无运行循环的工作线程上调用 _execute_task_wrapper（复现 APScheduler 形态）。"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, functools.partial(scheduler._execute_task_wrapper, task_id))


class RecordingExecutor:
    """确定性假执行体：记录调用线程、运行中循环；可配置成功/失败。"""

    def __init__(self, succeed: bool = True, execute_delay: float = 0.0):
        self.succeed = succeed
        self.execute_delay = execute_delay
        self.calls = 0
        self.threads: List[str] = []
        self.loops: List[asyncio.AbstractEventLoop] = []

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        self.calls += 1
        self.threads.append(threading.current_thread().name)
        self.loops.append(asyncio.get_running_loop())
        if self.execute_delay:
            await asyncio.sleep(self.execute_delay)
        if self.succeed:
            return {"success": True, "result": "ok"}
        return {"success": False, "error": "boom"}


class FailingRetryExecutor:
    """始终失败并记录每次执行的运行循环与线程（重试链特征化用）。"""

    def __init__(self):
        self.calls = 0
        self.threads: List[str] = []
        self.loops: List[asyncio.AbstractEventLoop] = []

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        self.calls += 1
        self.threads.append(threading.current_thread().name)
        self.loops.append(asyncio.get_running_loop())
        return {"success": False, "error": "boom"}


def _make_task(task_id: str, **retry_kwargs) -> AutomationTask:
    retry_policy = RetryPolicy(**retry_kwargs) if retry_kwargs else None
    return AutomationTask(
        id=task_id,
        name=f"task-{task_id}",
        type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        retry_policy=retry_policy,
    )


@pytest.fixture(params=["legacy", "shared"])
def scheduler(request, monkeypatch):
    """双模式参数化 fixture：env 开关在测试全程生效（_get_exec_mode 每次读 env）。

    teardown 用 getattr 防御——特征化阶段（实现前）shared 参数实际走 legacy
    代码路径，_pending_retry_futures / _shutdown_retry_loop 尚不存在。
    """
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", request.param)
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    for t in list(s._pending_retry_tasks):
        t.cancel()
    futures = getattr(s, "_pending_retry_futures", None)
    if futures:
        for f in list(futures):
            f.cancel()
    shutdown = getattr(sched_mod, "_shutdown_retry_loop", None)
    if shutdown is not None:
        shutdown()
    TaskScheduler._instance = None


@pytest.fixture
def scheduler_legacy(monkeypatch):
    """legacy 专属（Part B：drain 语义是 legacy 契约）。"""
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", "legacy")
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    for t in list(s._pending_retry_tasks):
        t.cancel()
    TaskScheduler._instance = None


# ── Part A：双模式不变的可观测行为 ──────────────────────────


@pytest.mark.asyncio
async def test_wrapper_executes_task_with_event_sequence(scheduler):
    """wrapper 触发 execute_task：started → completed，同一 execution，终态 SUCCESS"""
    executor = RecordingExecutor(succeed=True)
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-wrap-events"))

    events = []
    scheduler.add_event_handler(lambda et, data: events.append((et, data)))

    await run_wrapper(scheduler, "t-wrap-events")

    assert [et for et, _ in events] == ["execution_started", "execution_completed"]
    started, completed = events[0][1], events[1][1]
    assert started.id == completed.id
    assert completed.status == TaskStatus.SUCCESS
    assert executor.calls == 1
    history = scheduler.get_execution_history("t-wrap-events")
    assert len(history) == 1 and history[0].id == completed.id


@pytest.mark.asyncio
async def test_wrapper_passes_triggered_by_scheduler(scheduler):
    """wrapper 以 triggered_by="scheduler" 调 execute_task（事件与 history 双证）"""
    executor = RecordingExecutor(succeed=True)
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-wrap-trigger"))

    events = []
    scheduler.add_event_handler(lambda et, data: events.append((et, data)))

    await run_wrapper(scheduler, "t-wrap-trigger")

    assert all(data.triggered_by == "scheduler" for _, data in events)
    assert scheduler.get_execution_history("t-wrap-trigger")[0].triggered_by == "scheduler"


@pytest.mark.asyncio
async def test_wrapper_swallows_exceptions_and_logs(scheduler, monkeypatch, caplog):
    """异常包装：wrapper 吞异常仅落日志，不向 APScheduler 线程传播"""
    scheduler.add_task(_make_task("t-wrap-boom"))

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom-wrapper")

    monkeypatch.setattr(scheduler, "execute_task", _boom)

    with caplog.at_level(logging.ERROR, logger="neurova.agent.scheduler"):
        await run_wrapper(scheduler, "t-wrap-boom")  # 不抛——吞异常是 wrapper 对调度线程的契约

    wrapper_errors = [r for r in caplog.records if "Task execution wrapper failed" in r.getMessage()]
    assert wrapper_errors, "wrapper 必须落 'Task execution wrapper failed' 日志"
    assert any("boom-wrapper" in r.getMessage() for r in wrapper_errors)


@pytest.mark.asyncio
async def test_running_executions_lifecycle_within_wrapper(scheduler):
    """_running_executions：started 时在册，completed 前摘除，wrapper 返回后为空"""
    executor = RecordingExecutor(succeed=True)
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-wrap-running"))

    snapshots = []

    def _on_event(et, data):
        snapshots.append((et, data.id, data.id in scheduler._running_executions))

    scheduler.add_event_handler(_on_event)

    await run_wrapper(scheduler, "t-wrap-running")

    assert snapshots[0] == ("execution_started", snapshots[0][1], True), "执行开始时必须在册"
    assert snapshots[1] == ("execution_completed", snapshots[1][1], False), "completed 事件前必须已摘除"
    assert scheduler._running_executions == {}


@pytest.mark.asyncio
async def test_wrapper_uses_fresh_per_job_loop_and_closes_it(scheduler):
    """per-job 循环隔离（方案 B 保留）：每次执行新建循环，wrapper 返回前 close"""
    executor = RecordingExecutor(succeed=True)
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_task("t-wrap-loop1"))
    scheduler.add_task(_make_task("t-wrap-loop2"))

    await run_wrapper(scheduler, "t-wrap-loop1")
    await run_wrapper(scheduler, "t-wrap-loop2")

    assert len(executor.loops) == 2
    loop1, loop2 = executor.loops
    assert loop1 is not loop2, "两次 job 必须使用彼此独立的事件循环"
    assert loop1.is_closed() and loop2.is_closed(), "wrapper 返回前必须 close 本次 job 的循环"


# ── Part B：legacy 专属——wrapper 在 loop.close 前 drain 整条重试链 ──


@pytest.mark.asyncio
async def test_wrapper_legacy_drains_retry_chain_before_loop_close(scheduler_legacy, monkeypatch):
    """重试链跑在 job 循环上且 wrapper 返回前完成：若不先 drain，重试任务
    会随 loop.close() 被销毁（history 只有 1 条、循环上任务丢失）。"""
    executor = FailingRetryExecutor()
    scheduler_legacy._executors[TaskType.AGENT] = executor
    scheduler_legacy.add_task(
        _make_task("t-wrap-drain", enabled=True, max_attempts=3,
                   retry_delay_seconds=1, exponential_backoff=True)
    )

    async def fake_sleep(_delay):
        return  # no-op：链瞬间跑完；drain 语义由本测试钉住

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    await run_wrapper(scheduler_legacy, "t-wrap-drain")

    # drain 生效的直接证据：整条链（max_attempts=3）全部入史且顺序正确
    history = scheduler_legacy.get_execution_history("t-wrap-drain")
    assert [e.triggered_by for e in history] == ["scheduler", "retry", "retry"]
    assert executor.calls == 3
    # 三次执行（初始 + 两跳重试）全部发生在同一个 per-job 循环上
    assert len(executor.loops) == 3 and executor.loops[0] is executor.loops[1] is executor.loops[2]
    # 且该循环在 wrapper 返回前已被 close（先 drain 后 close 的时序锚点）
    assert executor.loops[0].is_closed()


# ── Part C：shared 模式新契约（方案 B：仅重试出循环）──────────────
# TDD：实现前这些测试为红（现状 env 开关被忽略、重试仍绑 job 循环）；
# 实现后转绿。C10 为 legacy/shared 漂移回归护栏（实现前经 legacy 路径
# 恰好为绿，实现后走 shared future 路径仍须绿）。

_RETRY_THREAD_NAME = "neurova-scheduler-retry-loop"


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    """真实时间轮询（跨线程 done_callback 收口无同步通知），deadline 兜底。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


@pytest.fixture
def scheduler_shared(monkeypatch):
    """shared 专属 fixture（Part C）。"""
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", "shared")
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    for t in list(s._pending_retry_tasks):
        t.cancel()
    futures = getattr(s, "_pending_retry_futures", None)
    if futures:
        for f in list(futures):
            f.cancel()
    shutdown = getattr(sched_mod, "_shutdown_retry_loop", None)
    if shutdown is not None:
        shutdown()
    TaskScheduler._instance = None


@pytest.mark.asyncio
async def test_shared_wrapper_returns_before_retry_chain_completes(scheduler_shared):
    """shared：wrapper 返回即返回（job 循环无未决任务），重试链挂在常驻循环上未完。

    真实退避 delay=1s：wrapper 返回时重试第一跳必然仍在 sleep——
    history 只有初始一条、pending future == 1、job 循环已关、常驻循环线程存活。
    """
    executor = FailingRetryExecutor()
    scheduler_shared._executors[TaskType.AGENT] = executor
    scheduler_shared.add_task(
        _make_task("t-shared-return", enabled=True, max_attempts=2,
                   retry_delay_seconds=1, exponential_backoff=False)
    )

    await run_wrapper(scheduler_shared, "t-shared-return")

    history = scheduler_shared.get_execution_history("t-shared-return")
    assert [e.triggered_by for e in history] == ["scheduler"], "wrapper 返回时重试尚未发生"
    assert executor.calls == 1

    futures = getattr(scheduler_shared, "_pending_retry_futures", None)
    assert futures is not None, "shared 模式必须有 _pending_retry_futures 引用集"
    pending_futures = [f for f in futures if not f.done()]
    assert len(pending_futures) == 1, "重试第一跳必须是常驻循环上的未决 future"
    assert scheduler_shared._pending_retry_tasks == set(), "shared 模式 job 循环上不得有重试任务"

    assert executor.loops[0].is_closed(), "job 循环仍须在 wrapper 返回前 close（per-job 隔离保留）"

    retry_threads = [t for t in threading.enumerate()
                     if t.name == _RETRY_THREAD_NAME and t.is_alive()]
    assert retry_threads, "常驻重试循环线程必须存活并承载未决重试"


@pytest.mark.asyncio
async def test_shared_retry_chain_runs_on_retry_loop_thread(scheduler_shared):
    """shared：重试跳在常驻重试循环线程上执行，而非 job 工作线程（P2 机制锚点）。"""
    executor = FailingRetryExecutor()
    scheduler_shared._executors[TaskType.AGENT] = executor
    scheduler_shared.add_task(
        _make_task("t-shared-thread", enabled=True, max_attempts=3,
                   retry_delay_seconds=0, exponential_backoff=True)
    )

    await run_wrapper(scheduler_shared, "t-shared-thread")
    await asyncio.wait_for(scheduler_shared.drain_pending_retries(), timeout=5)

    assert executor.calls == 3
    assert executor.threads[0] != _RETRY_THREAD_NAME, "初始执行在 job 工作线程"
    assert executor.threads[1:] == [_RETRY_THREAD_NAME] * 2, "重试跳必须跑在常驻重试循环线程上"
    assert all(loop.is_closed() for loop in executor.loops[:1]), "job 循环照常 close"


@pytest.mark.asyncio
async def test_shared_stop_cancels_pending_futures_and_closes_retry_loop(scheduler_shared):
    """shared：stop() 取消未决重试 future 并收口常驻循环（先 cancel 后 close）。"""
    executor = FailingRetryExecutor()
    scheduler_shared._executors[TaskType.AGENT] = executor
    scheduler_shared.add_task(
        _make_task("t-shared-stop", enabled=True, max_attempts=2,
                   retry_delay_seconds=1, exponential_backoff=False)
    )

    await run_wrapper(scheduler_shared, "t-shared-stop")

    futures = getattr(scheduler_shared, "_pending_retry_futures", None)
    assert futures is not None and len([f for f in futures if not f.done()]) == 1

    holder = getattr(sched_mod, "_retry_loop_holder", None)
    assert holder is not None and "entry" in holder, "常驻重试循环应在 shared 提交时懒启动"
    retry_loop = holder["entry"][0]

    scheduler_shared.stop()

    assert all(f.done() for f in futures), "stop() 后未决重试 future 必须完成（取消）"
    assert await _wait_until(lambda: not futures), "done_callback 必须清空引用集（无悬空 future）"
    assert await _wait_until(lambda: retry_loop.is_closed()), "常驻重试循环必须被 close"
    assert not [t for t in threading.enumerate()
                if t.name == _RETRY_THREAD_NAME and t.is_alive()], "重试循环线程必须已停止"
    assert executor.calls == 1, "第一跳被取消，不得发生第二次执行"


@pytest.mark.asyncio
async def test_shared_drain_waits_full_chain_futures(scheduler_shared):
    """shared：drain_pending_retries 等 `_pending_retry_futures` 整条链收口。

    delay=0：链在常驻循环上快速推进；drain 的快照-重查循环必须等到
    max_attempts 封顶（4 次执行），且引用集最终被 done_callback 清空。
    """
    executor = FailingRetryExecutor()
    scheduler_shared._executors[TaskType.AGENT] = executor
    # 退避 0.05s 起（0.05/0.1/0.2）：须高于 Windows loop.time() 粗粒度
    # （~15.6ms，刻度跳变可使短 sleep 定时器提前到期）——delay=0 会让重试
    # 跳与初始执行的入史顺序随机化，history 顺序断言失去甄别力。
    scheduler_shared.add_task(
        _make_task("t-shared-drain", enabled=True, max_attempts=4,
                   retry_delay_seconds=0.05, exponential_backoff=True)
    )

    await run_wrapper(scheduler_shared, "t-shared-drain")
    await asyncio.wait_for(scheduler_shared.drain_pending_retries(), timeout=5)

    assert executor.calls == 4, "drain 必须等整条链到 max_attempts 封顶"
    history = scheduler_shared.get_execution_history("t-shared-drain")
    assert [e.triggered_by for e in history] == ["scheduler", "retry", "retry", "retry"]
    futures = scheduler_shared._pending_retry_futures
    assert all(f.done() for f in futures)
    assert await _wait_until(lambda: not futures), "done_callback 清空引用集"
    assert scheduler_shared._running_executions == {}
