# -*- coding: utf-8 -*-
"""P2-4 集成核对面 + P2-5 升级闭环 单元测试。

覆盖：
- integrationReport：无挂账 → integration_ready；失败/依赖未满足 → blockers 点名；
- subagent_status 工具 view=integration 返回核对面；
- escalate 工具带 suggested_action/action_note → 升级信封与运行记录携带（P2-5 闭环）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.core import turn_context
from neurova.tool_executor import ToolExecutor


def make_agent(name="子Agent", reply="完成", fail=False):
    agent = MagicMock()
    agent.config.name = name
    if fail:
        agent.chat = AsyncMock(side_effect=RuntimeError("子任务失败"))
    else:
        agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


class TestIntegrationReport:
    @pytest.mark.asyncio
    async def test_empty_swarm_ready(self, swarm):
        report = swarm.integrationReport()
        assert report["integration_ready"] is True
        assert report["blockers"] == []

    @pytest.mark.asyncio
    async def test_failed_subtask_is_blocker(self, swarm):
        agent = make_agent(fail=True)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="会失败的任务", agent_id="researcher")
        assert result["status"] == "failed"
        report = swarm.integrationReport()
        assert report["integration_ready"] is False
        assert any(b["subagent_id"] == result["subagent_id"] for b in report["blockers"])

    @pytest.mark.asyncio
    async def test_completed_subtask_not_blocker(self, swarm):
        agent = make_agent(reply="完成")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="会成功的任务", agent_id="researcher")
        report = swarm.integrationReport()
        assert report["integration_ready"] is True
        assert report["subtasks"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_blocked_dependency_is_blocker(self, swarm):
        depAgent = make_agent(name="前置", reply="前置完成")
        downstream = make_agent(name="下游", reply="下游完成")
        agents = {"dep": depAgent, "researcher": downstream}

        def resolver(agent_id, *args, **kwargs):
            return agents.get(agent_id or "researcher")

        with patch("neurova.api.endpoints.get_agent_instance", side_effect=resolver):
            dep = await swarm.spawn(task="前置任务", agent_id="dep", background=True)
            blocked = await swarm.spawn(
                task="下游任务", agent_id="researcher",
                task_unit={"goal": "g", "dependencies": [dep["subagent_id"]]},
            )
            report = swarm.integrationReport()
            assert report["integration_ready"] is False
            assert any(b["reason"] == "dependencies_unsatisfied"
                       and b["subagent_id"] == blocked["subagent_id"]
                       for b in report["blockers"])

    @pytest.mark.asyncio
    async def test_status_tool_view_integration(self, swarm):
        exe = ToolExecutor(MagicMock())
        report = await exe._execute_subagent_status({"view": "integration"})
        assert "integration_ready" in report
        assert "blockers" in report
        assert "subtasks" in report

    def test_schema_exposes_view(self):
        props = _BUILTIN_SCHEMAS["subagent_status"]["parameters"]["properties"]
        assert "view" in props
        assert set(props["view"]["enum"]) == {"runs", "integration"}


class TestEscalationClosure:
    def test_schema_exposes_suggested_action(self):
        props = _BUILTIN_SCHEMAS["escalate"]["parameters"]["properties"]
        assert "suggested_action" in props
        assert "revise_dependency" in props["suggested_action"]["enum"]
        assert "action_note" in props

    @pytest.mark.asyncio
    async def test_escalate_carries_suggested_action(self, swarm):
        agent = make_agent(name="子Agent")
        exe = ToolExecutor(agent)
        # 子代理上下文：member 会话绑定一条活跃 run
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            spawned = await swarm.spawn(task="子任务", agent_id="researcher", background=True)
        run = swarm.status(spawned["subagent_id"])
        turn_context._session_id_var.set(run["member_session_id"])
        try:
            result = await exe._execute_escalate({
                "reason": "需要决策：接口变更影响下游",
                "suggested_action": "revise_dependency",
                "action_note": "依赖 sub-1 的接口约定需要主代理修订",
            })
        finally:
            turn_context._session_id_var.set(None)
        assert result["success"] is True
        stored = swarm.status(spawned["subagent_id"])
        assert stored["escalation"]["suggested_action"] == "revise_dependency"
        assert stored["escalation"]["action_note"].startswith("依赖")
