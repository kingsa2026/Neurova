# -*- coding: utf-8 -*-
"""C2 质量三曲线（survey §10.2）——archive-best/deployed/final 逐 checkpoint 分列。

三条曲线回答不同问题（§7.5）：历史最好到过哪 / 现在线上是什么 / 本轮结束读数。
语义互斥守卫：archive_best < deployed 的构造态被拒（"历史最好冒充现值"）。
"""

import pytest

from neurova.evolution.rsi.result_summary import (
    readQualityCurves,
    record_quality_curves,
)


@pytest.fixture
def isolated_stream(tmp_path, monkeypatch):
    from neurova.evolution.rsi import result_summary as rs

    monkeypatch.setattr(rs, "_persist_path", None, raising=False)
    monkeypatch.setattr(rs, "_quality_curves_memory", [], raising=False)
    return rs


def test_three_curves_distinct_per_checkpoint(isolated_stream):
    record_quality_curves("agent-c2", 10, deployed=0.6, final=0.6)
    record_quality_curves("agent-c2", 20, deployed=0.7, final=0.7)
    readout = readQualityCurves("agent-c2")
    assert readout["state"] == "measured"
    assert [e["checkpoint"] for e in readout["curve"]] == [10, 20]
    assert [e["deployed"] for e in readout["curve"]] == [0.6, 0.7]
    assert readout["archive_best"] == pytest.approx(0.7)


def test_archive_best_impersonation_rejected(isolated_stream):
    """红灯判据本体：archive_best < deployed 的构造态被拒（互斥守卫）。"""
    record_quality_curves("agent-c2x", 10, deployed=0.6, final=0.6)
    with pytest.raises(ValueError, match="冒充"):
        record_quality_curves("agent-c2x", 20, deployed=0.8, final=0.8,
                              archive_best=0.5)


def test_agent_isolation(isolated_stream):
    record_quality_curves("a", 10, deployed=0.5, final=0.5)
    readout = readQualityCurves("b")
    assert readout["state"] == "insufficient_data"


def test_non_numeric_rejected(isolated_stream):
    with pytest.raises(ValueError, match="非数值"):
        record_quality_curves("a", 10, deployed="high", final=0.5)
