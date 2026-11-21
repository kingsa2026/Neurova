"""R1 手动批准应用通道（递归自进化第一期 R1 卡）。

背景（2026-11-21 实测 data/evolution/rsi_summaries.jsonl：1018 条迭代 0 次应用）：
- phase=1（手动档）下 `can_auto_execute("low")=False`，run_iteration 的应用段
  （apply + 前后实测 + 回滚判定）整体被跳过 ⇒ measure_state 恒 not_attempted；
- phase 1 的语义是"生成优化建议，人工审批"，但参数优化没有人工批准入口，
  提案产出后无处落地 ⇒ 闭环从未咬合。

本文件钉 R1 的判据：
1. 扩信号后至少一个参数族能产出合法步进候选（tool_memory.muscle_memory_threshold
   生产实值 0.85 vs setpoint 0.8，当前唯一真实梯度）；
2. phase 1 下 run_iteration 产出提案但不自动应用、不做测量（phase 语义保持）；
3. 人工批准后走与自动档**同一份**"应用→前后实测→回滚判定"实现，
   产出 applied_count≥1 且 eval before/after 均 measured（gain_evidenced）；
4. 通道守卫：无提案/重复应用/观察期/债务闸 409，越界 optimization_id 422；
5. collect_feedback_signals 接通既有真实读数源（tool_weights 真实成败计数、
   EKB 质量快照、运行台账终态计数），信号不再只有占位/空读数。

阶段一律经治理设置文件进入（conftest 规则 1：禁止私赋 deployment phase）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.rsi.orchestrator import RSIOrchestrator


def _write_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int) -> None:
    """阶段经治理设置进入（生产同构路径，替代私赋 phase）。"""
    path = tmp_path / "governance_settings.json"
    path.write_text(
        json.dumps({"rsi_phase": phase, "conversation_rules_enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))


def _build_systems() -> dict:
    """四闭环真实子系统，装配形态对齐 agent_core 生产装配。

    - tool_memory.muscle_memory_threshold=0.85：AgentConfig 生产默认
      （agent_core.py:237），与 setpoint 0.8 构成当前唯一真实梯度；
    - tool_weights 注入真实成败计数（web_fetch 7 成 3 败），供扩信号读数。
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


def _build_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int) -> RSIOrchestrator:
    _write_phase(tmp_path, monkeypatch, phase)
    systems = _build_systems()
    return RSIOrchestrator(
        sleep_system=systems["sleep"],
        emotion_system=systems["emotion"],
        experience_system=systems["experience"],
        tool_memory_system=systems["tool_memory"],
        agent_id="r1-test",
    )


class TestPhaseOneKeepsProposalsPending:
    def test_run_produces_candidate_but_never_auto_applies(self, tmp_path, monkeypatch):
        """phase 1：候选照产、不自动应用、不做测量——手动档语义保持。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)

        result = orch.run_iteration()

        assert result["optimizations"], "扩源后至少一族（tool_memory）要能产出合法步进候选"
        assert result["applied_count"] == 0, "phase 1 手动档不得自动应用任何优化"
        assert result["eval"]["before"] is None and result["eval"]["after"] is None, (
            "未应用就没有前后测量——not_attempted 的根因是应用段未执行，不是评测集坏了"
        )
        family = result["family_attribution"]["by_family"]["tool_memory"]
        assert family["status"] == "proposed_not_applied", family

    def test_proposals_are_registered_for_manual_approval(self, tmp_path, monkeypatch):
        """本轮产出的优化必须登记成待批提案（带 optimization_id），这是人工通道的数据源。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        result = orch.run_iteration()

        pending = orch.pendingManualOptimizations()
        assert len(pending) == len(result["optimizations"]) >= 1
        produced_ids = {o["optimization_id"] for o in pending}
        assert len(produced_ids) == len(pending), "optimization_id 必须唯一可寻址"
        assert all(o.get("application_state") == "pending" for o in pending)


class TestManualApplyChannel:
    def test_approved_apply_measures_before_and_after(self, tmp_path, monkeypatch):
        """人工批准 → 与自动档同一份应用段执行：applied≥1 且前后均 measured。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()

        outcome = orch.applyApprovedOptimizations(approved_by="admin1")

        assert outcome["applied_count"] >= 1, outcome
        assert outcome["approved_by"] == "admin1"
        before = outcome["eval"]["before"]
        after = outcome["eval"]["after"]
        assert before is not None and before.get("state") == "measured", before
        assert after is not None and after.get("state") == "measured", after
        assert outcome["gain_evidenced"] is True, "前后均 measured 时增益必须有证据"
        assert outcome["rolled_back"] is False
        # 回滚判据在位且本轮未触发（非负增益不回滚）
        assert orch.rollback_manager.get_rollback_history() == []
        # 参数真的动了（唯一梯度被应用）
        params = {
            p.name: p.current_value
            for p in orch.integration_manager.get_optimizable_parameters()["tool_memory"]
        }
        assert params["muscle_memory_threshold"] != 0.85
        # 应用后提案被消费，不得重复应用
        assert orch.pendingManualOptimizations() == []

    def test_second_apply_is_rejected_409(self, tmp_path, monkeypatch):
        from neurova.evolution.rsi.orchestrator import RSIManualApplyError

        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()
        orch.applyApprovedOptimizations(approved_by="admin1")

        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="admin2")
        assert err.value.status_code == 409

    def test_unknown_optimization_id_is_422_and_consumes_nothing(self, tmp_path, monkeypatch):
        from neurova.evolution.rsi.orchestrator import RSIManualApplyError

        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()

        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(
                optimization_ids=["opt-does-not-exist"], approved_by="admin1"
            )
        assert err.value.status_code == 422
        assert orch.pendingManualOptimizations(), "越界请求不得消费待批提案"

    def test_apply_without_pending_round_is_409(self, tmp_path, monkeypatch):
        from neurova.evolution.rsi.orchestrator import RSIManualApplyError

        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)

        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="admin1")
        assert err.value.status_code == 409

    def test_phase0_run_promotes_then_manual_apply_applies(self, tmp_path, monkeypatch):
        """相位语义：phase 0（观察期）首轮迭代不应用任何东西，但会按晋升判据
        自动进 phase 1（0→1 无证据门槛，controller 既有设计）；此后人工批准
        应用即 phase 1 的合法路径——通道不另设第二道相位闸。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=0)
        orch.run_iteration()

        assert orch.deployment_controller.get_current_phase() == 1, (
            "phase 0 首轮后应自动晋升 phase 1（controller 既有设计）")
        outcome = orch.applyApprovedOptimizations(approved_by="admin1")
        assert outcome["applied_count"] >= 1
        assert outcome["eval"]["before"]["state"] == "measured"

    def test_debt_gate_blocks_manual_apply_409(self, tmp_path, monkeypatch):
        """反向闸（003 M2）对人工通道同样生效：上次动作代价未清 ⇒ 本次不动作。"""
        from neurova.evolution.rsi.debt_ledger import RsiDebtLedger
        from neurova.evolution.rsi.orchestrator import RSIManualApplyError

        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()
        ledger = RsiDebtLedger(path=tmp_path / "rsi_receipts.jsonl")
        assert ledger.record(
            parameter_path="tool_memory.muscle_memory_threshold",
            old_value=0.85, new_value=0.84, cost=5, repayment=0,
        )
        orch.debt_ledger = ledger

        with pytest.raises(RSIManualApplyError) as err:
            orch.applyApprovedOptimizations(approved_by="admin1")
        assert err.value.status_code == 409
        assert orch.pendingManualOptimizations(), "被债务闸拦下的提案保持待批"


class TestAgentWiring:
    def test_wire_agent_rsi_assembles_all_four_real_systems(self):
        """装配线（wireAgentRsi）在 tool_memory/evolution 就位后调用时，
        四族参数面必须全部可见、零占位——这是生产 1018 轮 placeholder_host 的根治判据。"""
        from types import SimpleNamespace

        from neurova.evolution.closed_loop import EvolutionOrchestrator
        from neurova.evolution.rsi.agent_wiring import wireAgentRsi

        systems = _build_systems()
        evolution = EvolutionOrchestrator()
        agent = SimpleNamespace(
            config=SimpleNamespace(name="w", agent_id="wire-test"),
            memory_manager=SimpleNamespace(_emotion_module=systems["emotion"]),
            sleep_consolidation=systems["sleep"],
            evolution=evolution,
            tool_memory=systems["tool_memory"],
            temperature_engine=None,
        )

        wireAgentRsi(agent)

        assert agent.rsi_orchestrator is not None
        assert evolution.rsi_orchestrator is agent.rsi_orchestrator, "必须注入 evolution 单例"
        manager = agent.rsi_orchestrator.integration_manager
        assert manager.get_placeholder_system_names() == [], "四系统齐全时不得有占位替身"
        counts = {k: len(v) for k, v in manager.get_optimizable_parameters().items()}
        assert counts["tool_memory"] == 4 and counts["experience"] == 3, counts


class TestSignalSourcesExtended:
    def test_tool_memory_signal_carries_real_weight_counts(self, tmp_path, monkeypatch):
        """tool_weights 的真实成败计数进信号——不再是"空史报 0.0 成功率"的假读数。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)

        signals = orch.collect_feedback_signals()

        tw = signals["tool_memory"]["tool_weights"]
        assert tw["observed_success_count"] == 7
        assert tw["observed_failure_count"] == 3
        assert tw["observed_success_rate"] == pytest.approx(0.7)
        assert tw["tracked_tools"] >= 1

    def test_experience_signal_carries_ekb_quality_snapshot(self, tmp_path, monkeypatch):
        """EKB 质量快照（结晶/采纳质量的既有算式源）接进 experience 信号。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)

        signals = orch.collect_feedback_signals()

        ekb = signals["experience"]["experience_kb"]
        assert isinstance(ekb["rows"], int) and ekb["rows"] >= 0
        assert "hit_rate" in ekb and "adoption_success_rate" in ekb

    def test_signals_carry_run_ledger_terminal_counts(self, tmp_path, monkeypatch):
        """运行台账终态计数（agent_run_store.stats 既有源）接入全部真实系统信号。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)

        signals = orch.collect_feedback_signals()

        for system in ("sleep", "emotion", "experience", "tool_memory"):
            rl = signals[system]["run_ledger"]
            assert {"running", "queued", "parked", "terminal"} <= set(rl.keys()), (
                f"{system} 信号缺运行台账终态计数"
            )

    def test_zero_observation_success_rate_is_not_read_as_all_failed(self):
        """空观察史（total_usages=0）的 success_rate=0.0 是"没测过"，
        不得被性能估算读成"全失败"——那是把没测到当成测出来是坏的。"""
        from neurova.evolution.rsi.system_performance import estimate_system_performance

        feedback = {"total_usages": 0, "success_rate": 0.0}
        at_setpoint = {
            "success_bonus": 0.1, "failure_penalty": 0.05,
            "decay_rate": 0.01, "muscle_memory_threshold": 0.8,
        }
        score = estimate_system_performance("tool_memory", feedback, at_setpoint)
        # 基础分中性 0.5 × 0.3 + 参数全在 setpoint 的贴近度 1.0 × 0.7
        assert score == pytest.approx(0.85)
