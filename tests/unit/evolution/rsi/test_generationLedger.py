"""P0-3 世代账本测试（docs/04-plans/2026-11-21-recursive-self-evolution-plan.md §2.3/§3.2/§6-P0-3）。

先红后绿：本文件先于 neurova/evolution/rsi/generation_ledger.py 存在，
导入失败即红灯；实现转绿后逐条钉住状态机守卫、谱系回溯与 env 持久化纪律。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.evolution.rsi.generation_ledger import (
    DECISION_KINDS,
    ChangeRef,
    DecisionRef,
    DeploymentRef,
    EvolutionGeneration,
    GenerationLedger,
    GenerationStatus,
    GenerationTransitionError,
    SignalRef,
)

ENV_GENERATIONS = "NEUROVA_EVOLUTION_GENERATIONS"


@pytest.fixture(autouse=True)
def _cleanGenerationsEnv(monkeypatch):
    """默认摘掉 env：任何用例都不许隐式写仓库 data/（测试状态污染防线）。"""
    monkeypatch.delenv(ENV_GENERATIONS, raising=False)
    yield


def _signals():
    return [
        SignalRef(kind="evalFailure", ref="case-g2-7", summary="G2 业务判据显著回退"),
        SignalRef(kind="guard", ref="tests/unit/core/test_identityChannelMergedToOneSource.py", summary="身份单通道守卫红"),
    ]


def _changes():
    return [
        ChangeRef(
            targetId="rsi.parameters.temperature",
            kind="param",
            ref="temperature: 0.5 -> 0.7",
            rationale="响应面提示温度区间偏冷",
        )
    ]


def _deployed(ledger: GenerationLedger, parentNo, basisCommit: str) -> EvolutionGeneration:
    """开一代并驱动到 deployed，供基线/回滚类用例复用。"""
    gen = ledger.openGeneration(parentNo, _signals(), _changes(), basisCommit)
    ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed("存活探针全绿")})
    ledger.recordVerdicts(gen.generationNo, {"g2": GateVerdict.passed("业务判据不回退")})
    ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))
    ledger.markDeployed(gen.generationNo, DeploymentRef(canaryConclusion="观测窗平稳"))
    return gen


# ── 开代与谱系 ────────────────────────────────────────────────


def test_openGenerationCreatesProposedRecord():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc1234")

    assert isinstance(gen, EvolutionGeneration)
    assert gen.generationNo == 1
    assert gen.parentNo is None
    assert gen.basisCommit == "abc1234"
    assert gen.status == GenerationStatus.PROPOSED.value
    assert gen.createdAt  # 非空时间戳
    assert [s.kind for s in gen.signals] == ["evalFailure", "guard"]
    assert gen.changes[0].targetId == "rsi.parameters.temperature"
    assert gen.verdicts == {}
    assert gen.decision is None
    assert gen.deployment is None


def test_generationNumbersIncrementAlongLineage():
    ledger = GenerationLedger()
    g1 = ledger.openGeneration(None, _signals(), _changes(), "a1")
    g2 = ledger.openGeneration(g1.generationNo, _signals(), _changes(), "a2")
    g3 = ledger.openGeneration(g2.generationNo, _signals(), _changes(), "a3")

    assert [g.generationNo for g in (g1, g2, g3)] == [1, 2, 3]
    assert ledger.get(3).parentNo == 2
    assert ledger.get(2).parentNo == 1


def test_unknownParentReferenceRejected():
    ledger = GenerationLedger()
    with pytest.raises(ValueError, match="父代 99 不存在"):
        ledger.openGeneration(99, _signals(), _changes(), "a1")


def test_lineageWalksParentChainToRoot():
    ledger = GenerationLedger()
    g1 = ledger.openGeneration(None, _signals(), _changes(), "a1")
    g2 = ledger.openGeneration(g1.generationNo, _signals(), _changes(), "a2")
    g3 = ledger.openGeneration(g2.generationNo, _signals(), _changes(), "a3")

    assert [g.generationNo for g in ledger.lineage(3)] == [3, 2, 1]
    assert [g.generationNo for g in ledger.lineage(1)] == [1]
    assert ledger.lineage(3)[0].basisCommit == "a3"


# ── 状态机守卫 ────────────────────────────────────────────────


def test_fullHappyPathAdvancesThroughAllStates():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")

    ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed("存活探针全绿")})
    assert ledger.get(1).status == GenerationStatus.SHADOW_TESTING.value

    ledger.recordVerdicts(gen.generationNo, {"g2": GateVerdict.passed("业务判据不回退")})
    assert ledger.get(1).status == GenerationStatus.GATED.value
    assert ledger.get(1).verdicts["g0"].state == "passed"
    assert ledger.get(1).verdicts["g2"].state == "passed"

    ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))
    assert ledger.get(1).status == GenerationStatus.CANARY.value
    assert ledger.get(1).decision.kind == "auto"

    ledger.markDeployed(gen.generationNo, DeploymentRef(canaryConclusion="平稳"))
    assert ledger.get(1).status == GenerationStatus.DEPLOYED.value
    assert ledger.get(1).deployment.promotedAt  # 未给 promotedAt 时自动补时间戳


def test_directJumpProposedToDeployedRejected():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")

    with pytest.raises(GenerationTransitionError) as exc:
        ledger.markDeployed(gen.generationNo, DeploymentRef())
    message = str(exc.value)
    # 错误信息点名当前态与期望态（proposal_lifecycle 纪律风格）
    assert "proposed" in message
    assert "canary" in message


def test_decisionBeforeGatingRejected():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")
    with pytest.raises(GenerationTransitionError):
        ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))


def test_verdictsAfterDeployedRejected():
    ledger = GenerationLedger()
    gen = _deployed(ledger, None, "abc")
    with pytest.raises(GenerationTransitionError):
        ledger.recordVerdicts(gen.generationNo, {"g1": GateVerdict.passed()})


def test_decideAfterRejectedRejected():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")
    ledger.markRejected(gen.generationNo, reason="G1 契约守卫一票否决")

    assert ledger.get(1).status == GenerationStatus.REJECTED.value
    assert ledger.get(1).decision.kind == "rejected"
    with pytest.raises(GenerationTransitionError):
        ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))
    with pytest.raises(GenerationTransitionError):
        ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed()})


def test_rejectedFromMidflightCanaryKeepsRecord():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")
    ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed()})
    ledger.recordVerdicts(gen.generationNo, {"g2": GateVerdict.failed("业务判据显著回退")})
    ledger.markRejected(gen.generationNo, reason="G2 业务判据显著回退")

    assert ledger.get(1).status == GenerationStatus.REJECTED.value
    assert ledger.get(1).verdicts["g2"].state == "failed"
    assert ledger.get(1).decision.reason == "G2 业务判据显著回退"


def test_rejectedDecisionRoutesToRejectedState():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")
    ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed()})
    ledger.recordVerdicts(gen.generationNo, {"g2": GateVerdict.passed()})
    ledger.recordDecision(gen.generationNo, DecisionRef(kind="rejected", reason="人工评审否决"))

    assert ledger.get(1).status == GenerationStatus.REJECTED.value
    assert ledger.get(1).decision.kind == "rejected"


def test_rejectionRequiresReason():
    ledger = GenerationLedger()
    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")
    with pytest.raises(ValueError, match="reason"):
        ledger.markRejected(gen.generationNo, reason="  ")


def test_approvalDecisionRequiresApprover():
    with pytest.raises(ValueError, match="审批人"):
        DecisionRef(kind="approval", approver=" ")


def test_decisionKindWhitelist():
    assert DECISION_KINDS == ("auto", "approval", "rejected")
    with pytest.raises(ValueError):
        DecisionRef(kind="yolo")


# ── 基线指认与回滚 ────────────────────────────────────────────


def test_currentBaselinePointsToLatestDeployed():
    ledger = GenerationLedger()
    assert ledger.currentBaseline() is None  # 尚无部署时不编造基线

    _deployed(ledger, None, "a1")
    g2 = _deployed(ledger, 1, "a2")
    assert ledger.currentBaseline().generationNo == g2.generationNo == 2


def test_markRolledBackRestoresBaseline():
    ledger = GenerationLedger()
    _deployed(ledger, None, "a1")
    g2 = _deployed(ledger, 1, "a2")
    assert ledger.currentBaseline().generationNo == 2

    ledger.markRolledBack(g2.generationNo, restoredTo=1)
    rolled = ledger.get(2)
    assert rolled.status == GenerationStatus.ROLLED_BACK.value
    assert rolled.deployment.rolledBackTo == 1
    # 回滚后生产基线指认回父代（上一好代永远可指认）
    assert ledger.currentBaseline().generationNo == 1


def test_rolledBackIsTerminal():
    ledger = GenerationLedger()
    _deployed(ledger, None, "a1")
    g2 = _deployed(ledger, 1, "a2")
    ledger.markRolledBack(g2.generationNo, restoredTo=1)

    with pytest.raises(GenerationTransitionError):
        ledger.markDeployed(g2.generationNo, DeploymentRef())
    with pytest.raises(GenerationTransitionError):
        ledger.recordDecision(g2.generationNo, DecisionRef(kind="auto"))


def test_rollBackTargetMustExist():
    ledger = GenerationLedger()
    gen = _deployed(ledger, None, "a1")
    with pytest.raises(ValueError, match="回滚目标世代 42 不存在"):
        ledger.markRolledBack(gen.generationNo, restoredTo=42)


# ── 持久化（env 约定） ────────────────────────────────────────


def test_envUnsetMeansZeroIO(tmp_path: Path, monkeypatch):
    ledger = GenerationLedger()
    _deployed(ledger, None, "abc")

    # 第一本账从未落盘：换路径开新账本读不到任何代，目录里也不产生文件
    sentinel = tmp_path / "gens.json"
    monkeypatch.setenv(ENV_GENERATIONS, str(sentinel))
    fresh = GenerationLedger()
    assert fresh.get(1) is None
    assert fresh.currentBaseline() is None
    assert list(tmp_path.iterdir()) == []


def test_envConfiguredPersistsAcrossLedgers(tmp_path: Path, monkeypatch):
    state = tmp_path / "gens" / "generations.json"
    monkeypatch.setenv(ENV_GENERATIONS, str(state))

    first = GenerationLedger()
    g1 = first.openGeneration(None, _signals(), _changes(), "a1")
    _deployed(first, 1, "a2")

    second = GenerationLedger()
    assert second.get(1).status == GenerationStatus.PROPOSED.value
    assert second.get(2).status == GenerationStatus.DEPLOYED.value
    assert second.get(2).verdicts["g0"].state == "passed"
    assert second.get(2).deployment.rolledBackTo is None
    assert [g.generationNo for g in second.lineage(2)] == [2, 1]
    assert second.currentBaseline().generationNo == 2
    assert state.exists()
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert [g["generationNo"] for g in payload["generations"]] == [1, 2]


def test_persistLeavesNoTempFileBehind(tmp_path: Path, monkeypatch):
    state = tmp_path / "generations.json"
    monkeypatch.setenv(ENV_GENERATIONS, str(state))
    ledger = GenerationLedger()
    ledger.openGeneration(None, _signals(), _changes(), "abc")
    assert state.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_corruptStateFileFallsBackToEmptyWithoutBlocking(tmp_path: Path, monkeypatch):
    state = tmp_path / "generations.json"
    state.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv(ENV_GENERATIONS, str(state))

    ledger = GenerationLedger()  # 不抛、不阻断
    assert ledger.currentBaseline() is None

    gen = ledger.openGeneration(None, _signals(), _changes(), "abc")  # 从 1 重新编号
    assert gen.generationNo == 1
    ledger.markRejected(1, reason="损坏后重建")
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["generations"][0]["status"] == "rejected"


def test_shapeMismatchedStateFileFallsBackToEmpty(tmp_path: Path, monkeypatch):
    state = tmp_path / "generations.json"
    state.write_text(json.dumps(["不是", "账本结构"]), encoding="utf-8")
    monkeypatch.setenv(ENV_GENERATIONS, str(state))

    ledger = GenerationLedger()
    assert ledger.get(1) is None
