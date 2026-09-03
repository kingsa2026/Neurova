"""
P1 调度器修复测试（2026-08 代码审计）

覆盖 bug:
1. AgentTaskExecutor.execute 中 agent.chat() 缺 await → 定时任务从不真正执行
2. AgentTaskExecutor.execute 导入不存在的 neurova.api.app.app_state → ImportError
3. update_task/disable_task/delete_task 用 `task_id in get_jobs()` 比较 str 与 Job 对象
   → 恒 False，APSchedulder 任务永不移除，禁用/删除的任务继续触发
4. delete_task 中 `del self._executions[task_id]` 对未初始化键抛 KeyError 导致删除中断
5. _check_dependencies 遍历的是依赖图的下游（dependents）而非上游依赖，
   且用 execution id 键匹配 task id → 依赖门控完全失效
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.scheduler import (
    AgentTaskExecutor,
    AutomationTask,
    TaskDependency,
    TaskExecution,
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
    TaskScheduler._instance = None


def _make_task(task_id: str, dependencies=None, enabled=True) -> AutomationTask:
    return AutomationTask(
        id=task_id,
        name=f"task-{task_id}",
        type=TaskType.AGENT,
        enabled=enabled,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        dependencies=dependencies or [],
    )


def _make_execution(exec_id: str, task_id: str, status: TaskStatus) -> TaskExecution:
    return TaskExecution(id=exec_id, task_id=task_id, status=status)


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def chat(self, message, stream=False):
        self.calls.append(message)
        return f"reply to {message}"


# ── 1+2. AgentTaskExecutor 真正 await agent.chat ────────


class TestAgentTaskExecutor:
    @pytest.mark.asyncio
    async def test_execute_awaits_agent_chat(self, monkeypatch):
        agent = FakeAgent()
        fake_state = SimpleNamespace(agents={"a1": agent}, default_agent=None)
        import neurova.api.app as app_module

        monkeypatch.setattr(app_module, "_app_state", fake_state)

        executor = AgentTaskExecutor()
        task = _make_task("t1")
        execution = _make_execution("e1", "t1", TaskStatus.RUNNING)

        result = await executor.execute(task, execution)

        assert agent.calls == ["hi"], "agent.chat 未被实际调用（缺 await 或导入错误）"
        assert result["success"] is True
        assert result["result"] == "reply to hi"

    @pytest.mark.asyncio
    async def test_execute_agent_not_found(self, monkeypatch):
        fake_state = SimpleNamespace(agents={}, default_agent=None)
        import neurova.api.app as app_module

        monkeypatch.setattr(app_module, "_app_state", fake_state)

        executor = AgentTaskExecutor()
        task = _make_task("t1")
        execution = _make_execution("e1", "t1", TaskStatus.RUNNING)

        result = await executor.execute(task, execution)
        assert result["success"] is False


# ── 3. 禁用/删除/更新任务必须移除 APScheduler job ──────


class TestSchedulerJobRemoval:
    def _mock_apscheduler(self, existing_job_ids):
        ap = MagicMock()
        jobs = {jid: MagicMock(id=jid) for jid in existing_job_ids}
        ap.get_job.side_effect = lambda jid: jobs.get(jid)
        ap.get_jobs.return_value = list(jobs.values())

        def remove_job(jid):
            jobs.pop(jid, None)

        ap.remove_job.side_effect = remove_job
        return ap

    def test_delete_task_removes_scheduler_job(self, scheduler):
        scheduler._apscheduler = self._mock_apscheduler({"t1"})
        scheduler.add_task(_make_task("t1"))

        assert scheduler.delete_task("t1") is True
        scheduler._apscheduler.remove_job.assert_called_once_with("t1")
        assert scheduler._apscheduler.get_job("t1") is None

    def test_disable_task_removes_scheduler_job(self, scheduler):
        scheduler._apscheduler = self._mock_apscheduler({"t1"})
        scheduler.add_task(_make_task("t1"))

        task = scheduler.disable_task("t1")
        assert task is not None and task.enabled is False
        scheduler._apscheduler.remove_job.assert_called_once_with("t1")
        assert scheduler._apscheduler.get_job("t1") is None

    def test_update_task_removes_old_scheduler_job(self, scheduler):
        scheduler._apscheduler = self._mock_apscheduler({"t1"})
        scheduler.add_task(_make_task("t1"))

        updated = scheduler.update_task("t1", {"name": "renamed"})
        assert updated is not None
        assert scheduler._apscheduler.get_job("t1") is None or updated.schedule is None


# ── 4. delete_task 对从未执行过的任务也应成功 ──────────


class TestDeleteTaskRobustness:
    def test_delete_never_executed_task(self, scheduler):
        scheduler.add_task(_make_task("t1"))
        scheduler._executions.pop("t1", None)  # 模拟无执行记录

        assert scheduler.delete_task("t1") is True
        assert "t1" not in scheduler._tasks


# ── 5. _check_dependencies 必须检查上游依赖 ────────────


class TestCheckDependencies:
    def test_blocks_when_upstream_dependency_running(self, scheduler):
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=[TaskDependency(task_id="A")]))

        scheduler._running_executions["exec-A"] = _make_execution("exec-A", "A", TaskStatus.RUNNING)

        assert scheduler._check_dependencies("B") is False, "上游依赖正在运行时不应放行下游任务"

    def test_blocks_when_upstream_dependency_failed(self, scheduler):
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=[TaskDependency(task_id="A")]))

        scheduler._executions["A"] = [_make_execution("exec-A", "A", TaskStatus.FAILED)]

        assert scheduler._check_dependencies("B") is False, "上游依赖最近执行失败时不应放行下游任务"

    def test_allows_when_upstream_dependency_succeeded(self, scheduler):
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=[TaskDependency(task_id="A")]))

        scheduler._executions["A"] = [_make_execution("exec-A", "A", TaskStatus.SUCCESS)]

        assert scheduler._check_dependencies("B") is True

    def test_allows_task_without_dependencies(self, scheduler):
        scheduler.add_task(_make_task("A"))
        assert scheduler._check_dependencies("A") is True
