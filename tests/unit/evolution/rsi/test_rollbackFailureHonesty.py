"""EVO-02：回滚失败不得假报成功（全仓审计批次 B）。

审计点（neurova/evolution/rsi/orchestrator.py）：
- ``_restore_optimizable`` 逐参数调 ``apply_optimization()`` 却丢弃布尔返回值；
- 回滚块无论恢复是否成功都置 ``rolled_back=True``、``applied_count=0``、
  ``gain=0.0`` —— 账本显示"已回滚"，线上却仍带着被判有害的参数。

判据：回滚结果参与状态机——恢复失败时 ``rolled_back=False``、
``rollback_failed=True``，实测增益与在用参数数不被清零，提案登记与世代
账本如实记"回滚失败"，rollback_manager 不留"已执行的回滚"假账。

故障注入全部走真实代码路径：系统侧以真实子类拒绝写入（``setattr`` 抛错，
``apply_optimization`` 捕获后如实返回 False），不用 MagicMock 冒充业务对象。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.rsi.gate_verdict import STATE_PASSED, GateVerdict
from neurova.evolution.rsi.generation_ledger import GenerationStatus
from neurova.evolution.rsi.generation_orchestrator import GenerationOrchestrator
from neurova.evolution.rsi.orchestrator import RSIOrchestrator
from neurova.evolution.rsi.shadow_verify import ShadowRunResult
from neurova.evolution.rsi.survival_probe import CRITERION_ORDER
from tests.unit.evolution.conftest import MeasuredHarness

ENV_GENERATIONS = "NEUROVA_EVOLUTION_GENERATIONS"


@pytest.fixture(autouse=True)
def _cleanGenerationsEnv(monkeypatch):
    """摘掉世代账本 env：任何用例都不许隐式写仓库 data/（状态污染防线）。"""
    monkeypatch.delenv(ENV_GENERATIONS, raising=False)
    yield


class _RestoreRejectingToolMemory(ToolMemoryIntegration):
    """真实 ToolMemoryIntegration 子类：``rejectParamWrites`` 置位后拒绝参数写入。

    模拟"回滚执行时系统侧写失败"这一真实故障形态：restore 的 ``setattr``
    抛错，``apply_optimization`` 捕获后如实返回 False，参数保持在被应用后
    的有害值上。
    """

    def __init__(self, *args: Any, **kwargs: Any):
        object.__setattr__(self, "rejectParamWrites", False)
        super().__init__(*args, **kwargs)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "rejectParamWrites", False):
            raise RuntimeError(f"模拟回滚期间系统拒绝写入: {name}")
        object.__setattr__(self, name, value)


class _SabotageOnSecondMeasure(MeasuredHarness):
    """第二次实测（发生在应用之后、回滚之前）时让系统进入拒绝写入态。"""

    def __init__(self, scores, target: _RestoreRejectingToolMemory):
        super().__init__(scores)
        self._target = target
        self._calls = 0

    def run(self, live_params: Dict[str, Any]) -> Dict[str, Any]:
        outcome = super().run(live_params)
        self._calls += 1
        if self._calls >= 2:
            self._target.rejectParamWrites = True
        return outcome


class _StubShadowVerify:
    """可编程影子验证桩（与 test_canaryWindowDrill 同形，全绿默认）。"""

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


def _buildOrchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
                       phase: int = 1, evalHarness: Optional[Any] = None):
    """真实四系统装配（与 test_r1_manual_apply_channel 同基座）。

    返回 (编排器, tool_memory 系统本身)；``evalHarness`` 非空时注入评测替身。
    """
    path = tmp_path / "governance_settings.json"
    path.write_text(
        json.dumps({"rsi_phase": phase, "conversation_rules_enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))
    weights = AdaptiveToolWeights()
    for _ in range(7):
        weights.update_weight("web_fetch", True)
    for _ in range(3):
        weights.update_weight("web_fetch", False)
    toolMemory = _RestoreRejectingToolMemory(
        memory_layer=None,
        muscle_memory=None,
        tool_weights=weights,
        confidence_threshold=0.8,
        temperature_threshold=30.0,
        muscle_memory_threshold=0.85,
    )
    orch = RSIOrchestrator(
        sleep_system=SleepConsolidation(),
        emotion_system=EmotionModule(),
        experience_system=ExperienceFeedback(),
        tool_memory_system=toolMemory,
        agent_id="evo02-test",
    )
    if evalHarness is not None:
        orch._eval_harness = evalHarness
    return orch, toolMemory


def _toolMemoryThreshold(orch: RSIOrchestrator):
    params = {
        p.name: p.current_value
        for p in orch.integration_manager.get_optimizable_parameters()["tool_memory"]
    }
    return params["muscle_memory_threshold"]


class TestRollbackFailureHonesty:
    def test_restoreFailureIsNotReportedAsRolledBack(self, tmp_path, monkeypatch):
        """恢复失败时不得置 rolled_back=True：回滚结果参与状态机。

        前置：优化真被应用、实测增益为负触发回滚判据；此刻系统拒绝写入，
        恢复必然失败。旧实现无视恢复结果照报 rolled_back=True 并清零
        applied_count/gain——账本显示已恢复，线上仍带有害参数。
        """
        orch, toolMemory = _buildOrchestrator(tmp_path, monkeypatch)
        orch._eval_harness = _SabotageOnSecondMeasure([1.0, 0.0], toolMemory)
        orch.run_iteration()

        outcome = orch.applyApprovedOptimizations(approved_by="evo02-admin")

        # ── 前提咬合（红绿两态都须成立，证明场景真的走到了回滚段）──
        assert outcome["attempted"] is True, outcome
        assert outcome["applied_results"][0]["applied"] is True, outcome
        assert outcome["eval"]["after"]["state"] == "measured", outcome
        # 系统拒绝写入 ⇒ 恢复没成功：有害参数（0.84）仍在线上
        assert _toolMemoryThreshold(orch) != 0.85, (
            "参数被恢复到 0.85——与'系统拒绝写入'的注入前提矛盾"
        )
        # ── 判据（旧实现在此红灯）──
        # 1. 恢复失败不得假报"已回滚"
        assert outcome["rolled_back"] is False, (
            "恢复失败仍报 rolled_back=True——账本显示已恢复，线上仍带有害参数"
        )
        # 2. 失败必须显式暴露（专用字段，不与成功态混同）
        assert outcome["rollback_failed"] is True, outcome
        # 3. 回滚失败 = 有害参数仍在应用态：applied_count 不得被假回滚清零
        assert outcome["applied_count"] >= 1, outcome
        # 4. 实测到的负增益是事实，不得被假回滚清成 0
        assert outcome["gain"] < 0, outcome
        # 5. 提案登记如实记"回滚失败"，不落 rolled_back/applied 态
        readout = orch._roundProposalsReadout()
        assert readout["state"] == "rollback_failed", readout
        # 6. rollback_manager 不留"已执行的回滚"假账
        assert orch.rollback_manager.get_rollback_history() == [], (
            "回滚未成功执行，rollback_manager 却记了一笔回滚历史"
        )

    def test_canaryRollbackFailureIsRecordedHonestlyInLedger(self, tmp_path, monkeypatch):
        """金丝雀越界自动回滚失败时，世代账本不得记 markRolledBack（假恢复）。"""
        orch, toolMemory = _buildOrchestrator(tmp_path, monkeypatch)
        genOrch = GenerationOrchestrator(
            rsiOrchestrator=orch,
            shadowVerify=_StubShadowVerify(tmpRoot=tmp_path / "shadow"),
            canaryWindowSeconds=0.3,
        )
        orch.generationOrchestrator = genOrch

        # 第 1 代：窗满晋升，成为父代基线
        orch.run_iteration()
        orch.applyApprovedOptimizations(approved_by="evo02-admin")
        time.sleep(0.35)
        genOrch.canaryCheckpoint(1, readings={"measure_state": "measured", "gain": 0.0})
        parentNo = genOrch.generationLedger().currentBaseline().generationNo
        parentParam = _toolMemoryThreshold(orch)
        assert parentNo == 1

        # 第 2 代：批准应用后进 canary 窗（参数已应用，受限发布）
        orch.run_iteration()
        orch.applyApprovedOptimizations(approved_by="evo02-admin")
        gen2 = genOrch.generationForRound(2)
        assert gen2.status == GenerationStatus.CANARY.value
        canaryParam = _toolMemoryThreshold(orch)
        assert canaryParam != parentParam, "前提：金丝雀窗内参数已应用"

        # 窗内注入负增益读数触发自动回滚，但系统此刻拒绝写入 → 恢复必然失败
        toolMemory.rejectParamWrites = True
        settled = genOrch.canaryCheckpoint(2, readings={"gain": -0.5})

        # 判据 1：恢复失败不得记"已回滚到父代"（假恢复）
        assert settled.status != GenerationStatus.ROLLED_BACK.value, (
            "回滚执行失败，世代账本却记了 markRolledBack——账本显示已恢复、"
            "线上仍带有害参数"
        )
        # 判据 2：失败显式留痕（拒绝留档 + 理由点名回滚执行失败）
        assert settled.status == GenerationStatus.REJECTED.value, settled.status
        reason = str(getattr(settled.decision, "reason", ""))
        assert "回滚执行失败" in reason and "有害参数仍在线上" in reason, settled.decision
        # 判据 3：有害参数仍在线上
        assert _toolMemoryThreshold(orch) == canaryParam
        # 判据 4：rollback_manager 不留假账
        assert orch.rollback_manager.get_rollback_history() == []
