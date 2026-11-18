# -*- coding: utf-8 -*-
"""H-2 机械完成闸门单元测试（对照评测改进项）。

语义（对齐参照系完成闸门，但按本仓"发现而不裁决"落地）：
- 后台工作未清（活跃子代理 run / 未回灌邮箱件）时，主出口的"完成"不得静默
  通过：出口决定带等待事实（reason），通知落会话盘留痕；**不续跑模型**（防忙等）；
- 与目标门无关——无目标也核账；
- 蜂群不可用 fail-open：核账失败不阻断出口。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.loops.base import LOOP_DONE, LoopExitDecision, evaluateLoopExit
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SwarmManager,
    get_swarm_manager,
    reset_swarm_manager,
)


@pytest.fixture()
def swarm():
    from neurova.agent.mailbox import reset_agent_mailbox

    reset_swarm_manager()
    reset_agent_mailbox()
    yield get_swarm_manager()
    reset_swarm_manager()
    reset_agent_mailbox()


def _seedRun(swarm, subagentId, sessionId, status=SUBAGENT_RUNNING):
    from neurova.agent.swarm import SubAgentRun

    run = SubAgentRun(subagent_id=subagentId, agent_id="child", agent_name="子",
                      task="后台任务", session_id=sessionId, status=status)
    with swarm._lock:
        swarm._runs[subagentId] = run
    return run


class TestPendingBackgroundAssessment:
    def test_active_run_for_session_is_pending(self, swarm):
        _seedRun(swarm, "swarm_a", "s-parent")
        result = swarm.pendingBackgroundForSession("s-parent")
        assert result["pending"] is True
        assert result["active"][0]["subagent_id"] == "swarm_a"

    def test_finished_and_foreign_runs_not_pending(self, swarm):
        _seedRun(swarm, "swarm_done", "s-parent", status=SUBAGENT_COMPLETED)
        _seedRun(swarm, "swarm_other", "s-other")
        assert swarm.pendingBackgroundForSession("s-parent")["pending"] is False
        assert swarm.pendingBackgroundForSession("s-other")["pending"] is True

    def test_mailbox_pending_counts(self, swarm):
        from neurova.agent.mailbox import get_agent_mailbox

        get_agent_mailbox().push("s-parent", "[子Agent终态] x")
        result = swarm.pendingBackgroundForSession("s-parent")
        assert result["mailbox_pending"] == 1
        assert result["pending"] is True

    def test_empty_session_safe(self, swarm):
        assert swarm.pendingBackgroundForSession("")["pending"] is False
        assert swarm.pendingBackgroundForSession(None)["pending"] is False


def _fakeLoop(sessionId="s-parent"):
    return SimpleNamespace(
        agent=SimpleNamespace(current_session_id=sessionId),
        resolveTurnGoal=lambda: None,
    )


class TestMainExitGate:
    @pytest.mark.asyncio
    async def test_exit_carries_waiting_notice_when_background_pending(self, swarm):
        _seedRun(swarm, "swarm_a", "s-parent")
        announced = []
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm), \
             patch("neurova.agent.loops.base.persistModelVisibleAnnouncement",
                   side_effect=lambda agent, text, source: announced.append((text, source))):
            decision = await evaluateLoopExit(_fakeLoop(), reply="全部完成",
                                              roundUsage=None, toolRound=1)
        assert decision.action == LOOP_DONE, "发现而不裁决：不续跑模型（防忙等），照常收口"
        assert decision.gate_name == "background_work"
        assert "1 个子代理仍在运行" in decision.reason
        assert announced and announced[0][1] == "completion_gate", "等待事实须落会话盘留痕"

    @pytest.mark.asyncio
    async def test_exit_plain_when_nothing_pending(self, swarm):
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            decision = await evaluateLoopExit(_fakeLoop(), reply="完成",
                                              roundUsage=None, toolRound=1)
        assert decision.action == LOOP_DONE
        assert decision.reason == "" and decision.gate_name == ""

    @pytest.mark.asyncio
    async def test_mailbox_backlog_alone_triggers_notice(self, swarm):
        from neurova.agent.mailbox import get_agent_mailbox

        get_agent_mailbox().push("s-parent", "[子Agent终态] x")
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            decision = await evaluateLoopExit(_fakeLoop(), reply="完成",
                                              roundUsage=None, toolRound=1)
        assert "待回灌" in decision.reason

    @pytest.mark.asyncio
    async def test_fail_open_when_swarm_unavailable(self):
        with patch("neurova.agent.swarm.get_swarm_manager",
                   side_effect=RuntimeError("registry down")):
            decision = await evaluateLoopExit(_fakeLoop(), reply="完成",
                                              roundUsage=None, toolRound=1)
        assert decision.action == LOOP_DONE and decision.reason == ""
