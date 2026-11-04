"""schedule_task 工具：Agent 必须能自己把「以后按点跑」落成平台调度任务。

判据：
1. 工具已注册且分派体真实存在；
2. create 支持 cron / interval，创建后 next_run_at 已排好、调度线程被拉起；
3. list 只列自己 Agent 的任务；cancel 只取消自己的任务；
4. 没有调度表达式、或想替别的 Agent 建任务 → 明确拒绝。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.collaborate.workflow.scheduler import AgentScheduler
from neurova.tool_executor import ToolExecutor


def _agent(agent_id="agent-x", user_id="u1"):
    return SimpleNamespace(
        _current_user_id=user_id,
        config=SimpleNamespace(agent_id=agent_id, user_id=user_id),
    )


@pytest.fixture
def executor(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "sched.json"))
    AgentScheduler._instance = None
    monkeypatch.setattr(AgentScheduler, "start", lambda self: None)
    yield ToolExecutor(_agent())
    AgentScheduler._instance = None


class TestScheduleTaskRegistration:
    def test_toolIsRegisteredWithCapability(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_capability

        schema = _BUILTIN_SCHEMAS.get("schedule_task")
        assert schema is not None, "schedule_task 未注册：Agent 无法自建定时任务"
        capability = get_builtin_tool_capability("schedule_task")
        assert capability is not None and capability.readOnly is False, (
            "schedule_task 会写共享调度面，必须声明为非只读"
        )

    def test_toolHasDispatchBody(self):
        method = ToolExecutor._builtin_dispatch.get("schedule_task")
        assert method, "schedule_task 有 schema 无执行体，调用必失败"
        assert callable(getattr(ToolExecutor, method, None))


class TestScheduleTaskCreate:
    @pytest.mark.asyncio
    async def test_createIntervalTask(self, executor):
        result = await executor._execute_schedule_task(
            {
                "action": "create",
                "name": "每两小时看广告",
                "interval_seconds": 7200,
                "message": "检查亚马逊广告数据并按收益调整预算",
            }
        )

        assert result["success"] is True
        task = result["task"]
        assert task["next_run_at"] is not None
        assert task["action"] == "send_message"
        assert task["agent_id"] == "agent-x"
        assert task["parameters"]["message"]

    @pytest.mark.asyncio
    async def test_createCronTask(self, executor):
        result = await executor._execute_schedule_task(
            {
                "action": "create",
                "name": "每天九点复盘",
                "cron_expression": "0 9 * * *",
                "message": "生成广告日报",
            }
        )

        assert result["success"] is True
        assert result["task"]["next_run_at"] is not None
        assert result["task"]["cron_expression"] == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_createCanvasTask(self, executor, monkeypatch):
        monkeypatch.setattr(
            "neurova.collaboration.canvas_store.get_canvas_store",
            lambda: SimpleNamespace(
                get=lambda canvas_id, requester_id=None: {
                    "id": canvas_id,
                    "user_id": "default",
                }
            ),
        )
        result = await executor._execute_schedule_task(
            {
                "action": "create",
                "name": "广告调优画布",
                "interval_seconds": 3600,
                "canvas_id": "canvas_abc123",
            }
        )

        assert result["success"] is True
        assert result["task"]["action"] == "run_canvas"
        assert result["task"]["parameters"]["canvas_id"] == "canvas_abc123"

    @pytest.mark.asyncio
    async def test_rejectsSchedulingAnotherUsersCanvas(self, executor, monkeypatch):
        monkeypatch.setattr(
            "neurova.collaboration.canvas_store.get_canvas_store",
            lambda: SimpleNamespace(
                get=lambda canvas_id, requester_id=None: {
                    "id": canvas_id,
                    "user_id": "someone-else",
                }
            ),
        )
        result = await executor._execute_schedule_task(
            {
                "action": "create",
                "name": "别人的画布",
                "interval_seconds": 3600,
                "canvas_id": "canvas_other",
            }
        )

        assert result["success"] is False
        assert "画布" in result["error"]

    @pytest.mark.asyncio
    async def test_rejectsMissingScheduleExpression(self, executor):
        result = await executor._execute_schedule_task(
            {"action": "create", "name": "无排程", "message": "hi"}
        )
        assert result["success"] is False
        assert "cron" in result["error"] or "interval" in result["error"]

    @pytest.mark.asyncio
    async def test_rejectsMissingTarget(self, executor):
        result = await executor._execute_schedule_task(
            {"action": "create", "name": "无目标", "interval_seconds": 60}
        )
        assert result["success"] is False
        assert "message" in result["error"] or "workflow_id" in result["error"] or "canvas_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejectsSchedulingAnotherAgent(self, executor):
        result = await executor._execute_schedule_task(
            {
                "action": "create",
                "name": "替别人建",
                "interval_seconds": 60,
                "message": "hi",
                "agent_id": "other-agent",
            }
        )
        assert result["success"] is False
        assert "agent" in result["error"]


class TestScheduleTaskListAndCancel:
    @pytest.mark.asyncio
    async def test_listOnlyOwnTasks(self, executor):
        from neurova.collaborate.workflow.scheduler import get_scheduler

        await executor._execute_schedule_task(
            {"action": "create", "name": "mine", "interval_seconds": 60, "message": "hi"}
        )
        scheduler = get_scheduler()
        foreign = scheduler.schedule_task(
            name="foreign", action="send_message", agent_id="other-agent",
            interval_seconds=60, parameters={"message": "hi"},
        )

        result = await executor._execute_schedule_task({"action": "list"})

        assert result["success"] is True
        names = {task["name"] for task in result["tasks"]}
        assert "mine" in names
        assert foreign.name not in names

    @pytest.mark.asyncio
    async def test_cancelOwnTask(self, executor):
        created = await executor._execute_schedule_task(
            {"action": "create", "name": "cancel-me", "interval_seconds": 60, "message": "hi"}
        )
        task_id = created["task"]["task_id"]

        result = await executor._execute_schedule_task(
            {"action": "cancel", "task_id": task_id}
        )

        assert result["success"] is True
        assert result["task"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancelForeignTaskRefused(self, executor):
        from neurova.collaborate.workflow.scheduler import get_scheduler

        foreign = get_scheduler().schedule_task(
            name="foreign", action="send_message", agent_id="other-agent",
            interval_seconds=60, parameters={"message": "hi"},
        )

        result = await executor._execute_schedule_task(
            {"action": "cancel", "task_id": foreign.task_id}
        )

        assert result["success"] is False
        assert result["task"]["status"] == "pending"


class TestSchedulerBootstrap:
    def test_ensureStartsOnlyWhenPendingTasksExist(self, tmp_path, monkeypatch):
        from neurova.collaborate.workflow.scheduler import ensure_scheduler_running

        monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "ensure.json"))
        AgentScheduler._instance = None
        scheduler = AgentScheduler()
        started = []
        monkeypatch.setattr(AgentScheduler, "start", lambda self: started.append(True))

        assert ensure_scheduler_running(scheduler) is False
        assert started == []

        scheduler.schedule_task(name="pending", action="send_message", interval_seconds=60)
        assert ensure_scheduler_running(scheduler) is True
        assert started == [True]
        AgentScheduler._instance = None

    def test_runCanvasHandlerCompilesAndExecutes(self, tmp_path, monkeypatch):
        """run_canvas 动作：按 id 取画布快照 → 编译工作流 → 执行引擎。"""
        from neurova.collaborate.workflow.scheduler import AgentScheduler, register_action_handlers

        monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "canvas.json"))
        AgentScheduler._instance = None
        snapshot = {
            "id": "canvas_test",
            "name": "广告调优画布",
            "nodes": [
                {"id": "n1", "type": "builtin:start", "config": {}},
                {"id": "n2", "type": "builtin:end", "config": {}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "n1", "portId": "output"},
                    "target": {"nodeId": "n2", "portId": "input"},
                }
            ],
        }
        fakeStore = SimpleNamespace(get=lambda canvas_id, requester_id=None: snapshot)

        class FakeInstance:
            status = "completed"
            outputs = {"ok": True}
            error = None

        class FakeExecutor:
            def create_instance(self, workflow, inputs=None, user_id=None):
                assert workflow.nodes
                return FakeInstance()

            async def execute(self, workflow, inputs=None, user_id=None, instance=None):
                return instance

        monkeypatch.setattr(
            "neurova.collaboration.canvas_store.get_canvas_store", lambda: fakeStore
        )
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.execution_engine.get_workflow_executor",
            lambda: FakeExecutor(),
        )

        scheduler = AgentScheduler()
        register_action_handlers(scheduler)
        task = scheduler.schedule_task(
            name="canvas-run",
            action="run_canvas",
            parameters={"canvas_id": "canvas_test", "user_id": "u1"},
        )

        scheduler._execute_task(task)

        assert task.status == "completed"
        assert task.last_result["success"] is True
        AgentScheduler._instance = None
