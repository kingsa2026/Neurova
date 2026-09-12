"""B-7 Phase 2 等价性协议 G1（立项 v2 §8.3.3：逐帧一致才判等价）

同一确定性任务集在 legacy / shared 两模式各跑一遍，diff 执行轨迹：
- 事件序列（execution_started/completed × triggered_by × 状态 × 在册标记）
- history 顺序 == 执行顺序
- 重试次数 == max_attempts 封顶
- 退避序列（sleep 参数逐值记录）
- 终态日志（max_attempts 给弃日志 + 每跳 Scheduling retry 日志）
- _running_executions 不跨链（completed 事件时必已摘除，终态为空）

确定性保障：
- 固定序列任务（先失败链、后成功单次）、固定失败注入（executor 按 task.id）
- 退避 sleep 经 fake 记录参数（真实等待压到 0.01s 级，只让跨线程回调推进，
  不影响记录的退避序列）
- 重试链严格串行（单失败任务），跨线程事件追加顺序与 legacy 单线程一致
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple

import pytest

import neurova.agent.scheduler as sched_mod
from neurova.agent.scheduler import (
    AutomationTask,
    RetryPolicy,
    TaskRequest,
    TaskScheduler,
    TaskType,
)

_FAIL_TASK = "eq-fail"
_OK_TASK = "eq-ok"

# 真实让出助手：经线程池执行 OS 级 time.sleep（高分辨率）。
# 不用 asyncio.sleep——Windows 上 loop.time() 粗粒度（~15.6ms）会让短
# sleep 的定时器因时钟刻度跳变提前到期（实测 0.01s sleep 34µs 返回），
# "真实让出"退化为微秒级，重试跳得以在初始执行入史前入史（跨线程
# 入史顺序竞态；生产退避为秒级不受此影响，纯测试装置问题）。
_REAL_TIME_SLEEP = time.sleep


async def _real_yield(seconds: float = 0.01):
    await asyncio.get_running_loop().run_in_executor(None, _REAL_TIME_SLEEP, seconds)



class ScenarioExecutor:
    """按 task.id 注入成败；记录每个任务的执行 start 顺序（执行顺序证据）。"""

    def __init__(self):
        self.start_ids: Dict[str, List[str]] = {}

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        self.start_ids.setdefault(task.id, []).append(execution.id)
        if task.id == _FAIL_TASK:
            return {"success": False, "error": "boom"}
        return {"success": True, "result": "ok"}


async def run_scenario(mode: str, monkeypatch, caplog) -> Dict[str, Any]:
    """跑一遍确定性任务集，返回可 diff 的轨迹快照。"""
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", mode)
    TaskScheduler._instance = None
    scheduler = TaskScheduler()
    executor = ScenarioExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    scheduler.add_task(AutomationTask(
        id=_FAIL_TASK, name="task-eq-fail", type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        retry_policy=RetryPolicy(enabled=True, max_attempts=3,
                                 retry_delay_seconds=1, exponential_backoff=True),
    ))
    scheduler.add_task(AutomationTask(
        id=_OK_TASK, name="task-eq-ok", type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
    ))

    events: List[Tuple[str, str, str, bool]] = []
    scheduler.add_event_handler(lambda et, data: events.append(
        (et, data.triggered_by, data.status.value, data.id in scheduler._running_executions)
    ))

    delays: List[float] = []

    async def fake_sleep(delay):
        delays.append(delay)  # 退避序列 = sleep 参数逐值记录
        await _real_yield()  # 真实短等待：让跨线程回调/调度推进（不改变记录值）

    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    try:
        with caplog.at_level(logging.INFO, logger="neurova.agent.scheduler"):
            await asyncio.wait_for(scheduler.execute_task(_FAIL_TASK), timeout=5)
            await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)
            await asyncio.wait_for(scheduler.execute_task(_OK_TASK), timeout=5)
            await asyncio.wait_for(scheduler.drain_pending_retries(), timeout=5)

        history = {
            task_id: [(e.triggered_by, e.status.value)
                      for e in scheduler.get_execution_history(task_id)]
            for task_id in (_FAIL_TASK, _OK_TASK)
        }
        return {
            "event_seq": events,
            "history": history,
            "exec_order_match": {
                task_id: executor.start_ids[task_id] ==
                          [e.id for e in scheduler.get_execution_history(task_id)]
                for task_id in (_FAIL_TASK, _OK_TASK)
            },
            "fail_calls": len(executor.start_ids[_FAIL_TASK]),
            "ok_calls": len(executor.start_ids[_OK_TASK]),
            "delays": delays,
            "terminal_logs": [r.getMessage() for r in caplog.records
                              if "max_attempts" in r.getMessage()],
            "scheduling_logs": [r.getMessage() for r in caplog.records
                                if "Scheduling retry" in r.getMessage()],
            "running_empty": len(scheduler._running_executions) == 0,
        }
    finally:
        for t in list(scheduler._pending_retry_tasks):
            t.cancel()
        for f in list(getattr(scheduler, "_pending_retry_futures", ())):
            f.cancel()
        sched_mod._shutdown_retry_loop()
        TaskScheduler._instance = None
        monkeypatch.delenv("NEUROVA_SCHEDULER_EXEC_MODE", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "shared"])
async def test_scenario_invariants_hold_per_mode(mode, monkeypatch, caplog):
    """逐模式：任务集的核心不变量各自成立（与跨模式 diff 互为补充）。"""
    snap = await run_scenario(mode, monkeypatch, caplog)

    # 重试次数 == max_attempts 封顶
    assert snap["fail_calls"] == 3
    assert snap["ok_calls"] == 1
    # 退避序列（base=1s 记录值：1 → 2，指数翻倍；真实等待被 fake 压短）
    assert snap["delays"] == [1, 2]
    # history 顺序 == 执行顺序，triggered_by/status 逐条一致
    # （直接调 execute_task 默认 triggered_by="manual"；wrapper 入口才传
    #   "scheduler"——后者由 test_b7_wrapper_characterization.py 钉住）
    assert snap["exec_order_match"] == {_FAIL_TASK: True, _OK_TASK: True}
    assert snap["history"][_FAIL_TASK] == [
        ("manual", "failed"), ("retry", "failed"), ("retry", "failed"),
    ]
    assert snap["history"][_OK_TASK] == [("manual", "success")]
    # 事件序列：4 次执行 × (started, completed)，started 时在册、completed 前摘除
    assert snap["event_seq"] == [
        ("execution_started", "manual", "pending", True),
        ("execution_completed", "manual", "failed", False),
        ("execution_started", "retry", "pending", True),
        ("execution_completed", "retry", "failed", False),
        ("execution_started", "retry", "pending", True),
        ("execution_completed", "retry", "failed", False),
        ("execution_started", "manual", "pending", True),
        ("execution_completed", "manual", "success", False),
    ]
    # 终态日志与每跳退避日志
    assert len(snap["terminal_logs"]) == 1 and "eq-fail" in snap["terminal_logs"][0]
    assert len(snap["scheduling_logs"]) == 2
    # _running_executions 不跨链：终态为空（事件级在册标记见 event_seq）
    assert snap["running_empty"] is True


@pytest.mark.asyncio
async def test_equivalence_legacy_vs_shared(monkeypatch, caplog):
    """G1：同一确定性任务集在两模式各跑一遍，执行轨迹逐帧一致。"""
    legacy_snap = await run_scenario("legacy", monkeypatch, caplog)
    caplog.clear()
    shared_snap = await run_scenario("shared", monkeypatch, caplog)

    if legacy_snap != shared_snap:
        for key in legacy_snap:
            assert legacy_snap[key] == shared_snap[key], (
                f"等价性破缺字段：{key}\nlegacy={legacy_snap[key]!r}\nshared={shared_snap[key]!r}"
            )
    assert legacy_snap == shared_snap
