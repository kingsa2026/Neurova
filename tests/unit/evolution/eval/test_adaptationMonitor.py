# -*- coding: utf-8 -*-
"""D4 自适应污染监测曲线（survey §10.2）——"反复选择适应该验证集"的可观测形态。

选择轮次 ×（holdout 增益 − heldout 增益）逐轮差值：选择面独涨而密封面不涨
= 搜索在适应判据集（自适应污染），越界告警。数据面：evolve 结果已有
holdout/heldout 两侧读数，监测是纯读数（不改判定）。
"""

import pytest

from neurova.evolution.eval.adaptation_monitor import (
    adaptationSuspect,
    adaptationGap,
)


class TestAdaptationGap:
    def test_holdout_only_rise_flags_suspect(self):
        """红灯判据本体：holdout 独涨（+0.1）heldout 不涨（0.0）→ 告警。"""
        assert adaptationSuspect(selection_gain=0.1, sealed_gain=0.0) is True

    def test_both_rise_no_flag(self):
        """两侧同涨：搜索在真实改善，不是适应判据集。"""
        assert adaptationSuspect(selection_gain=0.1, sealed_gain=0.08) is False

    def test_both_flat_no_flag(self):
        assert adaptationSuspect(selection_gain=0.0, sealed_gain=0.0) is False

    def test_sealed_only_rise_no_flag(self):
        """密封面独涨（真实改善，选择面没跟上）：不是污染形态。"""
        assert adaptationSuspect(selection_gain=0.0, sealed_gain=0.1) is False

    def test_gap_computation_signed(self):
        assert adaptationGap(selection_gain=0.1, sealed_gain=0.0) == pytest.approx(0.1)
        assert adaptationGap(selection_gain=0.02, sealed_gain=0.05) == pytest.approx(-0.03)


def test_sequence_monitor_accumulates_and_alerts():
    """逐轮曲线：序列累计后污染轮被点名（monitor 保留逐轮差值）。"""
    from neurova.evolution.eval.adaptation_monitor import AdaptationMonitor

    monitor = AdaptationMonitor()
    monitor.record(selection_gain=0.01, sealed_gain=0.01)   # 正常轮
    monitor.record(selection_gain=0.10, sealed_gain=0.0)    # 污染轮
    monitor.record(selection_gain=0.01, sealed_gain=0.01)   # 正常轮
    readout = monitor.readout()
    assert readout["suspect_rounds"] == [1]  # 第 2 次 record（0 起）
    assert len(readout["curve"]) == 3
    assert readout["state"] == "measured"
