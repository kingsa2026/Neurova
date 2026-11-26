# -*- coding: utf-8 -*-
"""ExternalCandidateBridge 单元测试（P2-2，计划书 §3.6 生成端 / §6 P2 批 P2-2）。

红灯判据（现状可复现）：桥接函数不存在——外部编码成员（neuacp）的代码产出
没有进入演化提案通道的任何入口，swarm 拿到 unified diff 只能走候选板文本合并。

绿灯判据（桥接接通后）：
- 合法 unified diff → 提案创建成功、状态 PENDING，metadata 带来源 lineage
  （source=neuacp_external + agent_id/run_id）；
- 触碰禁改内核的 patch → 提交即被预检拒绝（TargetRegistry assertMutable
  fail-closed，与批准时同一道闸），待审台账不收"注定批不了"的提案；
- 空补丁 / 越界路径 → 422 语义拒绝（ExternalPatchRejected.status_code=422）；
- 桥接产出的提案与 PrPatchChannel 衔接：plan → verify（注入桩影子）可走通，
  证明外部提案与内部提案共用同一条 L2 生效通道（不新建审批面）。

隔离纪律：proposer/channel 全部注入（台账/工作区/合并板/影子落 tmp），
不碰生产装配、不碰本仓工作树。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.evolution.rsi.pr_patch_channel import PatchPlan, PrPatchChannel
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.evolution.rsi.self_improvement_proposer import (
    ProposalStatus,
    ProposalType,
    SelfImprovementProposer,
)
from neurova.evolution.rsi.shadow_verify import ShadowRunResult, ShadowVerify
from neurova.evolution.rsi.target_registry import EvolutionTargetRegistry


@pytest.fixture(autouse=True)
def _gitIdentity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "neurova-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "neurova-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "neurova-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "neurova-test@example.com")


#: 首批 L2 白名单对象之一（与 test_prPatchChannel 同一目标，patch 上下文对齐）。
TARGET_FILE = "neurova/context/rules_sections.py"
ORIGINAL_CONTENT = "value = 1\n"
PATCH = (
    "--- a/neurova/context/rules_sections.py\n"
    "+++ b/neurova/context/rules_sections.py\n"
    "@@ -1 +1,2 @@\n"
    " value = 1\n"
    "+evolved = True\n"
)


def _makeWorkspace(tmp_path: Path) -> Path:
    """临时 git 仓：带白名单目标文件（内容与 patch 上下文对齐；LF 字节落盘）。"""
    repo = tmp_path / "ws"
    (repo / "neurova" / "context").mkdir(parents=True)
    (repo / "neurova" / "context" / "rules_sections.py").write_bytes(
        ORIGINAL_CONTENT.encode("utf-8")
    )
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=str(repo), check=True, capture_output=True,
    )
    return repo


def _makeProposer(tmp_path: Path, phase: int = 4) -> SelfImprovementProposer:
    from neurova.skill_system import SkillRegistry
    from neurova.skills.skill_service import SkillService

    return SelfImprovementProposer(
        agent_id="kai",
        proposals_dir=tmp_path / "ledger",
        deployment_controller=RSIDeploymentController(initial_phase=phase),
        rollback_manager=RSIRollbackManager(),
        skill_service=SkillService("kai", skills_dir=str(tmp_path / "agent-skills")),
        skill_registry=SkillRegistry(),
    )


def _allGreenVerdicts() -> dict:
    verdicts = {
        name: GateVerdict.passed(f"{name} 通过")
        for name in ("build", "health", "startup", "minimalChat", "toolExecution")
    }
    verdicts["guardSubset"] = GateVerdict.passed("守卫子集全绿")
    verdicts["patchApply"] = GateVerdict.passed("补丁预检通过")
    verdicts["g2Business"] = GateVerdict.passed("业务判据通过")
    return verdicts


class _StubShadow:
    """影子验证桩：回放预设 verdicts，不起子进程（真实影子由 test_shadowVerify 覆盖）。"""

    def __init__(self, verdicts: dict):
        self._verdicts = verdicts
        self.calls: list = []

    def verify(self, change):
        self.calls.append(change)
        return ShadowRunResult(
            changeId=change.changeId,
            kind=change.kind,
            verdicts=dict(self._verdicts),
            overall="passed",
            durationMs=0,
            dataRoot="stub://data",
            workspace="stub://ws",
        )


def _makeChannel(tmp_path: Path, workspace: Path, shadow=None) -> PrPatchChannel:
    from neurova.agent.candidate_merge import CandidateMergeBoard
    from neurova.checkpoints.service import CheckpointService

    return PrPatchChannel(
        registry=EvolutionTargetRegistry(),
        workspace=workspace,
        shadowVerify=shadow,
        checkpointService=CheckpointService("kai", base_dir=str(tmp_path / "ckpt")),
        mergeBoard=CandidateMergeBoard(),
        # EVO-04：三判据齐备才可用；本组测桥接/目标校验行为，按生产装配口径
        # 注入 G2（未装配时的 not_supported 由 test_prPatchChannelReadiness 覆盖）。
        businessCriteria=lambda change, verdicts: GateVerdict.passed("业务判据在案"),
        regressionCriteria=lambda change, verdicts: GateVerdict.passed("A/B 零新增失败"),
        doctrineCriteria=lambda change, verdicts: GateVerdict.passed("红绿+live-verify 在案"),
    )


def _submit(**overrides):
    """桥接调用统一入口：注入 proposer/channel（隔离生产装配），其余按需覆写。"""
    from neurova.evolution.rsi.external_candidate_bridge import submitExternalPatch

    kwargs = dict(
        agentId="ext-coder",
        targetFile=TARGET_FILE,
        patchContent=PATCH,
        description="外部成员修复",
        runContext={"runId": "run-abc", "tenantId": "t1", "teamId": "team-9"},
    )
    kwargs.update(overrides)
    return submitExternalPatch(**kwargs)


class TestBridgeExists:
    def test_submitExternalPatch_is_importable_and_callable(self):
        from neurova.evolution.rsi.external_candidate_bridge import submitExternalPatch

        assert callable(submitExternalPatch)


class TestSubmitExternalPatch:
    def test_legalDiffCreatesPendingProposalWithLineage(self, tmp_path):
        """主判据：合法 diff → 提案 PENDING 入账，metadata 带来源 lineage。"""
        workspace = _makeWorkspace(tmp_path)
        proposer = _makeProposer(tmp_path)
        channel = _makeChannel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))

        proposalId = _submit(proposer=proposer, channel=channel)

        assert proposalId, "必须返回提案 id"
        stored = proposer._proposals_cache[proposalId]
        assert stored.proposal_type == ProposalType.PR_PATCH
        assert stored.status == ProposalStatus.PENDING, "外部产出与内部提案同 awaiting 人工评审"
        assert stored.target == TARGET_FILE
        assert stored.content == PATCH
        # 来源 lineage 入 metadata：谁（外部成员）在哪个 run 产出
        assert stored.metadata["source"] == "neuacp_external"
        assert stored.metadata["agent_id"] == "ext-coder"
        assert stored.metadata["run_id"] == "run-abc"
        assert stored.metadata["run_context"]["tenantId"] == "t1"
        assert stored.metadata["run_context"]["teamId"] == "team-9"
        # runId 本身不再重复进 run_context（避免同一事实两处存）
        assert "runId" not in stored.metadata["run_context"]
        # 台账落盘可读回（from_dict 保留 metadata）
        reread = SelfImprovementProposer(
            agent_id="kai",
            proposals_dir=tmp_path / "ledger",
            deployment_controller=RSIDeploymentController(initial_phase=4),
            rollback_manager=RSIRollbackManager(),
        )
        assert reread._proposals_cache[proposalId].metadata["agent_id"] == "ext-coder"

    def test_forbiddenKernelTargetRejectedAtSubmission(self, tmp_path):
        """触碰禁改内核（neurova/agent_core.py）→ 提交即拒，台账不收。"""
        workspace = _makeWorkspace(tmp_path)
        proposer = _makeProposer(tmp_path)
        channel = _makeChannel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))

        from neurova.evolution.rsi.external_candidate_bridge import ExternalPatchRejected

        with pytest.raises(ExternalPatchRejected) as excinfo:
            _submit(
                targetFile="neurova/agent_core.py",
                patchContent=PATCH.replace("rules_sections.py", "agent_core.py"),
                proposer=proposer,
                channel=channel,
            )
        assert excinfo.value.status_code == 422
        assert "禁改" in str(excinfo.value), excinfo.value
        assert proposer.list_all_proposals() == [], "被拒补丁不得进入待审台账"

    def test_emptyPatchRejectedAs422(self, tmp_path):
        """空补丁 → 422 语义拒绝（不构成可评审提案）。"""
        from neurova.evolution.rsi.external_candidate_bridge import ExternalPatchRejected

        with pytest.raises(ExternalPatchRejected) as excinfo:
            _submit(patchContent="   \n  ")
        assert excinfo.value.status_code == 422

    def test_pathTraversalTargetRejectedAs422(self, tmp_path):
        """越界路径（路径穿越）→ 422 语义拒绝。"""
        from neurova.evolution.rsi.external_candidate_bridge import ExternalPatchRejected

        proposer = _makeProposer(tmp_path)
        channel = _makeChannel(tmp_path, tmp_path)
        with pytest.raises(ExternalPatchRejected) as excinfo:
            _submit(targetFile="../../etc/passwd", proposer=proposer, channel=channel)
        assert excinfo.value.status_code == 422

    def test_absoluteSystemPathTargetRejectedAs422(self, tmp_path):
        """越界路径（绝对路径指名系统文件）→ 422 语义拒绝。"""
        from neurova.evolution.rsi.external_candidate_bridge import ExternalPatchRejected

        proposer = _makeProposer(tmp_path)
        channel = _makeChannel(tmp_path, tmp_path)
        with pytest.raises(ExternalPatchRejected) as excinfo:
            _submit(targetFile="/etc/passwd", proposer=proposer, channel=channel)
        assert excinfo.value.status_code == 422

    def test_blankTargetRejectedAs422(self, tmp_path):
        from neurova.evolution.rsi.external_candidate_bridge import ExternalPatchRejected

        with pytest.raises(ExternalPatchRejected) as excinfo:
            _submit(targetFile="  ")
        assert excinfo.value.status_code == 422

    def test_blankAgentIdRejected(self, tmp_path):
        from neurova.evolution.rsi.external_candidate_bridge import ExternalPatchRejected

        with pytest.raises(ExternalPatchRejected) as excinfo:
            _submit(agentId="")
        assert excinfo.value.status_code == 422


class TestChannelHandoff:
    def test_bridgedProposalWalksChannelVerifyPath(self, tmp_path):
        """衔接判据：桥接产出的提案经 channel.plan → verify（注入桩）走通，
        证明外部提案与内部提案共用同一条 L2 生效通道与门禁链。"""
        workspace = _makeWorkspace(tmp_path)
        proposer = _makeProposer(tmp_path)
        shadow = _StubShadow(_allGreenVerdicts())
        channel = _makeChannel(tmp_path, workspace, shadow=shadow)

        proposalId = _submit(proposer=proposer, channel=channel)
        proposal = proposer._proposals_cache[proposalId]

        plan = channel.plan(proposal)
        assert isinstance(plan, PatchPlan), plan
        assert plan.targetFile == TARGET_FILE
        assert plan.patch == PATCH

        gates = channel.verify(proposal, plan)
        assert gates["overall"][0].state == "passed", gates["overall"][0].reason
        # 影子收到的是本提案的 patch 候选（target/patch 与桥接产出一致）
        assert shadow.calls, "verify 必须把提案补丁交给影子验证"
        assert shadow.calls[0].targetFile == TARGET_FILE
        assert shadow.calls[0].patch == PATCH

    def test_bridgedProposalSurvivesApprovalGatesUnchanged(self, tmp_path):
        """双 gate 不因桥接放松：phase 0 下外部提案批准仍被部署阶段 gate 拦下。"""
        workspace = _makeWorkspace(tmp_path)
        proposer = _makeProposer(tmp_path, phase=0)
        channel = _makeChannel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))

        proposalId = _submit(proposer=proposer, channel=channel)
        result = proposer.approve_and_apply(proposalId, approver="admin")

        assert result.success is False
        assert "phase" in result.error.lower() or "阶段" in result.error, result.error
        assert proposer._proposals_cache[proposalId].status == ProposalStatus.PENDING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
