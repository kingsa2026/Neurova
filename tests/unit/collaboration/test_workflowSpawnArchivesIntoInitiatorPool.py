# -*- coding: utf-8 -*-
"""工作流派生的子 Agent 报告，要归档进发起画布那个 Agent 的上下文池（§6-418 仍开②）。

现状：`exec_agent` 调 `swarm.spawn()` 时不传 `initiator_agent`，于是
`SwarmManager._archive_to_pool` 第一行就 return——工作流里的子 Agent 产出进不了任何池，
"写进池 → 后续轮次召回"这条活水对 workflow 路径**从不发生**。

根因不在 `exec_agent` 少传一个参数，而在上游没把发起者身份带进执行上下文：
`_execute_canvas_run` 调 `executor.execute()` 时既不传 `agent_id` 也不传
`context_pool`（同一仓里 REST 链 `neurflow_api` 两者都传，还带了"取不到就建默认池"
的降级），于是 `ResolutionContext.agent_id` 恒为 None——`exec_agent` 想接也接不到人。

归档的读者必须真存在：对话里跑画布的那个 agent，后续轮次会召回自己的池。
trigger／cron／webhook 那几个入口的发起者是系统，没有"下一个会读的人"，
本批**刻意不接**（见台账），所以这里也钉一格"接不上人时不许假装归档成功"。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.mailbox import get_agent_mailbox, reset_agent_mailbox
from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.collaboration.neurflow.builtin import exec_agent
from neurova.collaboration.neurflow.variable_resolver import ResolutionContext

WF_AGENT = "wf_owner_agent"
CHILD_AGENT = "wf_child_researcher"
WF_SESSION = "s-canvas-run"
REPORT_BODY = "工作流子节点产出：三套写入方案逐项比对，结论取 β。"


class _RecordingPool:
    """只记录写入的池替身——被测的是"有没有写进来"，不是池自己的召回实现。"""

    def __init__(self):
        self.added: list = []

    def add_context(self, context=None, *args, **kwargs):
        self.added.append(context if context is not None else args[0])


def _childAgent():
    child = MagicMock()
    child.config.name = "工作流子Agent"
    child.chat = AsyncMock(return_value={"text": REPORT_BODY})
    return child


def _ownerAgent(pool: _RecordingPool):
    return SimpleNamespace(
        config=SimpleNamespace(name="画布发起者", agent_id=WF_AGENT, user_id="u1"),
        context_pool=pool,
        current_user_id="u1",
        owner_user_id="",
    )


def _ctx(agentId=WF_AGENT):
    return {
        "resolution_context": ResolutionContext(
            workflow_id="wf-1",
            execution_id="ex-1",
            agent_id=agentId,
            user_id="u1",
            session_id=WF_SESSION,
        ),
        "node_id": "n-agent",
    }


def _resolveByAgentId(mapping):
    """形参表不手抄：签名的事实源是生产对象 `get_agent_instance`。"""

    def _resolve(*args, **kwargs):
        agent_id = args[0] if args else kwargs.get("agent_id")
        return mapping.get(agent_id)

    return _resolve


@pytest.fixture
def clean():
    reset_swarm_manager()
    reset_agent_mailbox()
    yield
    reset_swarm_manager()
    reset_agent_mailbox()


class TestWorkflowSpawnArchivesIntoInitiatorPool:
    @pytest.mark.asyncio
    async def test_execAgentArchivesTerminalIntoOwningAgentPool(self, clean):
        pool = _RecordingPool()
        mapping = {WF_AGENT: _ownerAgent(pool), CHILD_AGENT: _childAgent()}
        with patch(
            "neurova.api.endpoints.get_agent_instance", side_effect=_resolveByAgentId(mapping)
        ):
            outcome = await exec_agent(
                {"agent_id": CHILD_AGENT, "task": "比对三套写入方案"}, _ctx()
            )

        assert outcome.get("status") == "success", outcome
        assert pool.added, (
            "工作流派生的终态没归档进发起 Agent 的上下文池——§6-418 仍开②的实测形态："
            "`_archive_to_pool` 因 initiator_agent=None 在第一行就返回"
        )
        content = pool.added[0].content
        assert json.loads(content.split("] ", 1)[-1])["origin"] == "workflow"
        assert "结论取 β" not in content, "旁路只给指针，正文不经归档重复搬运"
        assert "swarm_" in content and "recall_history" in content, (
            f"归档内容缺下钻指针，日后无人能取回详情：{content!r}"
        )


class TestCanvasRunCarriesOwningAgentId:
    @pytest.mark.asyncio
    async def testCanvasRunPassesOwningAgentIdIntoExecutor(self):
        """上游漏传身份才是根因：画布执行链要把发起者带进 ResolutionContext。"""
        from neurova import tool_executor as te

        recorder: dict = {}

        class _RecordingExecutor:
            def create_instance(self, workflow, inputs=None, user_id=None, agent_id=None):
                return self._instance()

            async def execute(self, workflow=None, **kwargs):
                recorder["workflow"] = workflow
                recorder.update(kwargs)
                return self._instance()

            @staticmethod
            def _instance():
                return SimpleNamespace(
                    status="completed", node_results={}, outputs={}, error=None, duration=0.1
                )

        executor = te.ToolExecutor.__new__(te.ToolExecutor)
        executor._agent = SimpleNamespace(
            config=SimpleNamespace(name="画布发起者", agent_id=WF_AGENT, user_id="u1"),
            current_session_id=WF_SESSION,
            _current_user_id="u1",
        )

        service = SimpleNamespace(
            read_canvas=lambda **kw: _already_done({"success": True, "name": "调研画布"})
        )
        with patch.object(te, "get_canvas_op_service", lambda: service), patch.object(
            te, "get_workflow_executor", lambda: _RecordingExecutor()
        ), patch(
            "neurova.collaboration.canvas_bridge.canvas_to_workflow",
            lambda record, name=None: SimpleNamespace(id="wf-1", name=name),
        ):
            outcome = await executor._execute_canvas_run({"canvas_id": "c-1"})

        assert outcome.get("success") is True, outcome
        assert recorder.get("agent_id") == WF_AGENT, (
            "canvas_run 没把发起 Agent 带进执行上下文，"
            f"`ResolutionContext.agent_id` 因此恒为 None；实收 {recorder!r}"
        )


async def _already_done(payload):
    return payload


class TestBoundaryUnchanged:
    """反向控制：这一接不许把旁路面放宽，也不许在接不上人时假装成功。今天就该绿。"""

    @pytest.mark.asyncio
    async def testWorkflowSpawnStillDoesNotFillParentMailbox(self, clean):
        """邮箱服务于对话循环的排空点；workflow 没有那个读者，保持不回灌。"""
        pool = _RecordingPool()
        mapping = {WF_AGENT: _ownerAgent(pool), CHILD_AGENT: _childAgent()}
        with patch(
            "neurova.api.endpoints.get_agent_instance", side_effect=_resolveByAgentId(mapping)
        ):
            await exec_agent({"agent_id": CHILD_AGENT, "task": "任务"}, _ctx())

        assert get_agent_mailbox().pending(WF_SESSION) == 0

    @pytest.mark.asyncio
    async def testNoOwningAgentIdArchivesNothingYetReportsSuccess(self, clean):
        """trigger／cron 那类系统发起：接不上人就不归档，但也不谎报失败。"""
        pool = _RecordingPool()
        mapping = {CHILD_AGENT: _childAgent()}
        with patch(
            "neurova.api.endpoints.get_agent_instance", side_effect=_resolveByAgentId(mapping)
        ):
            outcome = await exec_agent(
                {"agent_id": CHILD_AGENT, "task": "任务"}, _ctx(agentId=None)
            )

        assert outcome.get("status") == "success", outcome
        assert pool.added == []
