# -*- coding: utf-8 -*-
"""P2-10 增强：子代理升级/结构化结果提交（escalate/submit_result）。

- 仅子代理运行内可用（按 member 会话找活跃运行）；
- escalate：运行记录升级 + 升级信封投递发起者会话邮箱；
- submit_result：结构化结果落到运行记录 + 邮箱通知；
- 主代理（非子代理上下文）调用 → 诚实报错。
"""

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.swarm import (
    SUBAGENT_RUNNING,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.core.hooks_engine import reset_hook_engine
from neurova.core.turn_context import set_turn_identity
from neurova.security.approval_manager import ApprovalManager
from neurova.security.governance import GovernancePolicy
from neurova.tool_executor import ToolExecutor

MEMBER_SESSION = "member-s1"
PARENT_SESSION = "parent-s1"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_HOOKS_CONFIG", str(tmp_path / "hooks.json"))
    monkeypatch.setattr(
        "neurova.security.governance.get_governance",
        lambda: GovernancePolicy(ask_on_high=True),
    )
    reset_hook_engine()
    reset_swarm_manager()
    yield tmp_path
    reset_hook_engine()
    reset_swarm_manager()
    set_turn_identity("cleared", None)


def _seedRun(memberSession=MEMBER_SESSION, parentSession=PARENT_SESSION):
    run = SubAgentRun(
        agent_id="child-agent",
        agent_name="子代理",
        task="长任务",
        origin="chat",
        session_id=parentSession,
        member_session_id=memberSession,
    )
    run.status = SUBAGENT_RUNNING
    get_swarm_manager()._runs[run.subagent_id] = run
    return run


@pytest.fixture
def asSubagent():
    set_turn_identity("子任务", MEMBER_SESSION)
    yield
    set_turn_identity("cleared", None)


def _executor():
    return ToolExecutor(SimpleNamespace(_current_user_id="u1", config=SimpleNamespace(agent_id="child-agent")))


class TestSwarmLookup:
    def test_finds_active_run_by_member_session(self):
        run = _seedRun()
        found = get_swarm_manager().getRunByMemberSession(MEMBER_SESSION)
        assert found is not None and found.subagent_id == run.subagent_id

    def test_none_when_not_subagent(self):
        assert get_swarm_manager().getRunByMemberSession("no-such-session") is None


class TestEscalate:
    def test_escalate_records_and_notifies_parent(self, env, asSubagent):
        run = _seedRun()
        result = asyncio.run(
            _executor()._execute_escalate(
                {"reason": "缺 API key", "question": "是否提供测试 key？", "severity": "urgent"}
            )
        )
        assert result["success"] is True and result["escalated"] is True
        assert run.escalation["reason"] == "缺 API key"
        assert run.escalation["severity"] == "urgent"
        # 升级信封投递到发起者（父）会话邮箱
        from neurova.agent.mailbox import get_agent_mailbox

        mailbox = get_agent_mailbox().drain(PARENT_SESSION)
        assert any("子Agent升级" in m and "缺 API key" in m for m in mailbox)

    def test_escalate_requires_reason(self, env, asSubagent):
        result = asyncio.run(_executor()._execute_escalate({}))
        assert result["success"] is False and "reason" in result["error"]

    def test_main_agent_cannot_escalate(self, env):
        # 主代理上下文（turn session 不是任何 member 会话）→ 诚实报错
        result = asyncio.run(_executor()._execute_escalate({"reason": "x"}))
        assert result["success"] is False
        assert "仅子代理" in result["error"]


class TestSubmitResult:
    def test_submit_result_records_and_notifies(self, env, asSubagent):
        run = _seedRun()
        result = asyncio.run(
            _executor()._execute_submit_result(
                {"summary": "已完成数据迁移，剩余 2 项待确认", "status": "partial"}
            )
        )
        assert result["success"] is True and result["submitted"] is True
        assert run.submitted_result["status"] == "partial"
        assert run.report == "已完成数据迁移，剩余 2 项待确认"
        from neurova.agent.mailbox import get_agent_mailbox

        mailbox = get_agent_mailbox().drain(PARENT_SESSION)
        assert any("子Agent结果" in m and "partial" in m for m in mailbox)

    def test_submit_result_requires_summary(self, env, asSubagent):
        result = asyncio.run(_executor()._execute_submit_result({"status": "success"}))
        assert result["success"] is False and "summary" in result["error"]

    def test_invalid_status_falls_back_to_success(self, env, asSubagent):
        _seedRun()
        result = asyncio.run(
            _executor()._execute_submit_result({"summary": "s", "status": "bogus"})
        )
        assert result["status"] == "success"
