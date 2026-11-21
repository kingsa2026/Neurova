"""P1-3 世代编排器接线测试（计划书 §2.2/§2.3/§3.4/§3.5/§6 P1 批 P1-3）。

先红后绿：本文件先于 neurova/evolution/rsi/generation_orchestrator.py 存在，
收集期 ImportError 即红灯；实现转绿后逐条钉住：

1. 一次带候选的迭代 + 人工批准 → 世代记录完整（signals/changes/verdicts/
   decision/status 全链可断言），谱系 parentNo 指向上一部署代；
2. 影子验证 failed → 世代 rejected，且人工批准被拒（参数不被应用）；
3. GateChain G0 短路语义在真实 ShadowVerify 数据下成立（真子进程探针，
   P1-2 注入执行器通道让构建判据真实 failed → 门禁链无 g1-g3 结论）；
4. orchestrator 无 generationOrchestrator 时行为与旧版完全一致（向后兼容）；
5. env 配置 tmp 落盘后世代可读回。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.rsi.gate_verdict import STATE_FAILED, STATE_PASSED, GateVerdict
from neurova.evolution.rsi.generation_ledger import GenerationLedger, GenerationStatus
# 红灯：generation_orchestrator 模块本体尚不存在 → 收集期 ImportError 即红。
from neurova.evolution.rsi.generation_orchestrator import (
    GenerationOrchestrator,
    gitHeadShort,
)
from neurova.evolution.rsi.orchestrator import RSIManualApplyError, RSIOrchestrator
from neurova.evolution.rsi.shadow_verify import ShadowChange, ShadowVerify, ShadowRunResult
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
    """四闭环真实子系统（装配形态对齐 agent_core 生产装配，同 R1 探针基座）。

    tool_memory.muscle_memory_threshold=0.85（生产实值）vs setpoint 0.8：
    当前全仓唯一真实梯度，保证每轮都有候选。
    """
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
        agent_id="gen-test",
    )


def _toolMemoryThreshold(orch: RSIOrchestrator):
    params = {
        p.name: p.current_value
        for p in orch.integration_manager.get_optimizable_parameters()["tool_memory"]
    }
    return params["muscle_memory_threshold"]


class _StubShadowVerify:
    """可编程影子验证桩：不 spawn 子进程，按预置三态返回结论（编排逻辑单测用）。

    结论形状与真实 ShadowRunResult 同构：六项存活判据 + parameterApply +
    g2Business/g3Regression（后两者在真实链路由业务判据回调产出）。
    """

    def __init__(
        self,
        *,
        tmpRoot: Path,
        probeState: str = STATE_PASSED,
        parameterApplyState: str = STATE_PASSED,
        businessState: str = STATE_PASSED,
        regressionState: str = STATE_PASSED,
    ):
        self._tmpRoot = tmpRoot
        self._tmpRoot.mkdir(parents=True, exist_ok=True)
        self._states = {
            "probe": probeState,
            "parameterApply": parameterApplyState,
            "g2Business": businessState,
            "g3Regression": regressionState,
        }
        self.verifiedChanges: list = []

    def _verdict(self, state: str, name: str) -> GateVerdict:
        if state == STATE_PASSED:
            return GateVerdict.passed(f"{name} 通过（桩）")
        if state == STATE_FAILED:
            return GateVerdict.failed(f"{name} 失败（桩）", evidence={"criterion": name})
        return GateVerdict.unevidenced(f"{name} 无证据（桩）", evidence={"criterion": name})

    def verify(self, change) -> ShadowRunResult:
        self.verifiedChanges.append(change)
        verdicts: dict = {}
        for name in CRITERION_ORDER:
            verdicts[name] = self._verdict(self._states["probe"], name)
        verdicts["parameterApply"] = self._verdict(
            self._states["parameterApply"], "parameterApply")
        verdicts["g2Business"] = self._verdict(self._states["g2Business"], "g2Business")
        verdicts["g3Regression"] = self._verdict(self._states["g3Regression"], "g3Regression")
        states = [v.state for v in verdicts.values()]
        if STATE_FAILED in states:
            overall = STATE_FAILED
        elif "unevidenced" in states:
            overall = "unevidenced"
        else:
            overall = STATE_PASSED
        return ShadowRunResult(
            changeId=change.changeId,
            kind=change.kind,
            verdicts=verdicts,
            overall=overall,
            durationMs=0,
            dataRoot=str(self._tmpRoot),
            workspace="stub",
        )


def _attach(orch: RSIOrchestrator, shadow, *, ledger=None) -> GenerationOrchestrator:
    genOrch = GenerationOrchestrator(
        rsiOrchestrator=orch, shadowVerify=shadow, ledger=ledger
    )
    orch.generationOrchestrator = genOrch
    return genOrch


# ── 验收 1：一次带候选的迭代 + 人工批准 → 世代记录完整 ────────────


class TestRoundBecomesGeneration:
    def test_iterationAndApprovalYieldCompleteGeneration(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        stub = _StubShadowVerify(tmpRoot=tmp_path / "shadowStub")
        genOrch = _attach(orch, stub)

        result = orch.run_iteration()
        assert result["optimizations"], "前提：本轮有候选（tool_memory 真实梯度）"

        gen = genOrch.generationForRound(1)
        assert gen is not None, "一次 RSI 迭代必须开出一个世代"
        # 开代要素：信号摘要 / 变更映射 / 基线 commit
        assert gen.basisCommit == gitHeadShort()
        assert re.fullmatch(r"[0-9a-f]{7,40}", gen.basisCommit)
        kinds = {s.kind for s in gen.signals}
        assert "feedback" in kinds and "convergence" in kinds
        feedbackRefs = {s.ref for s in gen.signals if s.kind == "feedback"}
        assert "tool_memory" in feedbackRefs
        assert gen.changes, "优化建议必须映射为变更引用"
        assert all(c.targetId == "rsi.parameterFamily" for c in gen.changes)
        assert any("muscle_memory_threshold" in c.ref for c in gen.changes)
        # 影子验证 + 门禁链在开代时完整执行（§2.2：提案→影子验证→门禁链→裁决），
        # 世代停在 gated 等待人工裁决
        assert gen.status == GenerationStatus.GATED.value
        assert gen.decision is None, "裁决在人工批准时落账"
        for gate in ("g0", "g1", "g2", "g3", "overall"):
            assert gen.verdicts[gate].state == STATE_PASSED
        # 每个候选各过一次影子验证
        assert len(stub.verifiedChanges) == len(result["optimizations"])

        outcome = orch.applyApprovedOptimizations(approved_by="admin1")
        assert outcome["applied_count"] >= 1, "R1 人工批准应用语义保持"

        resolved = genOrch.generationForRound(1)
        assert resolved.status == GenerationStatus.DEPLOYED.value
        assert resolved.decision.kind == "approval"
        assert resolved.decision.approver == "admin1"
        for gate in ("g0", "g1", "g2", "g3", "overall"):
            assert gate in resolved.verdicts, f"门禁链结论缺 {gate}"
            assert resolved.verdicts[gate].state == STATE_PASSED
        assert resolved.deployment is not None and resolved.deployment.promotedAt
        # 参数真的被应用（R1 通道不变）
        assert _toolMemoryThreshold(orch) != 0.85

    def test_nextGenerationLinesOnDeployedParent(self, tmp_path, monkeypatch):
        """谱系：下一代的 parentNo 指向当前生产基线（上一部署代）。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadowStub"))

        orch.run_iteration()
        orch.applyApprovedOptimizations(approved_by="admin1")
        orch.run_iteration()
        orch.applyApprovedOptimizations(approved_by="admin2")

        gen1 = genOrch.generationForRound(1)
        gen2 = genOrch.generationForRound(2)
        assert gen1.parentNo is None
        assert gen2.parentNo == gen1.generationNo
        assert gen2.status == GenerationStatus.DEPLOYED.value


# ── 验收 2：影子验证 failed → 世代 rejected 且参数不被应用 ─────────


class TestShadowFailureVeto:
    def test_failedShadowRejectsGenerationAndBlocksApply(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        stub = _StubShadowVerify(tmpRoot=tmp_path / "shadowStub", probeState=STATE_FAILED)
        genOrch = _attach(orch, stub)

        result = orch.run_iteration()
        assert result["optimizations"]

        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.REJECTED.value
        assert gen.verdicts["g0"].state == STATE_FAILED
        assert gen.decision is not None and gen.decision.kind == "rejected"

        before = _toolMemoryThreshold(orch)
        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="admin1")
        assert err.value.status_code == 409
        assert "拒绝" in str(err.value)
        # 参数不被应用
        assert _toolMemoryThreshold(orch) == before

    def test_businessGateFailureAlsoRejects(self, tmp_path, monkeypatch):
        """G2 业务判据 failed → 门禁链 overall failed → 世代 rejected + 拒绝应用。"""
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        stub = _StubShadowVerify(
            tmpRoot=tmp_path / "shadowStub", businessState=STATE_FAILED)
        genOrch = _attach(orch, stub)

        orch.run_iteration()
        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.REJECTED.value
        assert gen.verdicts["g2"].state == STATE_FAILED
        assert gen.verdicts["overall"].state == STATE_FAILED

        before = _toolMemoryThreshold(orch)
        with pytest.raises(RSIManualApplyError):
            orch.applyApprovedOptimizations(approved_by="admin1")
        assert _toolMemoryThreshold(orch) == before


# ── 验收 3：GateChain G0 短路语义在真实 ShadowVerify 数据下成立 ────


class TestGateChainShortCircuitWithRealShadow:
    @pytest.mark.timeout(900)
    def test_realShadowBuildFailureShortCircuitsGateChain(self, tmp_path, monkeypatch):
        """真子进程影子验证（P1-2 注入执行器通道）让构建判据真实 failed →
        G0 聚合 failed → 门禁链短路（无 g1/g2/g3 结论）→ 世代 rejected，
        人工批准被拒、参数不应用。"""
        helperDir = tmp_path / "genExecutors"
        helperDir.mkdir(parents=True)
        (helperDir / "genPoisonExecutor.py").write_text(
            "def apply(change):\n"
            "    import neurova.api.app as appModule\n"
            "    def boom(*args, **kwargs):\n"
            "        raise RuntimeError('影子注入：装配爆炸')\n"
            "    appModule.create_app = boom\n",
            encoding="utf-8",
        )

        class _PoisonedRealShadow:
            """真实 ShadowVerify 的薄包装：仅给候选挂上测试注入执行器引用，
            验证全程走真子进程 + 真探针（P1-2 的离线注桩通道，不真改仓库）。"""

            def __init__(self, inner: ShadowVerify, executorRef: str):
                self._inner = inner
                self._executorRef = executorRef

            def verify(self, change):
                poisoned = ShadowChange(
                    changeId=change.changeId,
                    kind="identity",
                    targetId=change.targetId,
                    executorRef=self._executorRef,
                )
                return self._inner.verify(poisoned)

        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        realShadow = _PoisonedRealShadow(
            ShadowVerify(extraSysPath=[str(helperDir)]), "genPoisonExecutor:apply")
        genOrch = _attach(orch, realShadow)

        result = orch.run_iteration()
        assert result["optimizations"]

        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.REJECTED.value
        assert gen.verdicts["g0"].state == STATE_FAILED
        # G0 短路：后续门禁未参评（世代判据里没有 g1/g2/g3 键）
        assert "g1" not in gen.verdicts
        assert "g2" not in gen.verdicts
        assert "g3" not in gen.verdicts
        assert gen.verdicts["overall"].state == STATE_FAILED
        # 影子失败 → 候选自动淘汰：审批被拒、参数不应用
        before = _toolMemoryThreshold(orch)
        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="admin1")
        assert err.value.status_code == 409
        assert _toolMemoryThreshold(orch) == before


# ── 验收 4：无 generationOrchestrator 时行为与旧版完全一致 ──────────


class TestBackwardCompat:
    def test_noneGenerationOrchestratorKeepsLegacyBehavior(self, tmp_path, monkeypatch):
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        assert getattr(orch, "generationOrchestrator", "missing") is None

        result = orch.run_iteration()
        assert result["optimizations"]
        assert result["applied_count"] == 0, "phase 1 手动档不自动应用（旧语义）"
        assert orch.pendingManualOptimizations()

        outcome = orch.applyApprovedOptimizations(approved_by="admin1")
        assert outcome["applied_count"] >= 1
        assert _toolMemoryThreshold(orch) != 0.85
        # 旧返回体没有世代字段（零行为变化）
        assert "generation" not in outcome and "generationNo" not in outcome


# ── 验收 5：env 配置 tmp 落盘后世代可读回 ──────────────────────────


class TestGenerationsPersisted:
    def test_generationsPersistToEnvPathAndReadBack(self, tmp_path, monkeypatch):
        statePath = tmp_path / "gens" / "generations.json"
        monkeypatch.setenv(ENV_GENERATIONS, str(statePath))

        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        # ledger 缺省经 env 解析 → 落 tmp 盘
        genOrch = _attach(orch, _StubShadowVerify(tmpRoot=tmp_path / "shadowStub"))

        orch.run_iteration()
        orch.applyApprovedOptimizations(approved_by="admin1")

        assert statePath.exists()
        readback = GenerationLedger()
        gen = readback.get(1)
        assert gen is not None
        assert gen.status == GenerationStatus.DEPLOYED.value
        assert gen.decision.kind == "approval" and gen.decision.approver == "admin1"
        assert gen.verdicts["overall"].state == STATE_PASSED
        assert readback.currentBaseline().generationNo == 1


# ── 失败诚实：世代管线异常不阻断 RSI 迭代本身 ──────────────────────


class TestPipelineFailureHonesty:
    def test_explodingLedgerDoesNotBlockIteration(self, tmp_path, monkeypatch):
        class _ExplodingLedger:
            def __getattr__(self, name):
                raise RuntimeError("世代账本爆炸（测试注入）")

        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(
            orch,
            _StubShadowVerify(tmpRoot=tmp_path / "shadowStub"),
            ledger=_ExplodingLedger(),
        )

        result = orch.run_iteration()  # 不抛
        assert result["optimizations"]
        assert genOrch.lastPipelineError, "管线故障必须留痕"

        # 无世代档案 → 人工通道不设 veto，仍走 R1 原语义
        outcome = orch.applyApprovedOptimizations(approved_by="admin1")
        assert outcome["applied_count"] >= 1
