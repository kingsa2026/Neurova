"""P1-4 金丝雀观测窗与自动回滚演练（计划书 §2.0/§3.9/§5 L4-L5/§6 P1-4/§8-4）。

先红后绿：本文件先于实现存在——canaryCheckpoint / observeOpenCanaries /
canaryReadout 与「批准应用后先进入 canary 观测窗、窗满晋升、越界自动回滚」
的语义尚未落地，用例即红灯。演练判据（总纲：进化全程自动，回滚无人工确认）：

1. 演练一：窗口=0 → 过门禁世代批准应用后直接 promoted（无观测等待）；
2. 演练二：窗内注入 should_rollback 命中读数（负增益/例级退化）→
   自动回滚：参数恢复父代实值、markRolledBack(restoredTo=parentNo)、
   rollback_manager 留痕、账本可回溯；
3. 窗满无异常 → markDeployed（promotedAt 落定、currentBaseline 指认）；
4. 窗口未满 → 世代 status=canary，get_status / canaryReadout 可见开窗；
5. 阈值消费：健康回调越界（max_error_rate/min_success_rate_drop）→ 回滚；
   默认无回调 → 阈值不参与判定（诚实：当前无生产错误率信号源，不造假信号）；
6. 观测驱动：run_iteration 每轮自动观测开窗世代（生产驱动不缺席）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.rsi.gate_verdict import STATE_FAILED, STATE_PASSED, GateVerdict
from neurova.evolution.rsi.generation_ledger import (
    DecisionRef,
    DeploymentRef,
    GenerationLedger,
    GenerationStatus,
    GenerationTransitionError,
)
# 红灯：金丝雀观测窗 API 尚不存在 → 构造/调用即 AttributeError/TypeError。
from neurova.evolution.rsi.generation_orchestrator import GenerationOrchestrator
from neurova.evolution.rsi.generation_ledger import SignalRef, ChangeRef
from neurova.evolution.rsi.orchestrator import RSIOrchestrator
from neurova.evolution.rsi.shadow_verify import ShadowRunResult
from neurova.evolution.rsi.survival_probe import CRITERION_ORDER

ENV_GENERATIONS = "NEUROVA_EVOLUTION_GENERATIONS"


@pytest.fixture(autouse=True)
def _cleanGenerationsEnv(monkeypatch):
    """默认摘掉世代账本 env：任何用例都不许隐式写仓库 data/（状态污染防线）。"""
    monkeypatch.delenv(ENV_GENERATIONS, raising=False)
    yield


def _writePhase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int) -> None:
    """阶段经治理设置进入（conftest 规则 1：禁止私赋 deployment phase）。"""
    path = tmp_path / "governance_settings.json"
    path.write_text(
        json.dumps({"rsi_phase": phase, "conversation_rules_enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))


def _buildSystems() -> dict:
    """四闭环真实子系统（与 P1-3 测试同基座）：tool_memory 0.85 vs setpoint 0.8
    是当前全仓唯一真实梯度，保证每轮都有候选。"""
    weights = AdaptiveToolWeights()
    for _ in range(7):
        weights.update_weight("web_fetch", True)
    for _ in range(3):
        weights.update_weight("web_fetch", False)
    return {
        "sleep": SleepConsolidation(),
        "emotion": EmotionModule(),
        "experience": ExperienceFeedback(),
        "tool_memory": ToolMemoryIntegration(
            memory_layer=None,
            muscle_memory=None,
            tool_weights=weights,
            confidence_threshold=0.8,
            temperature_threshold=30.0,
            muscle_memory_threshold=0.85,
        ),
    }


def _buildOrchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int
) -> RSIOrchestrator:
    _writePhase(tmp_path, monkeypatch, phase)
    systems = _buildSystems()
    return RSIOrchestrator(
        sleep_system=systems["sleep"],
        emotion_system=systems["emotion"],
        experience_system=systems["experience"],
        tool_memory_system=systems["tool_memory"],
        agent_id="canary-drill",
    )


def _toolMemoryThreshold(orch: RSIOrchestrator):
    params = {
        p.name: p.current_value
        for p in orch.integration_manager.get_optimizable_parameters()["tool_memory"]
    }
    return params["muscle_memory_threshold"]


class _StubShadowVerify:
    """可编程影子验证桩（与 test_generationOrchestrator 同形，全绿默认）。"""

    def __init__(self, *, tmpRoot: Path):
        self._tmpRoot = tmpRoot
        self._tmpRoot.mkdir(parents=True, exist_ok=True)

    def _verdict(self, name: str) -> GateVerdict:
        return GateVerdict.passed(f"{name} 通过（桩）")

    def verify(self, change) -> ShadowRunResult:
        verdicts = {name: self._verdict(name) for name in CRITERION_ORDER}
        verdicts["parameterApply"] = self._verdict("parameterApply")
        verdicts["g2Business"] = self._verdict("g2Business")
        verdicts["g3Regression"] = self._verdict("g3Regression")
        return ShadowRunResult(
            changeId=change.changeId,
            kind=change.kind,
            verdicts=verdicts,
            overall=STATE_PASSED,
            durationMs=0,
            dataRoot=str(self._tmpRoot),
            workspace="stub",
        )


def _attach(
    orch: RSIOrchestrator,
    shadow,
    *,
    canaryWindowSeconds: float = 0,
    canaryHealthCallback=None,
    ledger=None,
) -> GenerationOrchestrator:
    genOrch = GenerationOrchestrator(
        rsiOrchestrator=orch,
        shadowVerify=shadow,
        ledger=ledger,
        canaryWindowSeconds=canaryWindowSeconds,
        canaryHealthCallback=canaryHealthCallback,
    )
    orch.generationOrchestrator = genOrch
    return genOrch


def _approve(orch: RSIOrchestrator) -> Dict[str, Any]:
    return orch.applyApprovedOptimizations(approved_by="drill-admin")


def _deployFirstGeneration(orch: RSIOrchestrator, genOrch: GenerationOrchestrator):
    """第 1 代走完观测窗并晋升为父代基线；返回 (parentNo, 父代参数实值)。"""
    orch.run_iteration()
    _approve(orch)
    time.sleep(0.35)
    settled = genOrch.canaryCheckpoint(1)
    assert settled.status == GenerationStatus.DEPLOYED.value
    return settled.generationNo, _toolMemoryThreshold(orch)


# ── 演练一：窗口=0 → 批准应用后直接 promoted ─────────────────────


class TestZeroWindowDrill:
    def test_zeroWindowPromotesImmediatelyAfterApply(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=0)

        orch.run_iteration()
        outcome = _approve(orch)
        assert outcome["applied_count"] >= 1

        gen = genOrch.generationForRound(1)
        assert gen is not None
        # 窗长 0：观测窗即刻满足，不滞留 canary，直接晋升落定
        assert gen.status == GenerationStatus.DEPLOYED.value
        assert gen.deployment is not None and gen.deployment.promotedAt
        assert genOrch.generationLedger().currentBaseline().generationNo == gen.generationNo
        assert _toolMemoryThreshold(orch) != 0.85


# ── 演练核心：窗满晋升 / 窗内自动回滚 ────────────────────────────


class TestCanaryWindowDrill:
    def test_windowElapsedPromotesGeneration(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=0.2)

        orch.run_iteration()
        _approve(orch)
        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.CANARY.value, "窗未满前应处于 canary 观测态"

        time.sleep(0.25)
        settled = genOrch.canaryCheckpoint(1)
        assert settled.status == GenerationStatus.DEPLOYED.value, "窗满无异常应晋升"
        assert settled.deployment.promotedAt
        assert genOrch.generationLedger().currentBaseline().generationNo == settled.generationNo
        assert genOrch.canaryReadout()["count"] == 0, "晋升后开窗应关闭"

    def test_inWindowNegativeGainAutoRollsBackToParent(self, tmp_path, monkeypatch):
        """演练二：窗内注入负增益读数 → should_rollback 命中 → 全自动回滚：
        markRolledBack(restoredTo=parentNo)、参数恢复父代实值、rollback_manager 留痕。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=0.3)

        # 第 1 代：窗满晋升，成为父代基线
        orch.run_iteration()
        _approve(orch)
        time.sleep(0.35)
        genOrch.canaryCheckpoint(1)
        parentNo = genOrch.generationLedger().currentBaseline().generationNo
        parentParam = _toolMemoryThreshold(orch)
        assert parentNo == 1

        # 第 2 代：批准应用后进入 canary（窗未满）
        orch.run_iteration()
        _approve(orch)
        gen2 = genOrch.generationForRound(2)
        assert gen2.status == GenerationStatus.CANARY.value
        assert gen2.parentNo == parentNo
        canaryParam = _toolMemoryThreshold(orch)
        assert canaryParam != parentParam, "前提：金丝雀窗内参数已应用（受限发布）"

        historyBefore = len(orch.rollback_manager.get_rollback_history())
        settled = genOrch.canaryCheckpoint(2, readings={"gain": -0.5})

        # 全自动回滚：无人工确认
        assert settled.status == GenerationStatus.ROLLED_BACK.value
        assert settled.deployment.rolledBackTo == parentNo
        assert "gain" in (settled.deployment.canaryConclusion or ""), "回滚原因必须留痕"
        # 参数恢复父代实值（复用 R1 快照恢复路径）
        assert _toolMemoryThreshold(orch) == parentParam
        # rollback_manager 留痕（晋升判据"距上次回滚天数"的唯一数据源）
        history = orch.rollback_manager.get_rollback_history()
        assert len(history) == historyBefore + 1
        # 回滚后该世代终止：生产基线指认回父代
        assert genOrch.generationLedger().currentBaseline().generationNo == parentNo
        assert genOrch.canaryReadout()["count"] == 0, "回滚后开窗应关闭"

    def test_inWindowCaseRegressionAutoRollsBack(self, tmp_path, monkeypatch):
        """窗内注入例级退化读数（should_rollback 五条件之一）→ 自动回滚。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=0.3)

        parentNo, parentParam = _deployFirstGeneration(orch, genOrch)

        orch.run_iteration()
        _approve(orch)
        gen2 = genOrch.generationForRound(2)
        assert gen2.status == GenerationStatus.CANARY.value

        settled = genOrch.canaryCheckpoint(2, readings={"case_regressions": ["case-7"]})
        assert settled.status == GenerationStatus.ROLLED_BACK.value
        assert settled.deployment.rolledBackTo == parentNo
        assert "case-7" in (settled.deployment.canaryConclusion or "")
        assert _toolMemoryThreshold(orch) == parentParam, "参数必须恢复到应用前（父代）实值"

    def test_windowNotElapsedStaysCanaryAndVisibleInStatus(self, tmp_path, monkeypatch):
        """窗口未满：世代停留 canary，get_status / canaryReadout 可见开窗。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=60)

        orch.run_iteration()
        _approve(orch)
        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.CANARY.value

        settled = genOrch.canaryCheckpoint(1, readings={})
        assert settled.status == GenerationStatus.CANARY.value, "窗未满且判据未命中，不晋升也不回滚"

        readout = genOrch.canaryReadout()
        assert readout["count"] == 1
        assert readout["openWindows"][0]["generationNo"] == gen.generationNo
        assert readout["openWindows"][0]["roundNo"] == 1
        status = orch.get_status()
        assert status["canary"]["count"] == 1, "get_status 必须暴露金丝雀观测面"

    def test_iterationDrivesCanaryObservation(self, tmp_path, monkeypatch):
        """观测驱动接线：窗满后一次 run_iteration 自动完成晋升（生产驱动不缺席）。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=0.2)

        orch.run_iteration()
        _approve(orch)
        assert genOrch.generationForRound(1).status == GenerationStatus.CANARY.value

        time.sleep(0.25)
        orch.run_iteration()  # 生产驱动：每轮迭代观测开窗世代
        assert genOrch.generationForRound(1).status == GenerationStatus.DEPLOYED.value


# ── 阈值消费：健康回调可选注入，默认不参与判定 ────────────────────


class TestCanaryThresholdConsumption:
    def test_healthCallbackErrorRateBreachTriggersRollback(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        health = {"armed": False}

        def _health():
            if not health["armed"]:
                return None  # 父代观测期不注入（回调只服务被测的那一代）
            return {"error_rate": 0.5, "success_rate": 0.2, "baseline_success_rate": 0.9}

        genOrch = _attach(
            orch,
            _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
            canaryWindowSeconds=0.3,
            canaryHealthCallback=_health,
        )
        _deployFirstGeneration(orch, genOrch)

        orch.run_iteration()
        _approve(orch)
        health["armed"] = True
        settled = genOrch.canaryCheckpoint(2, readings={})
        assert settled.status == GenerationStatus.ROLLED_BACK.value
        assert "max_error_rate" in (settled.deployment.canaryConclusion or "")

    def test_healthCallbackSuccessDropBreachTriggersRollback(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        health = {"armed": False}

        def _health():
            if not health["armed"]:
                return None
            return {"success_rate": 0.75, "baseline_success_rate": 0.9}

        genOrch = _attach(
            orch,
            _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
            canaryWindowSeconds=0.3,
            canaryHealthCallback=_health,
        )
        _deployFirstGeneration(orch, genOrch)

        orch.run_iteration()
        _approve(orch)
        health["armed"] = True
        settled = genOrch.canaryCheckpoint(2, readings={})
        assert settled.status == GenerationStatus.ROLLED_BACK.value
        assert "min_success_rate_drop" in (settled.deployment.canaryConclusion or "")

    def test_noHealthCallbackMeansThresholdsNotJudged(self, tmp_path, monkeypatch):
        """默认无回调：阈值不参与判定（无生产错误率信号源，不造假信号）；
        注入读数也不命中 should_rollback 时，世代继续停留 canary。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=60)

        orch.run_iteration()
        _approve(orch)
        settled = genOrch.canaryCheckpoint(1, readings={})
        assert settled.status == GenerationStatus.CANARY.value


# ── 世代账本：canary→rolledBack 转移与窗口起点留痕 ────────────────


class TestLedgerCanaryRollback:
    def _canaryGeneration(self, ledger: GenerationLedger):
        gen = ledger.openGeneration(
            None,
            [SignalRef(kind="feedback", ref="tool_memory", summary="s")],
            [ChangeRef(targetId="rsi.parameterFamily", kind="parameter", ref="p: 1 -> 2")],
            "abc1234",
        )
        ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed("g0")})
        ledger.recordVerdicts(
            gen.generationNo,
            {"overall": GateVerdict.passed("overall"), "g1": GateVerdict.passed("g1")},
        )
        ledger.recordDecision(gen.generationNo, DecisionRef(kind="approval", approver="admin"))
        return gen

    def _deployRoot(self, ledger: GenerationLedger):
        """根代走合法状态机到 deployed（proposed→shadowTesting→gated→canary→deployed）。"""
        gen = ledger.openGeneration(None, [], [], "abc1234")
        ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed("g0")})
        ledger.recordVerdicts(gen.generationNo, {"overall": GateVerdict.passed("overall")})
        ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))
        ledger.markDeployed(gen.generationNo, DeploymentRef(canaryConclusion="父代平稳"))
        return gen

    def test_canaryCanRollBackWithReason(self):
        ledger = GenerationLedger()
        parent = self._deployRoot(ledger)
        gen = self._canaryGeneration(ledger)

        ledger.annotateCanaryWindow(gen.generationNo, "2026-11-21T00:00:00+00:00")
        ledger.markRolledBack(
            gen.generationNo, restoredTo=parent.generationNo, reason="窗内负增益越界"
        )

        rolled = ledger.get(gen.generationNo)
        assert rolled.status == GenerationStatus.ROLLED_BACK.value
        assert rolled.deployment.rolledBackTo == parent.generationNo
        assert "窗内负增益越界" in rolled.deployment.canaryConclusion
        assert ledger.currentBaseline().generationNo == parent.generationNo

    def test_canaryStartedAtPersistsThroughRoundtrip(self, tmp_path, monkeypatch):
        state = tmp_path / "gens" / "generations.json"
        monkeypatch.setenv(ENV_GENERATIONS, str(state))
        ledger = GenerationLedger()
        gen = self._canaryGeneration(ledger)
        ledger.annotateCanaryWindow(gen.generationNo, "2026-11-21T00:00:01+00:00")

        readback = GenerationLedger()
        loaded = readback.get(gen.generationNo)
        assert loaded.deployment.canaryStartedAt == "2026-11-21T00:00:01+00:00"
        assert loaded.status == GenerationStatus.CANARY.value

    def test_annotateCanaryWindowRequiresCanaryState(self):
        ledger = GenerationLedger()
        gen = ledger.openGeneration(None, [], [], "abc1234")
        with pytest.raises(GenerationTransitionError):
            ledger.annotateCanaryWindow(gen.generationNo, "2026-11-21T00:00:00+00:00")


# ── 边界诚实：根代无父代可回滚时拒绝而非伪装回滚 ──────────────────


class TestRootGenerationEdge:
    def test_rootCanaryFailureWithoutParentRejectsHonestly(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadow"), canaryWindowSeconds=60)

        orch.run_iteration()
        _approve(orch)
        settled = genOrch.canaryCheckpoint(1, readings={"gain": -1.0})

        # 根代无父代世代可指认：走 markRejected 诚实留痕（不伪装 rolledBackTo）
        assert settled.status == GenerationStatus.REJECTED.value
        assert "无父代可回滚" in (settled.decision.reason or "")
        # 参数仍恢复到应用前实值（恢复动作不因无父代档案而跳过）
        assert _toolMemoryThreshold(orch) == 0.85
