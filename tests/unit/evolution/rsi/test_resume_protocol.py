# -*- coding: utf-8 -*-
"""P0-③ 进化任务断点续跑协议（reference_af 对照批）红灯测试。

对照 Agent-S4 driver.py 的 dispatch_log + 孤儿回收 + 幂等重放纪律。本仓缺口：
世代账本虽落盘，但「轮次→世代映射」与「金丝雀观测窗运行态」（窗长/快照/单调
起点）只在内存——进程重启后：

1. canary 世代**永久卡死**：参数已应用（受限发布中）却无人观测/晋升/回滚
   （observeOpenCanaries 只遍历内存窗表，重启后为空）；
2. gated/rejected 世代**门禁被绕过**：gateManualApproval / autoApplyAllowed
   查不到世代即放行（重启把门禁打穿）；
3. 影子隔离根（neurovaShadow-*）成**孤儿目录**：验证中途崩溃无人回收。

契约（本批落地）：
- ``GenerationOrchestrator.resumeInterrupted()``：从账本幂等重放——canary 窗
  重新在观测（canaryReadout 可见），检查点照常结算（窗满晋升 / 越界自动回滚，
  **回滚快照从账本恢复**，不因重启失效）；gated/rejected 世代重新对本轮可见
  （门禁不被重启绕过）；孤儿影子根清扫（只认前缀、只清上代进程的）。
- 重复调用 resumeInterrupted 不重复挂窗（幂等）。
- ``EvolutionJobQueue.staleRunningJobs()``：running 超租约的卡死作业只读面
  （S4 dispatch_log 的可见性对应物），recover_stale 修复后清零。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.job_queue import EvolutionJobQueue
from neurova.evolution.rsi.gate_verdict import STATE_FAILED, STATE_PASSED, GateVerdict
from neurova.evolution.rsi.generation_ledger import (
    GenerationLedger,
    GenerationStatus,
)
from neurova.evolution.rsi.generation_orchestrator import GenerationOrchestrator
from neurova.evolution.rsi.orchestrator import RSIManualApplyError, RSIOrchestrator
from neurova.evolution.rsi.shadow_verify import ShadowRunResult
from neurova.evolution.rsi.survival_probe import CRITERION_ORDER

ENV_GENERATIONS = "NEUROVA_EVOLUTION_GENERATIONS"


@pytest.fixture(autouse=True)
def _cleanGenerationsEnv(monkeypatch):
    """默认摘掉世代账本 env：任何用例都不许隐式写仓库 data/（状态污染防线）。"""
    monkeypatch.delenv(ENV_GENERATIONS, raising=False)
    yield


# ── 基座（与 test_canaryWindowDrill 同款四闭环真实子系统） ──────────


def _buildSystems() -> dict:
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


def _writePhase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int) -> None:
    path = tmp_path / "governance_settings.json"
    path.write_text(
        json.dumps({"rsi_phase": phase, "conversation_rules_enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))


def _buildOrchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int = 1):
    _writePhase(tmp_path, monkeypatch, phase)
    systems = _buildSystems()
    return RSIOrchestrator(
        sleep_system=systems["sleep"],
        emotion_system=systems["emotion"],
        experience_system=systems["experience"],
        tool_memory_system=systems["tool_memory"],
        agent_id="resume-drill",
    )


def _toolMemoryThreshold(orch: RSIOrchestrator) -> float:
    params = {
        p.name: p.current_value
        for p in orch.integration_manager.get_optimizable_parameters()["tool_memory"]
    }
    return params["muscle_memory_threshold"]


class _StubShadowVerify:
    """全绿影子验证桩（与 test_generationOrchestrator 同形）。"""

    def __init__(self, *, tmpRoot: Path):
        self._tmpRoot = tmpRoot
        self._tmpRoot.mkdir(parents=True, exist_ok=True)

    def verify(self, change) -> ShadowRunResult:
        verdicts = {
            name: GateVerdict.passed(f"{name} 通过（桩）") for name in CRITERION_ORDER
        }
        verdicts["parameterApply"] = GateVerdict.passed("parameterApply 通过（桩）")
        verdicts["g2Business"] = GateVerdict.passed("g2Business 通过（桩）")
        verdicts["g3Regression"] = GateVerdict.passed("g3Regression 通过（桩）")
        return ShadowRunResult(
            changeId=change.changeId,
            kind=change.kind,
            verdicts=verdicts,
            overall=STATE_PASSED,
            durationMs=0,
            dataRoot=str(self._tmpRoot),
            workspace="stub",
        )


class _CrashingShadowVerify:
    """verify 直接崩溃的影子桩 → G0 fail-closed → 世代被拒（影子失败自动淘汰）。"""

    def verify(self, change):
        raise RuntimeError("shadow subprocess died")


def _attach(
    orch: RSIOrchestrator,
    shadow,
    *,
    canaryWindowSeconds: float = 0,
    ledger: GenerationLedger = None,
) -> GenerationOrchestrator:
    genOrch = GenerationOrchestrator(
        rsiOrchestrator=orch,
        shadowVerify=shadow,
        ledger=ledger,
        canaryWindowSeconds=canaryWindowSeconds,
    )
    orch.generationOrchestrator = genOrch
    return genOrch


def _approve(orch: RSIOrchestrator) -> Dict[str, Any]:
    return orch.applyApprovedOptimizations(approved_by="resume-admin")


def _driveToCanary(tmp_path, monkeypatch, state: Path, window: float):
    """跑出一代停在 canary 观测态的世代；返回 (orch, genOrch, state)。"""
    orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
    genOrch = _attach(
        orch,
        _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
        canaryWindowSeconds=window,
        ledger=GenerationLedger(statePath=state),
    )
    orch.run_iteration()
    outcome = _approve(orch)
    assert outcome["applied_count"] >= 1
    gen = genOrch.generationForRound(1)
    assert gen.status == GenerationStatus.CANARY.value, "前提：世代停在 canary 观测态"
    return orch, genOrch, state


# ── 契约 1：canary 观测窗重启后幂等重放 ─────────────────────────────


class TestCanaryWindowResume:
    def test_window_resumes_and_promotes_after_restart(self, tmp_path, monkeypatch):
        """重启后从账本重挂观测窗；窗满检查点照常晋升——中断的派发被续跑，
        不是永久卡死。"""
        state = tmp_path / "generations.json"
        orch, genOrch, state = _driveToCanary(tmp_path, monkeypatch, state, window=0.2)

        # 模拟进程重启：全新编排器（同账本落盘文件、全新内存态）
        orch2 = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch2 = GenerationOrchestrator(
            rsiOrchestrator=orch2,
            shadowVerify=_StubShadowVerify(tmpRoot=tmp_path / "shadow2"),
            ledger=GenerationLedger(statePath=state),
        )
        readout = genOrch2.resumeInterrupted()
        assert readout["resumedCanaries"] == [1], "canary 窗必须从账本重挂"
        assert genOrch2.canaryReadout()["count"] == 1

        time.sleep(0.25)
        settled = genOrch2.canaryCheckpoint(1, readings={"measure_state": "measured", "gain": 0.0})
        assert settled.status == GenerationStatus.DEPLOYED.value, (
            "重启后续跑检查点：窗满应晋升，而不是世代永久卡死在 canary"
        )
        assert genOrch2.canaryReadout()["count"] == 0
        # 幂等：再次 resume 不重复挂窗/不改变已结算世代
        readout2 = genOrch2.resumeInterrupted()
        assert readout2["resumedCanaries"] == []
        assert genOrch2.canaryReadout()["count"] == 0

    def test_rollback_after_restart_restores_params_from_ledger_snapshot(
        self, tmp_path, monkeypatch
    ):
        """重启后窗内越界 → 自动回滚，且**回滚快照从账本恢复**——参数必须
        恢复父代实值（快照不落盘＝重启后回滚失去恢复源，安全态回不去）。"""
        state = tmp_path / "generations.json"
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(
            orch,
            _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
            canaryWindowSeconds=1.0,
            ledger=GenerationLedger(statePath=state),
        )
        # 第 1 代：窗满晋升为父代基线（与演练二同构，回滚需要可指认的父代）
        orch.run_iteration()
        _approve(orch)
        time.sleep(1.1)
        settled1 = genOrch.canaryCheckpoint(1, readings={"measure_state": "measured", "gain": 0.0})
        assert settled1.status == GenerationStatus.DEPLOYED.value
        parentNo = settled1.generationNo
        parentParam = _toolMemoryThreshold(orch)

        # 第 2 代：批准应用后进入 canary（窗未满，参数已应用）
        orch.run_iteration()
        _approve(orch)
        gen2 = genOrch.generationForRound(2)
        assert gen2.status == GenerationStatus.CANARY.value
        assert gen2.parentNo == parentNo

        # 模拟进程重启：新进程的编排器从默认态起步（其活参数与本进程无关），
        # 以同账本落盘、全新内存重建——回滚恢复源只能是账本里的快照
        orch2 = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch2 = GenerationOrchestrator(
            rsiOrchestrator=orch2,
            shadowVerify=_StubShadowVerify(tmpRoot=tmp_path / "shadow2"),
            ledger=GenerationLedger(statePath=state),
        )
        readout = genOrch2.resumeInterrupted()
        assert readout["resumedCanaries"] == [2], "第 2 代的观测窗必须从账本重挂"

        settled = genOrch2.canaryCheckpoint(2, readings={"gain": -0.5})
        assert settled.status == GenerationStatus.ROLLED_BACK.value
        assert settled.deployment.rolledBackTo == parentNo
        assert _toolMemoryThreshold(orch2) == parentParam, (
            "重启后回滚必须从账本快照恢复参数（否则安全态回不去）"
        )

    def test_resume_is_noop_without_interrupted_state(self, tmp_path, monkeypatch):
        """无在途世代时 resume 是空操作（读数全空），不编造窗口。"""
        state = tmp_path / "generations.json"
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(
            orch,
            _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
            ledger=GenerationLedger(statePath=state),
        )
        readout = genOrch.resumeInterrupted()
        assert readout["resumedCanaries"] == []
        assert readout["restoredRounds"] == []
        assert genOrch.canaryReadout()["count"] == 0


# ── 契约 2：门禁不因重启被绕过 ──────────────────────────────────────


class TestGateSurvivesRestart:
    def test_rejected_generation_still_gates_after_restart(self, tmp_path, monkeypatch):
        """被门禁拒绝的世代，重启后对本轮依然可见：autoApplyAllowed=False、
        人工批准 409——重启不得把门禁打穿。"""
        state = tmp_path / "generations.json"
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(
            orch,
            _CrashingShadowVerify(),
            ledger=GenerationLedger(statePath=state),
        )
        orch.run_iteration()
        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.REJECTED.value, "前提：影子崩溃世代被拒"

        orch2 = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch2 = GenerationOrchestrator(
            rsiOrchestrator=orch2,
            shadowVerify=_StubShadowVerify(tmpRoot=tmp_path / "shadow2"),
            ledger=GenerationLedger(statePath=state),
        )
        genOrch2.resumeInterrupted()
        assert genOrch2.generationForRound(1) is not None, (
            "重启后轮次→世代映射必须从账本恢复（否则门禁被绕过）"
        )
        assert genOrch2.autoApplyAllowed(1) is False
        with pytest.raises(RSIManualApplyError):
            genOrch2.gateManualApproval(roundNo=1, approvedBy="resume-admin")

    def test_gated_generation_remains_approvable_after_restart(
        self, tmp_path, monkeypatch
    ):
        """gated 世代重启后仍可走人工批准通道（裁决照落），不是查无此代放行。"""
        state = tmp_path / "generations.json"
        orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch = _attach(
            orch,
            _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
            ledger=GenerationLedger(statePath=state),
        )
        orch.run_iteration()
        gen = genOrch.generationForRound(1)
        assert gen.status == GenerationStatus.GATED.value, "前提：世代停在 gated 待裁决"

        orch2 = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
        genOrch2 = GenerationOrchestrator(
            rsiOrchestrator=orch2,
            shadowVerify=_StubShadowVerify(tmpRoot=tmp_path / "shadow2"),
            ledger=GenerationLedger(statePath=state),
        )
        genOrch2.resumeInterrupted()
        settled = genOrch2.gateManualApproval(roundNo=1, approvedBy="resume-admin")
        assert settled is not None
        assert settled.status == GenerationStatus.CANARY.value
        assert settled.decision is not None and settled.decision.approver == "resume-admin"


# ── 契约 3：孤儿影子隔离根清扫 ──────────────────────────────────────


class TestOrphanShadowRootSweep:
    def test_resume_sweeps_orphan_shadow_roots(self, tmp_path, monkeypatch):
        """上代进程遗留的 neurovaShadow-* 目录在 resume 时被回收；
        本进程在用的（晚于进程启动）不动。"""
        tempBase = Path(tempfile.gettempdir())
        orphan1 = tempBase / "neurovaShadow-resume-orphan1"
        orphan2 = tempBase / "neurovaShadow-resume-orphan2"
        fresh = tempBase / "neurovaShadow-resume-fresh"
        for d in (orphan1, orphan2, fresh):
            d.mkdir(parents=True, exist_ok=True)
            (d / "probe.txt").write_text("x", encoding="utf-8")
        old = time.time() - 3600
        os.utime(orphan1, (old, old))
        os.utime(orphan2, (old, old))

        try:
            state = tmp_path / "generations.json"
            orch = _buildOrchestrator(tmp_path, monkeypatch, phase=1)
            genOrch = _attach(
                orch,
                _StubShadowVerify(tmpRoot=tmp_path / "shadow"),
                ledger=GenerationLedger(statePath=state),
            )
            readout = genOrch.resumeInterrupted()
            assert readout["sweptShadowRoots"] >= 2
            assert not orphan1.exists(), "上代进程的影子隔离根必须被回收"
            assert not orphan2.exists()
            assert fresh.exists(), "本进程新起的影子根不得误删"
        finally:
            import shutil as _shutil

            for d in (orphan1, orphan2, fresh):
                _shutil.rmtree(d, ignore_errors=True)


# ── 契约 4：作业队列卡死作业只读面 ──────────────────────────────────


class TestJobQueueStaleReadout:
    def test_stale_running_jobs_visible_then_recovered(self, tmp_path):
        """running 超租约的卡死作业必须可见（S4 dispatch_log 的可见性对应物）；
        recover_stale 修复后清零。"""
        q = EvolutionJobQueue(db_path=tmp_path / "jobs.db", lease_seconds=60)
        try:
            q.enqueue("proposal", {"x": 1}, idempotency_key="k1")
            job = q.claim("worker-a")
            assert job is not None
            # 人为把租约拨老：模拟 worker 崩溃后遗留的 running 行
            old = time.time() - 3600
            q._conn.execute(
                "UPDATE evolution_jobs SET locked_at=? WHERE id=?", (old, job["id"])
            )
            q._conn.commit()

            stale = q.staleRunningJobs()
            assert len(stale) == 1
            assert stale[0]["id"] == job["id"]
            assert stale[0]["kind"] == "proposal"
            assert stale[0]["ageSeconds"] >= 3600 - 5

            assert q.recover_stale() == 1
            assert q.staleRunningJobs() == []
        finally:
            q.close()
