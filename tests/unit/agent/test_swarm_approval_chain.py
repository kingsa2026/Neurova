# -*- coding: utf-8 -*-
"""P3-1 跨 agent 审批链单元测试（评测报告 G-11）。

覆盖：
- 危险分级：normalizeLevel / classifyActionLevel（声明只升不降，L2 不可降）；
- L0 低危自动放行 + 记账（不等待、不投箱）；
- 声明 L0 但动作命中危险命令检测 → 升档 L1（interactive 下转待审）；
- L1 interactive：审批单进既有 ApprovalManager（单源）+ 父会话邮箱信封，
  父代理裁决经 approval_relay 唤醒等待中的子代理（批准/拒绝两路）；
- L1 auto_approve 模式自动放行；L2 任何模式强制人工（auto_approve 也不放行）；
- 等待超时：诚实 approval_timeout，审批单保留（与工具 ASK 同语义）；
- decideSwarmApproval 只认蜂群审批单、已裁决幂等失败；
- member 工具面收窄：request_approval 可用、decide_subagent_approval 被剔除；
- run.approvals 记录进 to_dict。
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.approval_chain import (
    approvalMode,
    classifyActionLevel,
    decideSwarmApproval,
    normalizeLevel,
    requestRunApproval,
)
from neurova.agent.swarm import SubAgentRun, computeSubagentToolAllowlist, reset_swarm_manager
from neurova.security.approval_manager import ApprovalManager, ApprovalStatus
from neurova.security.approval_relay import installApprovalRelay


@pytest.fixture
def swarmRun():
    reset_swarm_manager()
    return SubAgentRun(
        agent_id="child", agent_name="子代理", task="整理季度数据",
        session_id="parent-session", origin="chat", member_session_id="swarm_member_test",
    )


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    """真 ApprovalManager（临时数据根）+ 接上中继；patch 单源工厂入口。

    等待预算统一给安全默认（防未裁决用例落进 300s 生产默认挂死测试）；
    需要更短/更长预算的用例自行 setenv 覆盖。
    """
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "3")
    mgr = ApprovalManager(str(tmp_path / "approval_ws"))
    assert installApprovalRelay(mgr) is True
    with patch("neurova.security.approval_manager.get_approval_manager", return_value=mgr):
        yield mgr


@pytest.fixture
def parentMail():
    box = MagicMock()
    with patch("neurova.agent.mailbox.get_agent_mailbox", return_value=box):
        yield box


class TestGrading:
    def test_normalize_level_accepts_case_only(self):
        assert normalizeLevel("l0") == "L0"
        assert normalizeLevel(" L1 ") == "L1"
        assert normalizeLevel("L2") == "L2"
        with pytest.raises(ValueError):
            normalizeLevel("L9")
        with pytest.raises(ValueError):
            normalizeLevel("")

    def test_declared_l0_dangerous_action_bumps_to_l1(self):
        assert classifyActionLevel("读取只读配置文件", "L0") == "L0"
        assert classifyActionLevel("rm -rf /tmp/legacy_cache", "L0") == "L1"
        # L2 不可逆：声明即生效，不因检测器而降档
        assert classifyActionLevel("rm -rf /tmp/legacy_cache", "L2") == "L2"

    def test_mode_default_interactive(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        assert approvalMode() == "interactive"

    def test_mode_auto_approve(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_MODE", "auto_approve")
        assert approvalMode() == "auto_approve"


class TestRequestFlow:
    @pytest.mark.asyncio
    async def test_l0_auto_approves_and_records(self, swarmRun, approvals, parentMail, monkeypatch):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        result = await requestRunApproval(swarmRun, "读取只读配置", reason="需要库表结构", level="L0")
        assert result["approved"] is True
        assert result["auto_approved"] is True
        assert result["level"] == "L0"
        req = approvals.get_request(result["request_id"])
        assert req.status == ApprovalStatus.APPROVED
        assert req.metadata["source"] == "swarm"
        assert swarmRun.approvals[0]["request_id"] == result["request_id"]
        parentMail.push.assert_not_called()  # L0 不打扰父代理

    @pytest.mark.asyncio
    async def test_declared_l0_dangerous_goes_pending_with_parent_mail(
        self, swarmRun, approvals, parentMail, monkeypatch
    ):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "0.2")
        result = await requestRunApproval(swarmRun, "rm -rf /tmp/legacy_cache", level="L0")
        assert result["approved"] is False
        assert result["pending"] is True
        req = approvals.get_request(result["request_id"])
        assert req.status == ApprovalStatus.PENDING
        assert req.metadata["effective_level"] == "L1"
        assert req.metadata["declared_level"] == "L0"
        # 父会话邮箱收到审批信封（含 request_id 与裁决入口提示）
        assert parentMail.push.call_count == 1
        mailText = parentMail.push.call_args[0][1]
        assert result["request_id"] in mailText
        assert "decide_subagent_approval" in mailText

    @pytest.mark.asyncio
    async def test_l1_interactive_parent_approval_wakes_waiter(
        self, swarmRun, approvals, parentMail, monkeypatch
    ):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "5")
        task = asyncio.create_task(requestRunApproval(swarmRun, "导出审计日志", level="L1"))
        await asyncio.sleep(0.05)
        pending = approvals.get_pending_requests()
        assert len(pending) == 1
        assert approvals.approve_request(pending[0].request_id, approved_by="parent_agent")
        result = await task
        assert result["approved"] is True
        assert result["decided_by"] == "parent_agent"
        assert result["pending"] is False

    @pytest.mark.asyncio
    async def test_l1_interactive_parent_rejection_denies(
        self, swarmRun, approvals, parentMail, monkeypatch
    ):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "5")
        task = asyncio.create_task(requestRunApproval(swarmRun, "批量外发邮件", level="L1"))
        await asyncio.sleep(0.05)
        pending = approvals.get_pending_requests()
        assert len(pending) == 1
        assert approvals.reject_request(pending[0].request_id, rejected_by="parent_agent", note="风险大")
        result = await task
        assert result["approved"] is False
        assert result["denied"] is True
        assert result["status"] == "rejected"
        assert result["note"] == "风险大"

    @pytest.mark.asyncio
    async def test_l1_auto_mode_auto_approves(self, swarmRun, approvals, parentMail, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_MODE", "auto_approve")
        result = await requestRunApproval(swarmRun, "读取内部接口列表", level="L1")
        assert result["approved"] is True
        assert result["auto_approved"] is True
        parentMail.push.assert_not_called()

    @pytest.mark.asyncio
    async def test_l2_forces_human_even_in_auto_mode(
        self, swarmRun, approvals, parentMail, monkeypatch
    ):
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_MODE", "auto_approve")
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "5")
        task = asyncio.create_task(requestRunApproval(swarmRun, "删除生产数据库表", level="L2"))
        await asyncio.sleep(0.05)
        pending = approvals.get_pending_requests()
        assert len(pending) == 1, "L2 不可逆操作在 auto_approve 模式下也不得自动放行"
        # 用户（管理员）经治理面裁决——同一条 ApprovalManager 通路唤醒等待方
        assert approvals.approve_request(pending[0].request_id, approved_by="admin_user")
        result = await task
        assert result["approved"] is True
        assert result["decided_by"] == "admin_user"
        assert result["auto_approved"] is False

    @pytest.mark.asyncio
    async def test_wait_timeout_reports_honestly_and_keeps_request(
        self, swarmRun, approvals, parentMail, monkeypatch
    ):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "0.2")
        result = await requestRunApproval(swarmRun, "修改共享凭据", level="L1")
        assert result["approved"] is False
        assert result.get("approval_timeout") is True
        assert result["pending"] is True
        # 审批单保留（人工稍后仍可裁决），不是悄悄消失
        assert approvals.get_request(result["request_id"]).status == ApprovalStatus.PENDING

    @pytest.mark.asyncio
    async def test_invalid_level_rejected(self, swarmRun, approvals, monkeypatch):
        with pytest.raises(ValueError):
            await requestRunApproval(swarmRun, "任意操作", level="L9")

    @pytest.mark.asyncio
    async def test_empty_action_rejected(self, swarmRun, approvals, monkeypatch):
        with pytest.raises(ValueError):
            await requestRunApproval(swarmRun, "  ", level="L0")


class TestDecide:
    @pytest.mark.asyncio
    async def test_decide_rejects_non_swarm_request(self, swarmRun, approvals):
        foreign = approvals.create_approval_request(agent_id="a1", user_id="u1", command="curl x")
        result = decideSwarmApproval(foreign.request_id, "approve")
        assert result["success"] is False
        assert "蜂群" in result["error"]

    @pytest.mark.asyncio
    async def test_decide_approve_then_idempotent_failure(
        self, swarmRun, approvals, parentMail, monkeypatch
    ):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "5")
        task = asyncio.create_task(requestRunApproval(swarmRun, "导入客户名单", level="L1"))
        await asyncio.sleep(0.05)
        rid = approvals.get_pending_requests()[0].request_id
        first = decideSwarmApproval(rid, "approve", note="同意导入")
        assert first["success"] is True
        assert first["status"] == "approved"
        second = decideSwarmApproval(rid, "approve")
        assert second["success"] is False, "已裁决的审批单必须幂等失败，不重复受理"
        result = await task
        assert result["approved"] is True
        assert result["note"] == "同意导入"

    def test_decide_validates_params(self, approvals):
        assert decideSwarmApproval("", "approve")["success"] is False
        assert decideSwarmApproval("whatever", "maybe")["success"] is False


class TestWiring:
    def test_member_allowlist_keeps_request_blocks_decide(self):
        allow = computeSubagentToolAllowlist("general")
        assert "request_approval" in allow
        assert "decide_subagent_approval" not in allow, \
            "子代理不得裁决审批单（自己批自己=审批链失效）"

    @pytest.mark.asyncio
    async def test_run_to_dict_carries_approvals(self, swarmRun, approvals, monkeypatch):
        monkeypatch.delenv("NEUROVA_SWARM_APPROVAL_MODE", raising=False)
        await requestRunApproval(swarmRun, "读取只读配置", level="L0")
        data = swarmRun.to_dict()
        assert data["approvals"], "审批记录必须进 run 投影（可观测）"
        assert data["approvals"][0]["effective_level"] == "L0"
        assert data["approvals"][0]["status"] == "approved"
