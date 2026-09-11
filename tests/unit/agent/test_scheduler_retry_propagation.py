"""RES-P1-1 防回归：任务重试计数必须沿重试链透传（docs/资源型Bug扫描报告_2026-09-11.md）

历史缺陷：`_retry_count` 存放在每次执行都新建的 `TaskExecution.metadata` 上，
`execute_task` 重试时新建 execution → metadata 为空 dict → 计数归零：
- `max_attempts` 永不生效，失败任务无限重试（AGENT 任务每轮真烧 LLM token）
- 指数退避恒为 `2**0`
- await 链无限加深，占死 APScheduler ThreadPoolExecutor(10)

契约：
1. 持续失败时总执行次数 ≤ retry_policy.max_attempts
2. 重试退避 delay 随重试次数翻倍（`2 ** _retry_count` 用透传值）
3. 达到 max_attempts 后不再安排重试，并落明确终态日志
4. 退避关闭（exponential_backoff=False）时 delay 恒为 base

注意：所有被测执行包在 asyncio.wait_for 内——旧实现会无限重试，
超时取消即红（挂死本身就是缺陷的活证据）；修复后瞬间完成。
"""

import asyncio
import logging
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

EXECUTE_TIMEOUT = 5  # 修复后毫秒级完成；旧实现无限重试必然超时

# 台账 #7（2026-09-11）：重试链改为独立任务后，execute_task 返回≠重试链
# 结束——断言前必须 drain 未决重试任务（新的收口契约点）。断言本身不变。
async def _execute_and_drain(scheduler, task_id: str, **kwargs):
    execution = await asyncio.wait_for(
        scheduler.execute_task(task_id, **kwargs), timeout=EXECUTE_TIMEOUT
    )
    await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=EXECUTE_TIMEOUT)
    return execution


@pytest.fixture
def scheduler():
    TaskScheduler._instance = None
    s = TaskScheduler()
    yield s
    TaskScheduler._instance = None


class FailingExecutor:
    """始终失败的假执行体——绝不触碰真实 agent.chat / LLM"""

    def __init__(self):
        self.execute_calls = 0

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        self.execute_calls += 1
        return {"success": False, "error": "boom"}


def _make_failing_task(
    task_id: str = "t-retry",
    max_attempts: int = 3,
    retry_delay_seconds: int = 1,
    exponential_backoff: bool = True,
) -> AutomationTask:
    return AutomationTask(
        id=task_id,
        name=f"task-{task_id}",
        type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        retry_policy=RetryPolicy(
            enabled=True,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            exponential_backoff=exponential_backoff,
        ),
    )


@pytest.mark.asyncio
async def test_persistent_failure_bounded_by_max_attempts(scheduler, monkeypatch, caplog):
    """持续失败：总执行次数 == max_attempts，不再无限重试"""
    executor = FailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_failing_task("t-bounded", max_attempts=3))

    async def fake_sleep(_delay):
        pass

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    with caplog.at_level(logging.INFO, logger="neurova.agent.scheduler"):
        await _execute_and_drain(scheduler, "t-bounded")

    assert executor.execute_calls == 3, (
        f"期望总执行次数被 max_attempts=3 封顶，实际 {executor.execute_calls} 次"
        "——重试计数未透传导致无限重试"
    )


@pytest.mark.asyncio
async def test_backoff_delay_doubles_with_retry_count(scheduler, monkeypatch):
    """退避 delay 随重试次数翻倍：base*2**0 → base*2**1 → ..."""
    executor = FailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(_make_failing_task("t-backoff", max_attempts=4, retry_delay_seconds=1))

    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    await _execute_and_drain(scheduler, "t-backoff")

    assert delays == [1, 2, 4], (
        f"期望退避序列 [1, 2, 4]（随次数翻倍），实际 {delays}——退避用了恒为 0 的计数"
    )
    assert executor.execute_calls == 4


@pytest.mark.asyncio
async def test_no_backoff_keeps_constant_delay(scheduler, monkeypatch):
    """exponential_backoff=False 时 delay 恒为 base"""
    executor = FailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(
        _make_failing_task("t-flat", max_attempts=3, retry_delay_seconds=5, exponential_backoff=False)
    )

    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    await _execute_and_drain(scheduler, "t-flat")

    assert delays == [5, 5]
    assert executor.execute_calls == 3


@pytest.mark.asyncio
async def test_max_attempts_terminal_state_logged(scheduler, monkeypatch, caplog):
    """达到 max_attempts 后落明确终态日志且最后一次执行仍为 FAILED"""
    executor = FailingExecutor()
    scheduler._executors[TaskType.AGENT] = executor

    async def fake_sleep(_delay):
        pass

    import neurova.agent.scheduler as sched_mod

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    scheduler.add_task(_make_failing_task("t-terminal", max_attempts=2))

    with caplog.at_level(logging.WARNING, logger="neurova.agent.scheduler"):
        execution = await _execute_and_drain(scheduler, "t-terminal")

    assert execution is not None and execution.status == TaskStatus.FAILED
    assert executor.execute_calls == 2
    terminal_logs = [r for r in caplog.records if "max_attempts" in r.getMessage()]
    assert terminal_logs, "达到 max_attempts 时必须落终态日志（包含 max_attempts 字样）"

    # 台账 #7 修复后：history append 顺序 == 执行顺序（旧 await 链实现为
    # 反序，预存怪癖已消除——此处由集合语义加强为顺序语义）
    history = scheduler.get_execution_history("t-terminal")
    assert len(history) == 2
    assert [e.triggered_by for e in history] == ["manual", "retry"]
