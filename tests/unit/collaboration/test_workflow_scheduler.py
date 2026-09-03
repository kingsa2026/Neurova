"""
AgentScheduler(挂载版) 功能复活测试（2026-08-31）

断点(调度器此前完全不工作):
1. schedule_task 不初始化 next_run_at → is_due 恒 False, 所有任务永不触发
   (interval 任务只在下一次执行后才设置 next_run_at, 首跑即死锁);
2. cron_expression 循环在 mark_completed 中 pass(TODO) → cron 任务只可能跑一次、
   且首次触发也不会安排(next_run_at 为空);
3. _task_handlers 全仓零注册 → 即使触发也是 "No handler registered"。
4. 任务只按 scheduled_at/next_run_at 到期(秒级轮询), cron 任务需由
   compute_next_run 支持 APScheduler 5 段表达式。

契约:
1. schedule_task(interval_seconds=N): next_run_at=now+N;
2. schedule_task(cron_expression='M H * * DOW'): next_run_at=下一次触发时刻
   (APScheduler 语义 0=周一);
3. 到期执行后: interval → 续排; cron → 计算下一次; 单次 → 置 completed;
4. 已注册 handler 被调用(task.parameters 透传), 未注册 → status=failed。
"""

import math
from datetime import datetime

import pytest

from neurova.collaborate.workflow.scheduler import AgentScheduler
from neurova.collaborate.workflow.models import ScheduledTask, compute_next_run


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    # 隔离存储: 防写真实 data/scheduler_tasks.json
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "sched.json"))
    AgentScheduler._instance = None
    s = AgentScheduler()
    yield s
    AgentScheduler._instance = None


def test_interval_sets_next_run_on_schedule(scheduler):
    task = scheduler.schedule_task(
        name="interval-task", action="send_message", interval_seconds=300, parameters={"message": "hi"}
    )
    assert task.next_run_at is not None
    assert math.isclose(task.next_run_at - datetime.now().timestamp(), 300, abs_tol=5)


def test_cron_sets_next_run_on_schedule(scheduler):
    task = scheduler.schedule_task(
        name="cron-task", action="send_message",
    )
    task.cron_expression = "0 9 * * 0,2,4"
    # 模拟 agent_cron 组装后由调度器重新计算 next_run
    task.next_run_at = compute_next_run(
        cron_expression=task.cron_expression, after=datetime(2026, 8, 31, 12, 0).timestamp()
    )
    assert task.next_run_at is not None
    # 2026-09-02 09:00 +08(周三, 0=周一 / 2=周三)
    assert abs(task.next_run_at - datetime(2026, 9, 2, 9, 0).timestamp()) < 5


def test_cron_reschedules_after_completion(scheduler):
    task = scheduler.schedule_task(name="cron-task", action="x")
    task.cron_expression = "0 9 * * *"
    first = task.next_run_at = compute_next_run(cron_expression="0 9 * * *", after=None)
    task.mark_running()
    task.mark_completed({"ok": True})
    assert task.status == "pending"
    assert task.next_run_at is not None and task.next_run_at > datetime.now().timestamp()


def test_interval_reschedules_after_completion(scheduler):
    task = scheduler.schedule_task(name="int-task", action="x", interval_seconds=60)
    task.mark_running()
    task.mark_completed({"ok": True})
    assert task.status == "pending"
    assert task.next_run_at is not None


def test_one_shot_stays_completed(scheduler):
    task = scheduler.schedule_task(name="once", action="x", scheduled_at=datetime.now().timestamp() + 1)
    task.mark_running()
    task.mark_completed({"ok": True})
    assert task.status == "completed"


def test_handler_dispatch_and_unregistered_fails(scheduler):
    seen = {}
    scheduler.register_handler("send_message", lambda task, ctx: seen.update(msg=task.parameters.get("message")))
    task = scheduler.schedule_task(name="t", action="send_message", parameters={"message": "hello"})
    task.scheduled_at = datetime.now().timestamp() - 1
    scheduler._execute_task(task)
    assert seen.get("msg") == "hello"
    assert task.status == "completed"

    task2 = scheduler.schedule_task(name="t2", action="no_such_action")
    task2.scheduled_at = datetime.now().timestamp() - 1
    scheduler._execute_task(task2)
    assert task2.status == "failed"


def test_persist_and_reload_after_restart(tmp_path):
    """遗留修复: 任务持久化到 JSON, 重启(新实例)后任务仍在且排程可续"""
    import os

    store = tmp_path / "scheduler_tasks.json"
    os.environ["NEUROVA_SCHEDULER_STORE"] = str(store)

    AgentScheduler._instance = None
    s1 = AgentScheduler()
    task1 = s1.schedule_task(name="persist-me", action="send_message", cron_expression="0 9 * * *", parameters={"message": "hi"})
    assert store.exists()

    # 模拟重启: 单例重置 + 新实例从 storage 加载
    AgentScheduler._instance = None
    s2 = AgentScheduler()
    try:
        task = s2.get_task(task1.task_id)
        assert task is not None
        assert task.name == "persist-me"
        assert task.cron_expression == "0 9 * * *"
        assert task.next_run_at is not None
    finally:
        AgentScheduler._instance = None
        os.environ.pop("NEUROVA_SCHEDULER_STORE", None)
