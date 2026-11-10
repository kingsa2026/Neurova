# -*- coding: utf-8 -*-
"""F1 外部固定参考集并列（survey §10.2）——setpoint 贴近度代理第一次有外部对照。

代理分（0.7×setpoint 贴近度）与外部参考分（B1 的 e2e 真实结局对齐——重放
真实结局流，与 setpoint 代理不同测量族）逐轮成对采集，滚动相关性呈报：
"代理涨×参考平"序列的相关性读数必须如实下跌（代理不得独自粉饰）。
观测档形态：外部参考=e2e 对齐（确定性重放）；B2 任务流的 golden 臂评分
（真轨迹面）属升判据档，随 A1 真臂机器挂载——通道已由 B2 备好。
"""

import pytest

from neurova.evolution.rsi.proxy_reference import rollingCorrelation


class TestRollingCorrelation:
    def test_proxy_rising_reference_flat_reads_low(self):
        """红灯判据本体：代理涨×参考平 → 相关性≈0（代理不得独自粉饰）。"""
        proxy = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        reference = [0.5] * 8
        readout = rollingCorrelation(proxy, reference)
        assert readout["state"] == "measured"
        assert abs(readout["correlation"]) < 0.2, (
            f"代理独自上涨却被读成与外部参考相关：{readout}——相关性粉饰")

    def test_aligned_series_reads_high(self):
        """对照：代理与参考同向 → 相关性高（读数能区分两种形态）。"""
        proxy = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        reference = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55]
        readout = rollingCorrelation(proxy, reference)
        assert readout["correlation"] > 0.9

    def test_insufficient_pairs_report_insufficient_data(self):
        readout = rollingCorrelation([0.1], [0.5])
        assert readout["state"] == "insufficient_data"
        assert readout["score"] is None

    def test_degenerate_series_reads_zero_by_convention(self):
        """常数序列（方差 0）：按零相关约定呈报并点名 degenerate（皮尔逊无定义）。"""
        readout = rollingCorrelation([0.5] * 8, [0.5] * 8)
        assert readout["state"] == "measured"
        assert readout["correlation"] == 0.0
        assert readout["degenerate"] is True


def test_orchestrator_collects_pairs_and_surfaces_readout(tmp_path, monkeypatch):
    """编排器接线：逐轮成对采集（proxy, e2e 参考分），状态面挂相关性读数。"""
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    # 成对采集：合成序列喂入（proxy 涨、参考平）
    for proxy, reference in [(0.1 + i * 0.1, 0.5) for i in range(8)]:
        orch._recordProxyReferencePair(proxy, reference)
    readout = orch.get_status().get("proxy_reference_correlation")
    assert isinstance(readout, dict), "相关性读数未挂状态面"
    assert readout["state"] == "measured"
    assert abs(readout["correlation"]) < 0.2, (
        f"代理涨×参考平被读成高相关：{readout}")
    assert readout["pairs"] == 8
