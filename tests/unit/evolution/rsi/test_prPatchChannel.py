"""PrPatchChannel 生效通道单元测试（P2-1，计划书 §3.6 / §6 P2 批 P2-1）。

红灯判据（现状可复现）：PR_PATCH 提案走到 approve_and_apply 被 not_supported
诚实拒绝——通道接通前，"批准"不产生任何生效。

绿灯判据（通道接通后）：
- 合法 patch：过影子验证（门禁链全绿）+ 人工审批（phase≥4）后真实生效，
  工作区文件被补丁改写、台账记 APPLIED、scope 快照可读回、CAS 板记一次合入；
- 禁改目标：kernel 清单内的文件被拒（fail-closed）；
- 白名单外目标：未登记的 neurova/ 模块一律拒（§6 P2-3）；
- 非法 patch：git apply --check 预检失败，门禁链整体 failed，工作树零改动；
- CAS 冲突：合入板冲突升级人工，不静默覆盖、不应用；
- 快照/回滚：回滚把目标文件恢复到应用前字节，状态记 ROLLED_BACK；
- 其余类型（action_definition）保持 not_supported 诚实拒绝，不因通道存在而放开。

隔离纪律：影子验证用桩回放（真实影子行为由 test_shadowVerify 覆盖）+ 真实
git apply --check 预检路径；工作区/检查点/合并板全部落 tmp，不碰本仓工作树。
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
    ImprovementProposal,
    ProposalType,
    SelfImprovementProposer,
)
from neurova.evolution.rsi.shadow_verify import ShadowRunResult, ShadowVerify
from neurova.evolution.rsi.target_registry import EvolutionTargetRegistry


@pytest.fixture(autouse=True)
def _gitIdentity(monkeypatch):
    """scope 快照的 git commit 需要作者身份（同 tests/unit/checkpoints/conftest）。"""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "neurova-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "neurova-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "neurova-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "neurova-test@example.com")


#: 首批 L2 白名单对象之一作为补丁目标（P2-3 登记；本文件用局部注册表注入，
#: 与全局注册表的登记解耦——全局登记由 test_l2WhitelistGuard 守卫）。
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
    """临时 git 仓：带白名单目标文件（内容与 patch 上下文对齐）。

    用 write_bytes 落 LF 字节——Path.write_text 在 Windows 会把 \\n 翻译成
    \\r\\n，污染 scope 快照字节级比对。
    """
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


def _localRegistry() -> EvolutionTargetRegistry:
    """局部注册表实例：禁改内核 + P2-3 首批 L2 白名单随构造自动装配。

    用独立实例而非进程级单例——单测不依赖、也不污染全局注册表状态。
    """
    return EvolutionTargetRegistry()


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
    """影子验证桩：回放预设 verdicts，不起子进程。"""

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


def _channel(tmp_path: Path, workspace: Path, shadow=None, **kwargs) -> PrPatchChannel:
    from neurova.agent.candidate_merge import CandidateMergeBoard
    from neurova.checkpoints.service import CheckpointService

    return PrPatchChannel(
        registry=_localRegistry(),
        workspace=workspace,
        shadowVerify=shadow,
        checkpointService=CheckpointService("kai", base_dir=str(tmp_path / "ckpt")),
        mergeBoard=CandidateMergeBoard(),
        regressionCriteria=lambda change, verdicts: GateVerdict.passed("A/B 零新增失败"),
        doctrineCriteria=lambda change, verdicts: GateVerdict.passed(
            "红绿+live-verify 证据在案"
        ),
        **kwargs,
    )


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


def _patchProposal(proposer: SelfImprovementProposer, target: str = TARGET_FILE,
                   patch: str = PATCH) -> ImprovementProposal:
    proposal = proposer.propose_pr_patch(
        target_file=target, patch_content=patch, description="进化补丁"
    )
    proposer.submit_proposal(proposal)
    return proposal


def _targetPath(workspace: Path) -> Path:
    return workspace / "neurova" / "context" / "rules_sections.py"


class TestPlanGate:
    """plan：类型/禁改/白名单/文件存在性四道闸。"""

    def test_nonPrPatchTypeIsRefusedAsNotSupported(self, tmp_path):
        channel = _channel(tmp_path, tmp_path)
        proposal = ImprovementProposal(
            proposal_type=ProposalType.ACTION_DEFINITION,
            target="some_action", content="def handle(args):\n    return 1\n",
        )
        outcome = channel.plan(proposal)
        assert isinstance(outcome, str)
        assert "not_supported" in outcome, outcome

    def test_forbiddenKernelTargetIsRefused(self, tmp_path):
        channel = _channel(tmp_path, tmp_path)
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH,
            target="neurova/agent_core.py", content=PATCH,
        )
        outcome = channel.plan(proposal)
        assert isinstance(outcome, str)
        assert "l2_not_allowed" in outcome and "禁改" in outcome, outcome

    def test_nonWhitelistedModuleIsRefused(self, tmp_path):
        channel = _channel(tmp_path, tmp_path)
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH,
            target="neurova/agent/orchestrator.py", content=PATCH,
        )
        outcome = channel.plan(proposal)
        assert isinstance(outcome, str)
        assert "l2_not_allowed" in outcome and "白名单" in outcome, outcome

    def test_missingTargetFileIsRefused(self, tmp_path):
        emptyWs = tmp_path / "empty-ws"
        emptyWs.mkdir()
        channel = _channel(tmp_path, emptyWs)
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH, target=TARGET_FILE, content=PATCH,
        )
        outcome = channel.plan(proposal)
        assert isinstance(outcome, str)
        assert "不存在" in outcome, outcome

    def test_whitelistedTargetYieldsPatchPlan(self, tmp_path):
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace)
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH, target=TARGET_FILE, content=PATCH,
            proposal_id="prop-plan-1",
        )
        plan = channel.plan(proposal)
        assert isinstance(plan, PatchPlan)
        assert plan.targetId == "l2.promptCompiler"
        assert plan.targetFile == TARGET_FILE
        assert plan.patch == PATCH
        assert plan.proposalId == "prop-plan-1"


class TestVerifyGates:
    def test_illegalPatchFailsAtPrecheckAndShortCircuits(self, tmp_path):
        """真实影子（预检失败即短路，不起探针子进程）：整体 failed、G0 扛失败结论。"""
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=ShadowVerify(workspace=workspace))
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH, target=TARGET_FILE,
            content="这不是一个合法的 unified diff",
        )
        plan = channel.plan(proposal)
        assert isinstance(plan, PatchPlan)
        gateResult = channel.verify(proposal, plan)
        assert gateResult["overall"][0].state == "failed"
        assert gateResult["g0"][0].state == "failed"
        assert TARGET_FILE in gateResult["g0"][0].reason
        # G0 短路：后续门禁不执行（结果不含其键）
        assert "g1" not in gateResult and "g4" not in gateResult

    def test_greenShadowOrganizesAllFiveGates(self, tmp_path):
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH, target=TARGET_FILE, content=PATCH,
        )
        plan = channel.plan(proposal)
        gateResult = channel.verify(proposal, plan)
        assert set(gateResult) == {"g0", "g1", "g2", "g3", "g4", "overall"}
        for gate in ("g0", "g1", "g2", "g3", "g4", "overall"):
            assert gateResult[gate][0].state == "passed", gateResult[gate][0].reason
        # 影子收到的变更：L2 patch 候选，目标与补丁对齐提案
        change = channel._shadow.calls[0]
        assert change.kind == "patch" and change.targetFile == TARGET_FILE


class TestApplyFlow:
    def test_legalPatchAppliesThroughApproval(self, tmp_path):
        """主判据：合法 PR_PATCH 在影子全绿 + phase4 + 人工批准下真实生效。"""
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))
        proposer = _makeProposer(tmp_path)
        proposer._pr_patch_channel = channel
        proposal = _patchProposal(proposer)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is True, f"红灯现状（通道未接通）: {result.error}"
        assert proposal.status.value == "applied"
        assert result.proposal.approved_by == "admin"
        # 工作区文件真的被补丁改写（生效，不是一次文件写入的假象）
        assert _targetPath(workspace).read_text(encoding="utf-8") == (
            ORIGINAL_CONTENT + "evolved = True\n"
        )
        # scope 快照可读回应用前字节（回滚底座在位）
        payload = channel._checkpointServiceFor("kai").restoreScope(
            proposal.proposal_id, 1
        )
        assert payload[TARGET_FILE].decode("utf-8") == ORIGINAL_CONTENT
        # CAS 板记一次合入（合入链可追溯）
        assert channel._mergeBoard().revision == 1
        assert result.snapshot_id.startswith("refs/neurova/checkpoints/")

    def test_applyRefusedWhenGatesNotGreen(self, tmp_path):
        workspace = _makeWorkspace(tmp_path)
        badVerdicts = _allGreenVerdicts()
        badVerdicts["build"] = GateVerdict.failed("构建失败")
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(badVerdicts))
        proposer = _makeProposer(tmp_path)
        proposer._pr_patch_channel = channel
        proposal = _patchProposal(proposer)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is False
        assert "门禁链" in result.error, result.error
        assert proposal.status.value == "pending", "被拒提案不得离开待审状态"
        assert _targetPath(workspace).read_text(encoding="utf-8") == ORIGINAL_CONTENT

    def test_casConflictEscalatesToHuman(self, tmp_path):
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))
        # 先真实合入一颗种子候选把板推到 revision=1，再令 apply 提交的候选带
        # 陈旧基准 0 → 真实合并板逻辑必判 CAS 冲突
        board = channel._mergeBoard()
        seed = board.submitCandidate(runId="seed", content="seed", artifactKeys=[TARGET_FILE])
        board.mergeCandidate(seed.candidateId)
        originalSubmit = board.submitCandidate

        def staleSubmit(*args, **kwargs):
            kwargs["baseRevision"] = 0
            return originalSubmit(*args, **kwargs)

        board.submitCandidate = staleSubmit
        proposer = _makeProposer(tmp_path)
        proposer._pr_patch_channel = channel
        proposal = _patchProposal(proposer)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is False
        assert "冲突" in result.error, result.error
        assert proposal.status.value == "pending"
        assert _targetPath(workspace).read_text(encoding="utf-8") == ORIGINAL_CONTENT

    def test_rollbackRestoresPreApplyBytes(self, tmp_path):
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))
        proposer = _makeProposer(tmp_path)
        proposer._pr_patch_channel = channel
        proposal = _patchProposal(proposer)
        applied = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        assert applied.success is True, applied.error

        rolled = proposer.rollback_applied_proposal(
            proposal.proposal_id, applied.snapshot_id
        )

        assert rolled.success is True, rolled.error
        assert _targetPath(workspace).read_text(encoding="utf-8") == ORIGINAL_CONTENT
        assert proposal.status.value == "rolled_back"

    def test_phaseGateStillRequiresPhase4(self, tmp_path):
        """部署阶段 gate 先于通道：phase 0 拦下高风险提案（通道不绕审批）。"""
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))
        proposer = _makeProposer(tmp_path, phase=0)
        proposer._pr_patch_channel = channel
        proposal = _patchProposal(proposer)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is False
        assert "phase" in result.error.lower() or "阶段" in result.error, result.error
        assert _targetPath(workspace).read_text(encoding="utf-8") == ORIGINAL_CONTENT

    def test_actionDefinitionStillNotSupported(self, tmp_path):
        """非 PR_PATCH 的无通道类型保持 not_supported 诚实拒绝。"""
        workspace = _makeWorkspace(tmp_path)
        channel = _channel(tmp_path, workspace, shadow=_StubShadow(_allGreenVerdicts()))
        proposer = _makeProposer(tmp_path)
        proposer._pr_patch_channel = channel
        proposal = proposer.propose_action_definition(
            action_name="new_action", handler_code="def handle(args):\n    return 1\n"
        )
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is False
        assert "not_supported" in result.error, result.error
        assert proposal.status.value == "pending"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
