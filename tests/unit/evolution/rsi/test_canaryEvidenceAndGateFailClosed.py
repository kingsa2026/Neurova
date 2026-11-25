"""EVO-03：安全门禁缺证据不得放行 / 世代治理状态必须可跨重启。

审计证据（2026-11-25）：
- 金丝雀观测窗空读数（未提供任何实测证据）窗满仍晋升；
- 世代管线已挂接但本轮无世代档案时，人工批准与自动档均放行；
- 世代账本默认纯内存，重启丢失治理状态。

判据（红 → 绿）：
1. 无读数 / 空读数窗满 → 保持 canary，不晋升；有实测证据才晋升；
2. 已挂接世代管线且无本轮档案 → gateManualApproval 409、autoApplyAllowed False；
3. 生产装配（wireAgentRsi）的世代账本落到数据根持久化路径，env 可覆盖。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.evolution.rsi.generation_orchestrator import GenerationOrchestrator
from neurova.evolution.rsi.orchestrator import RSIManualApplyError
from neurova.evolution.rsi.shadow_verify import ShadowRunResult, ShadowVerify
from neurova.evolution.rsi.survival_probe import CRITERION_ORDER

from tests.unit.evolution.conftest import _default_systems


class _StubShadowVerify:
    """影子验证桩：六判据全绿（与 canary 演练同形）。"""

    def verify(self, change) -> ShadowRunResult:
        verdicts = {name: GateVerdict.passed(f"{name} 通过（桩）") for name in CRITERION_ORDER}
        verdicts["parameterApply"] = GateVerdict.passed("参数应用通过（桩）")
        verdicts["g2Business"] = GateVerdict.passed("业务判据通过（桩）")
        return ShadowRunResult(
            changeId=change.changeId,
            kind=change.kind,
            verdicts=verdicts,
            overall="passed",
            durationMs=0,
            dataRoot="stub://data",
            workspace="stub://ws",
        )


def _attach(orch, *, window=0.15):
    genOrch = GenerationOrchestrator(
        rsiOrchestrator=orch,
        shadowVerify=_StubShadowVerify(),
        ledger=None,  # 测试默认内存账本（不改共享状态）
        canaryWindowSeconds=window,
    )
    orch.generationOrchestrator = genOrch
    return genOrch


class TestCanaryPromotionRequiresEvidence:
    def test_emptyReadingsNeverPromoteEvenAfterWindow(self, rsi_probe_factory):
        probe = rsi_probe_factory(rsi_phase=1)
        orch = probe.orchestrator
        genOrch = _attach(orch)

        orch.run_iteration()
        orchid = orch.applyApprovedOptimizations(approved_by="evo03-admin")
        assert orchid["applied_count"] >= 1
        assert genOrch.generationForRound(1).status == "canary"

        time.sleep(0.2)
        noReadings = genOrch.canaryCheckpoint(1)
        assert noReadings.status == "canary", "无读数窗满不得晋升"
        emptyReadings = genOrch.canaryCheckpoint(1, readings={})
        assert emptyReadings.status == "canary", "空读数窗满不得晋升"

        measured = genOrch.canaryCheckpoint(
            1, readings={"measure_state": "measured", "gain": 0.0}
        )
        assert measured.status == "deployed", "有实测证据且窗满应正常晋升"


class TestGenerationGateFailClosed:
    def test_manualApprovalWithoutGenerationArchiveRejected(self, rsi_probe_factory):
        probe = rsi_probe_factory(rsi_phase=1)
        genOrch = _attach(probe.orchestrator)

        with pytest.raises(RSIManualApplyError) as err:
            genOrch.gateManualApproval(roundNo=99, approvedBy="evo03-admin")
        assert err.value.status_code == 409
        assert "世代档案" in str(err.value)

    def test_autoApplyWithoutGenerationArchiveDenied(self, rsi_probe_factory):
        probe = rsi_probe_factory(rsi_phase=1)
        genOrch = _attach(probe.orchestrator)

        assert genOrch.autoApplyAllowed(99) is False


class TestGenerationLedgerPersistenceWiring:
    def test_resolverFallsBackToDataRootAndEnvOverrides(self, tmp_path, monkeypatch):
        from neurova.evolution.rsi.generation_ledger import (
            resolveGenerationsPersistencePath,
        )

        monkeypatch.delenv("NEUROVA_EVOLUTION_GENERATIONS", raising=False)
        defaultPath = resolveGenerationsPersistencePath()
        assert defaultPath is not None, "生产默认必须落盘（治理状态不得随重启丢失）"
        assert defaultPath.name == "rsi_generations.json"

        override = tmp_path / "generations.json"
        monkeypatch.setenv("NEUROVA_EVOLUTION_GENERATIONS", str(override))
        assert resolveGenerationsPersistencePath() == override

    def test_wireAgentRsiMountsPersistentLedger(self, monkeypatch):
        from neurova.evolution.rsi.agent_wiring import wireAgentRsi

        monkeypatch.delenv("NEUROVA_EVOLUTION_GENERATIONS", raising=False)
        systems = _default_systems(None)
        evolution = SimpleNamespace(experience_feedback=systems["experience"])
        agent = SimpleNamespace(
            config=SimpleNamespace(name="evo03-wire", agent_id="evo03-wire"),
            memory_manager=SimpleNamespace(_emotion_module=systems["emotion"]),
            sleep_consolidation=systems["sleep"],
            evolution=evolution,
            tool_memory=systems["tool_memory"],
            temperature_engine=None,
        )

        wireAgentRsi(agent)

        genOrch = agent.rsi_orchestrator.generationOrchestrator
        assert genOrch is not None
        assert genOrch.generationLedger().statePath is not None, (
            "生产装配必须挂载持久化账本；纯内存账本重启即丢治理状态"
        )
        assert genOrch._shadowVerify is None or isinstance(genOrch._shadowVerify, ShadowVerify)