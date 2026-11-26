"""EVO-04：PR_PATCH 通道判据未装配时必须显式不可用，不得留死通道。

审计证据（2026-11-25）：生产默认 `PrPatchChannel()` 未注入 G2/G3/G4 判据，
门禁链整体 `unevidenced`，`apply` 永久拒绝——提案可入账、可批准，但永远
无法生效，用户被引到一条死路。

判据（红 → 绿）：
- 默认通道 `unavailableReason()` 非空且点名缺 G2/G3/G4；
- 未装配判据时 `apply` 在影子验证前直接返回 not_supported，不产生任何副作用；
- 三判据齐备（含注入影子）时通道可用；
- 外部补丁桥在通道不可用时 503 诚实拒绝，不向待审台账塞注定批不了的提案。
"""

from __future__ import annotations

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
from neurova.evolution.rsi.target_registry import EvolutionTargetRegistry


TARGET_FILE = "neurova/context/rules_sections.py"
PATCH = (
    "--- a/neurova/context/rules_sections.py\n"
    "+++ b/neurova/context/rules_sections.py\n"
    "@@ -1 +1,2 @@\n"
    " value = 1\n"
    "+evolved = True\n"
)


def _proposal() -> ImprovementProposal:
    return ImprovementProposal(
        proposal_type=ProposalType.PR_PATCH,
        target=TARGET_FILE,
        content=PATCH,
        description="evo04 测试补丁",
    )


class TestChannelReadiness:
    def test_defaultChannelNamesMissingCriteria(self):
        channel = PrPatchChannel(registry=EvolutionTargetRegistry())
        reason = channel.unavailableReason()
        assert reason, "默认通道未装配判据却自称可用，等于保留死通道"
        assert "G2" in reason and "G3" in reason and "G4" in reason

    def test_applyRefusesBeforeShadowWhenUnready(self, monkeypatch):
        channel = PrPatchChannel(registry=EvolutionTargetRegistry())

        def _mustNotRun():
            raise AssertionError("未装配判据的通道不得启动影子验证")

        monkeypatch.setattr(channel, "_shadowVerify", _mustNotRun)
        plan = PatchPlan(
            proposalId="p1",
            targetId="rsi.parameterFamily",
            targetFile=TARGET_FILE,
            patch=PATCH,
        )
        outcome = channel.apply(_proposal(), plan, approver="admin")
        assert outcome.ok is False
        assert outcome.error.startswith("not_supported"), outcome.error
        assert "未装配" in outcome.error

    def test_readinessTrueWhenCriteriaAndShadowProvided(self):
        channel = PrPatchChannel(
            registry=EvolutionTargetRegistry(),
            shadowVerify=object(),  # 影子行为由调用方提供，通道只校验装配面
            businessCriteria=lambda change, verdicts: GateVerdict.passed("g2"),
            regressionCriteria=lambda change, verdicts: GateVerdict.passed("g3"),
            doctrineCriteria=lambda change, verdicts: GateVerdict.passed("g4"),
        )
        assert channel.unavailableReason() == ""


class TestBridgeRefusesUnavailableChannel:
    def test_externalPatchRejected503WhenChannelUnawired(self, tmp_path):
        from neurova.evolution.rsi.external_candidate_bridge import (
            ExternalPatchRejected,
            submitExternalPatch,
        )
        from neurova.skill_system import SkillRegistry
        from neurova.skills.skill_service import SkillService

        proposer = SelfImprovementProposer(
            agent_id="evo04",
            proposals_dir=Path(tmp_path) / "ledger",
            deployment_controller=RSIDeploymentController(initial_phase=4),
            rollback_manager=RSIRollbackManager(),
            skill_service=SkillService("evo04", skills_dir=str(tmp_path / "skills")),
            skill_registry=SkillRegistry(),
        )
        with pytest.raises(ExternalPatchRejected) as err:
            submitExternalPatch(
                agentId="ext-evo04",
                targetFile=TARGET_FILE,
                patchContent=PATCH,
                proposer=proposer,
            )
        assert err.value.status_code == 503
        assert "PR_PATCH" in str(err.value)
        assert not list(proposer._proposals_cache.values()), (
            "通道不可用时不得向台账塞注定批不了的提案"
        )