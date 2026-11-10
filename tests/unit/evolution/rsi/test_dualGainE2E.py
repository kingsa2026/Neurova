# -*- coding: utf-8 -*-
"""B1 真实结局升判据（survey §10.2）：yardstick 从观测面升为 gain 的并列构成。

gain 报告体改双读数（行为地板分＋真实结局对齐分）；回滚判据读两者——
"行为分涨而真实结局对齐崩"必须判否（只涨代理分不再自动安全）。
e2e 轴**只否决不奖励**：对齐崩 → 回滚；对齐涨不单凭它接受（安全地板哲学）。
前置处置：平稳性边界配"分布漂移告警读数"；decay_rate 边界维持
eval_harness 专用用例守（既有，不动）。
"""

import pytest

from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.evolution.rsi.task_yardstick import replay_alignment_score


def _mgr():
    return RSIRollbackManager()


def _stream(*, early_ok=0.8, late_ok=0.2, n=24):
    """时间分半的结局流：前半成功率 early_ok、后半 late_ok（平稳性漂移可控）。"""
    entries = []
    for i in range(n):
        rate = early_ok if i < n // 2 else late_ok
        entries.append((float(i), f"tool_{i % 3}", (i % 10) / 10 < rate))
    return {"t1": [(ts, ok) for ts, _t, ok in entries]}


class TestRollbackReadsE2EAxis:
    def test_proxy_up_but_real_outcome_crash_rolls_back(self):
        """红灯判据本体：行为分涨（CI 确证）而真实结局对齐崩 → 必须判否。"""
        result = _mgr().should_rollback({
            "gain": 0.05,
            "gain_ci": {"lower": 0.02, "upper": 0.08, "n": 6},
            "e2e_gain": -0.3,
        })
        assert result is True, (
            "代理分独自安全了——真实结局对齐崩没被读进判据")

    def test_e2e_improvement_alone_never_accepts(self):
        """e2e 轴只否决不奖励：对齐涨不构成接受信号（对齐涨＋行为分崩仍回滚）。"""
        assert _mgr().should_rollback({
            "gain": -0.05,
            "gain_ci": {"lower": -0.08, "upper": -0.02, "n": 6},
            "e2e_gain": 0.3,
        }) is True, "e2e 涨不该抵消确证的行为分危害"

    def test_e2e_axis_absent_keeps_prior_behavior(self):
        """e2e 缺席（insufficient_data 形态）不参与判据——读数缺省不参与。"""
        assert _mgr().should_rollback({"gain": 0.05}) is False
        assert _mgr().should_rollback({"gain": 0.05, "e2e_gain": None}) is False


class TestStationarityDriftReadout:
    def test_drift_readout_flags_distribution_shift(self):
        """分布漂移告警读数：前半好后半崩的流必须被点名（平稳性边界的可观测形态）。"""
        readout = replay_alignment_score(
            _stream(early_ok=0.9, late_ok=0.1),
            success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01,
        )
        assert readout["state"] == "measured"
        drift = readout.get("stationarity_drift") or {}
        assert drift.get("value") is not None
        assert drift.get("suspect") is True, (
            f"分布漂移未告警：{drift}——重放的平稳性假设破裂时读数必须说")

    def test_stable_stream_does_not_flag(self):
        readout = replay_alignment_score(
            _stream(early_ok=0.5, late_ok=0.5),
            success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01,
        )
        drift = readout.get("stationarity_drift") or {}
        assert drift.get("suspect") is False, f"平稳流被误报漂移：{drift}"


def test_orchestrator_dual_gain_wiring(tmp_path, monkeypatch):
    """编排器接线：应用轮次后 eval_outcome 携带 e2e_gain，且回滚判据吃到它。"""
    from unittest.mock import MagicMock

    import neurova.evolution.rsi.task_yardstick as yardstick_module
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )

    # 控制 yardstick 读数：before 0.8 → after 0.5（对齐崩）
    e2e_scores = iter([0.8, 0.5])
    monkeypatch.setattr(
        yardstick_module, "measure_tool_selection",
        lambda weights: {"state": "measured", "score": next(e2e_scores),
                         "entries": 40, "tools": 3, "detail": "synthetic"},
        raising=False,
    )
    # 主度量与决策档都走 measured（CI 可算）
    harness_scores = iter([0.5, 0.7])
    monkeypatch.setattr(
        orch, "_measure_performance",
        lambda: (lambda score: (
            setattr(orch, "_last_eval_outcome", {
                "state": "measured", "score": score,
                "cases": [{"id": f"c{i}", "score": score} for i in range(6)],
                "e2e": {"state": "measured", "score": next(e2e_scores),
                        "entries": 40, "tools": 3, "detail": "synthetic"},
            }) or score))(next(harness_scores)),
        raising=False,
    )

    # 造一轮"应用发生"：绕过真实候选生成，直接压一轮前测/后测对齐
    before = orch._measure_performance()
    eval_before = orch._last_eval_outcome
    after = orch._measure_performance()
    eval_after = orch._last_eval_outcome

    e2e_gain = orch._pairedE2EGain(eval_before, eval_after)
    assert e2e_gain is not None and e2e_gain == pytest.approx(-0.3), (
        f"双读数差分没算出来：{e2e_gain}")

    metrics = {
        "convergence_status": "", "roi": 0.0,
        "gain": after - before,
        "gain_ci": orch._pairedGainCI(eval_before, eval_after),
        "e2e_gain": e2e_gain,
    }
    assert orch.rollback_manager.should_rollback(metrics) is True, (
        "行为分涨（0.5→0.7）而结局对齐崩（0.8→0.5）——综合判据没判否")
