"""P1-2 工具选择端到端标尺 — 红灯先行的契约测试(2026-10-06)。

背景:eval_harness 的 gain 来自 setpoint 梯度的"信号估算"(其模块文档
自认缺"整个 agent 是否变好"的端到端标尺)。本标尺补第一块行为读数:
把 AdaptiveToolWeights 滑动窗口里的真实结局流,在给定参数下经真实排名
代码路径重放,量"结局与权重排名的对齐度"(百分位对齐,成败对称)。

与 gain 的关系:**并列呈报、不参与 gain 判定与回滚** —— 它是观测面,
不是判据(判据仍归 eval_harness 与 rollback_manager)。

重放评估假设(诚实边界):历史成败可预测后续成败(平稳性);decay_rate
在快重放中不可观测(无闲置间隔),其遗忘带宽由 eval_harness 专用用例把守。
"""

import pytest


def _alpha_beta_streams(cycles: int):
    """alpha 成功 / beta 失败交替的结局流(ts 仅用于定序)。"""
    entries = []
    ts = 1000.0
    for _ in range(cycles):
        entries.append((ts, "tool_alpha", True))
        ts += 1
        entries.append((ts, "tool_beta", False))
        ts += 1
    return {
        "tool_alpha": [(ts, ok) for ts, tool, ok in entries if tool == "tool_alpha"],
        "tool_beta": [(ts, ok) for ts, tool, ok in entries if tool == "tool_beta"],
    }


class TestReplayAlignment:
    def test_flat_params_tie_score_exactly_half(self):
        """乘数与窗口成功率全并列时,对齐分必须恰为 0.5(中位秩契约)。"""
        from neurova.evolution.rsi.task_yardstick import replay_alignment_score

        streams = {
            "tool_alpha": [(1000.0 + 2 * i, True) for i in range(5)],
            "tool_beta": [(1001.0 + 2 * i, True) for i in range(5)],
        }
        outcome = replay_alignment_score(
            streams, success_bonus=0.0, failure_penalty=0.0, decay_rate=0.0)
        assert outcome["state"] == "measured"
        assert outcome["score"] == pytest.approx(0.5)

    def test_differentiating_params_align_better_than_flat(self):
        """参数敏感性:分化参数(default)的重放对齐分必须高于无分化(flat)。

        手算(12 条结局,前 6 条处于小样本免疫期):
        flat  = 免疫期 6×0.5 + 窗口期 6×1.0 → 0.75;
        default = 仅首条并列 0.5,其余乘数/成功率都把 alpha 排前 → ≈0.958。
        """
        from neurova.evolution.rsi.task_yardstick import replay_alignment_score

        streams = _alpha_beta_streams(cycles=6)
        default = replay_alignment_score(
            streams, success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01)
        flat = replay_alignment_score(
            streams, success_bonus=0.0, failure_penalty=0.0, decay_rate=0.0)
        assert default["state"] == flat["state"] == "measured"
        assert flat["score"] == pytest.approx(0.75)
        assert default["score"] > flat["score"]
        assert default["score"] == pytest.approx(11.5 / 12, abs=1e-3)

    def test_insufficient_data_is_honest(self):
        """结局流不足 → insufficient_data 且 score=None,不伪造读数。"""
        from neurova.evolution.rsi.task_yardstick import (
            MIN_ENTRIES,
            replay_alignment_score,
        )

        streams = {"tool_a": [(float(i), True) for i in range(MIN_ENTRIES - 1)]}
        outcome = replay_alignment_score(
            streams, success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01)
        assert outcome["state"] == "insufficient_data"
        assert outcome["score"] is None

    def test_empty_streams_insufficient(self):
        from neurova.evolution.rsi.task_yardstick import replay_alignment_score

        outcome = replay_alignment_score(
            {}, success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01)
        assert outcome["state"] == "insufficient_data" and outcome["score"] is None

    def test_deterministic(self):
        from neurova.evolution.rsi.task_yardstick import replay_alignment_score

        streams = _alpha_beta_streams(cycles=6)
        first = replay_alignment_score(
            streams, success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01)
        second = replay_alignment_score(
            streams, success_bonus=0.1, failure_penalty=0.05, decay_rate=0.01)
        assert first == second


class TestOutcomeStreams:
    def test_snapshot_excludes_none_votes(self):
        """三态语义:None(无回执)不投票 → 不进结局窗口。"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        weights = AdaptiveToolWeights()
        weights.update_weight("t1", True)
        weights.update_weight("t2", False)
        weights.update_weight("t1", None)
        streams = weights.outcome_streams()
        assert [ok for _, ok in streams["t1"]] == [True]
        assert [ok for _, ok in streams["t2"]] == [False]


class TestOrchestratorWiring:
    def test_measure_performance_reports_e2e_alongside(
            self, rsi_probe_factory, measured_eval_harness):
        """_measure_performance 的读数面必须并列携带 e2e 标尺(不参与 gain)。"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        probe = rsi_probe_factory(rsi_phase=2)
        weights = AdaptiveToolWeights()
        for _ in range(6):
            weights.update_weight("tool_alpha", True)
            weights.update_weight("tool_beta", False)
        probe.systems["tool_memory"].tool_weights = weights
        probe.orchestrator._eval_harness = measured_eval_harness([0.5])

        probe.orchestrator._measure_performance()

        e2e = probe.orchestrator._last_eval_outcome["e2e"]
        assert e2e["state"] == "measured"
        assert 0.0 <= e2e["score"] <= 1.0

    def test_apply_zero_keeps_iteration_alive(self, rsi_probe_factory, measured_eval_harness):
        """潜伏崩溃修复(随本标尺同批):候选过闸但全部应用失败 →
        run_iteration 不得 NameError,eval.after 诚实为 None。"""
        probe = rsi_probe_factory(rsi_phase=2)
        orch = probe.orchestrator
        orch._eval_harness = measured_eval_harness([0.5])
        orch.generate_optimizations = lambda signals: [
            {"system": "tool_memory", "param": "success_bonus", "value": 0.11}]
        orch.apply_optimizations = lambda optimizations: [
            {"applied": False, "reason": "stub"}]

        result = orch.run_iteration()

        assert result["applied_count"] == 0
        assert result["eval"]["before"] is not None
        assert result["eval"]["after"] is None

    def test_e2e_gain_helper(self):
        from neurova.evolution.rsi.orchestrator import _e2e_gain_from_evals

        before = {"e2e": {"state": "measured", "score": 0.5}}
        after = {"e2e": {"state": "measured", "score": 0.6}}
        assert _e2e_gain_from_evals(before, after) == pytest.approx(0.1)
        # 任一侧缺读数/未量出 → None(诚实三态,不得兜底 0.0)
        assert _e2e_gain_from_evals(None, after) is None
        blind = {"e2e": {"state": "insufficient_data", "score": None}}
        assert _e2e_gain_from_evals(blind, after) is None
