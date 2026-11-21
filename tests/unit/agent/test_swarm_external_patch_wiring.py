# -*- coding: utf-8 -*-
"""P2-2 待办清偿：swarm 外部成员补丁 → 演化提案通道的实际接线。

计划书 §6 P2 批 P2-2：swarm 外部成员产出 → propose_pr_patch 入提案通道
（沙箱校验 + 双 gate 不变）。桥（submitExternalPatch）已交付，本套件钉住
``_run_member`` 候选合入成功段到桥的接线：

- 外部成员（_externalAdapters 在册）合入成功 + 任务书 artifactOwnership
  指名仓库路径 → submitExternalPatch 提案入账（PENDING、metadata 带 lineage）；
- 提案通道任何异常（拒绝/503/校验失败）只记 external_patch_proposal_failed
  事件留痕——不影响候选合入与 run 结算（主链不受影响）；
- 内部（非外部）成员不触发；未指名仓库路径目标不触发。

隔离纪律：proposer 台账落 tmp；外部适配器为桩（不真跑外部进程）；
合入走真实 spawn → _run_member 主链。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager

#: 首批 L2 白名单对象之一（与 test_externalCandidateBridge 同一目标）。
TARGET_FILE = "neurova/context/rules_sections.py"
PATCH = (
    "--- a/neurova/context/rules_sections.py\n"
    "+++ b/neurova/context/rules_sections.py\n"
    "@@ -1 +1,2 @@\n"
    " value = 1\n"
    "+evolved = True\n"
)


def makeExternalAdapter(report: str = PATCH):
    """外部编码成员桩：chat 返回 unified diff 正文（不启动任何外部进程）。

    close 须为协程——run 终态释放适配器走 asyncio.create_task(close())。
    """
    adapter = MagicMock()
    adapter.config.name = "外部编码代理"
    adapter.chat = AsyncMock(return_value={"text": report})
    adapter.close = AsyncMock(return_value=None)
    return adapter


def makeHostAgent(proposer):
    """宿主 agent 桩：RSI 提案通道挂在 rsi_orchestrator.self_improvement_proposer。"""
    return SimpleNamespace(
        agent_id="host-kai",
        owner_user_id="user-a",
        rsi_orchestrator=SimpleNamespace(self_improvement_proposer=proposer),
    )


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


@pytest.fixture
def proposer(tmp_path):
    from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
    from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
    from neurova.evolution.rsi.self_improvement_proposer import SelfImprovementProposer
    from neurova.skill_system import SkillRegistry
    from neurova.skills.skill_service import SkillService

    return SelfImprovementProposer(
        agent_id="host-kai",
        proposals_dir=tmp_path / "ledger",
        deployment_controller=RSIDeploymentController(initial_phase=4),
        rollback_manager=RSIRollbackManager(),
        skill_service=SkillService("host-kai", skills_dir=str(tmp_path / "agent-skills")),
        skill_registry=SkillRegistry(),
    )


def wireExternalMember(monkeypatch, swarm, adapter):
    """名册解析桩：agent_id 点名的成员一律解析为外部适配器（跳过进程启动）。"""
    monkeypatch.setattr(swarm, "_resolveExternalMember", lambda mid, tid: (adapter, None))


def captureEvents(monkeypatch, swarm):
    """包裹 _logRunEvent 捕获事件流（原逻辑照常执行）。"""
    events = []
    original = swarm._logRunEvent

    def spy(run, eventType, payload=None):
        events.append({"type": eventType, "payload": dict(payload or {})})
        return original(run, eventType, payload)

    monkeypatch.setattr(swarm, "_logRunEvent", spy)
    return events


class TestExternalPatchWiring:
    @pytest.mark.asyncio
    async def test_externalMemberMergeCreatesPendingProposalWithLineage(
            self, swarm, proposer, monkeypatch):
        """主判据：外部成员合入成功 → 补丁入演化提案通道（PENDING + lineage）。"""
        wireExternalMember(monkeypatch, swarm, makeExternalAdapter())
        initiator = makeHostAgent(proposer)
        events = captureEvents(monkeypatch, swarm)

        result = await swarm.spawn(
            task="演进 rules_sections 编译器",
            agent_id="ext-1",
            initiator_agent=initiator,
            task_unit={"goal": "g", "artifactOwnership": TARGET_FILE},
        )

        assert result["status"] == "completed", result
        pending = [p for p in proposer._proposals_cache.values()
                   if p.target == TARGET_FILE]
        assert len(pending) == 1, "外部成员合入成功的补丁必须生成一条演化提案"
        proposal = pending[0]
        assert proposal.status.value == "pending"
        assert proposal.content == PATCH
        # 来源 lineage：谁（宿主通道）在哪个 run 产出、租户随行
        assert proposal.metadata["source"] == "neuacp_external"
        assert proposal.metadata["agent_id"] == "host-kai"
        assert proposal.metadata["run_id"] == result["subagent_id"]
        run = swarm._runs[result["subagent_id"]]
        assert proposal.metadata["run_context"]["tenantId"] == run.tenant_id
        # 闭环留痕：提案提交成功也有事件（不只失败才留痕）
        proposed = [e for e in events if e["type"] == "external_patch_proposed"]
        assert proposed and proposed[0]["payload"]["proposal_id"] == proposal.proposal_id
        assert proposed[0]["payload"]["target_file"] == TARGET_FILE

    @pytest.mark.asyncio
    async def test_proposalChannelRejectionLeavesMainChainIntactAndLogsEvent(
            self, swarm, proposer, monkeypatch):
        """提案通道拒绝（禁改内核预检）→ 主链不受影响、失败事件留痕。"""
        wireExternalMember(monkeypatch, swarm, makeExternalAdapter())
        initiator = makeHostAgent(proposer)
        events = captureEvents(monkeypatch, swarm)

        result = await swarm.spawn(
            task="试图改内核",
            agent_id="ext-1",
            initiator_agent=initiator,
            task_unit={"goal": "g", "artifactOwnership": "neurova/agent_core.py"},
        )

        # 主链不受影响：候选照常合入、run 照常 completed
        assert result["status"] == "completed", result
        cands = swarm._candidates.candidatesForRun(result["subagent_id"])
        assert len(cands) == 1 and cands[0].status == "accepted"
        # 失败留痕：external_patch_proposal_failed 事件点名拒绝原因
        failures = [e for e in events if e["type"] == "external_patch_proposal_failed"]
        assert failures, "提案通道拒绝必须留痕"
        assert "禁改" in str(failures[0]["payload"].get("error", "")), failures[0]
        assert failures[0]["payload"]["target_file"] == "neurova/agent_core.py"
        # 被拒补丁不得进入待审台账（预检在提交前拒绝）
        assert proposer.list_all_proposals() == []

    @pytest.mark.asyncio
    async def test_internalMemberDoesNotTriggerProposal(
            self, swarm, proposer, monkeypatch):
        """内部（非外部）成员合入成功不触发提案通道。"""
        internal = MagicMock()
        internal.config.name = "内置成员"
        internal.chat = AsyncMock(return_value={"text": PATCH})
        events = captureEvents(monkeypatch, swarm)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=internal):
            result = await swarm.spawn(
                task="内部成员任务",
                agent_id="researcher",
                initiator_agent=makeHostAgent(proposer),
                task_unit={"goal": "g", "artifactOwnership": TARGET_FILE},
            )

        assert result["status"] == "completed", result
        assert proposer.list_all_proposals() == [], "内部成员不得触发演化提案通道"
        assert not [e for e in events if e["type"].startswith("external_patch")]

    @pytest.mark.asyncio
    async def test_externalMemberWithoutRepoPathTargetDoesNotTrigger(
            self, swarm, proposer, monkeypatch):
        """外部成员但工件所有权未指名仓库路径（仅记忆键）→ 不触发也不误报失败。"""
        wireExternalMember(monkeypatch, swarm, makeExternalAdapter())
        initiator = makeHostAgent(proposer)
        events = captureEvents(monkeypatch, swarm)

        result = await swarm.spawn(
            task="只动记忆的任务",
            agent_id="ext-1",
            initiator_agent=initiator,
            task_unit={"goal": "g", "artifactOwnership": "记忆:auth, doc-a"},
        )

        assert result["status"] == "completed", result
        assert proposer.list_all_proposals() == [], "未指名补丁目标不得生成提案"
        assert not [e for e in events if e["type"].startswith("external_patch")]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
