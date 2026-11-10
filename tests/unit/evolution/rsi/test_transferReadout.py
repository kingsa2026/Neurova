# -*- coding: utf-8 -*-
"""C4 迁移读数两轴（survey §10.2）——两域重放差值＋同域恒等守卫。"""

import pytest

from neurova.evolution.rsi.task_yardstick import replay_alignment_score
from neurova.evolution.rsi.transfer_readout import (
    splitWindowDomains,
    transferReadout,
)


def _stream(rate, n=24):
    return {"t1": [(float(i), (i % 10) / 10 < rate) for i in range(n)]}


def test_same_domain_self_comparison_is_identity():
    """红灯判据本体：同域自比读数必须≈恒等（防"迁移"读数是噪声）。"""
    stream = _stream(0.5)
    readout = transferReadout(stream, stream, label_a="same", label_b="same")
    assert readout["state"] == "measured"
    assert readout["score"] == pytest.approx(0.0)


def test_same_reference_violation_raises():
    """重放机器失准（同引用差值≠0）当场炸——读数是噪声不是迁移。"""
    import neurova.evolution.rsi.transfer_readout as tr

    calls = {"n": 0}

    def _flaky(streams, **kw):
        calls["n"] += 1
        base = replay_alignment_score(streams, **kw)
        if calls["n"] == 2:
            base["score"] = base["score"] + 0.5  # 病态：同输入不同输出
        return base

    monkey = pytest.MonkeyPatch()
    monkey.setattr(tr, "replay_alignment_score", _flaky)
    try:
        stream = _stream(0.5)
        with pytest.raises(ValueError, match="重放机器失准"):
            tr.transferReadout(stream, stream)
    finally:
        monkey.undo()


def test_insufficient_domains_report_unevidenced():
    readout = transferReadout(_stream(0.5, n=4), _stream(0.8, n=4))
    assert readout["state"] == "insufficient_data"


def test_cross_domain_delta_is_signed():
    """旧域好（0.9）近域崩（0.1）→ 差值为负（分布漂移的可观测形态）。"""
    readout = transferReadout(_stream(0.9), _stream(0.1),
                              label_a="older", label_b="recent")
    assert readout["state"] == "measured"
    assert readout["score"] < 0


def test_window_split_yields_two_domains():
    split = splitWindowDomains(_stream(0.5))
    assert split is not None
    assert set(split.keys()) == {"a", "b"}
    readout = transferReadout(split["a"], split["b"], label_a="older", label_b="recent")
    assert readout["state"] in {"measured", "insufficient_data"}
