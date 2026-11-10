# -*- coding: utf-8 -*-
"""H2 三策略离线对比（survey §10.2）——同题同机，对比器唯一。"""

import pytest

from neurova.evolution.rsi.eval_harness import RSIEvalHarness
from neurova.evolution.rsi.strategy_comparison import compareStrategies

#: setpoint 活参数态（与 eval_harness 真值契约同形）
def _params(**overrides):
    base = {
        "tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                        "decay_rate": 0.01, "muscle_memory_threshold": 0.8},
        "sleep": {"base_decay_rate": 0.1, "similarity_threshold": 0.7},
        "emotion": {"emotional_protection_threshold": 0.5,
                    "emotional_protection_factor": 0.3},
        "experience": {"crystallize_min_observations": 3,
                       "crystallize_min_success_rate": 0.6,
                       "pattern_min_support": 2},
    }
    for system, params in overrides.items():
        base[system].update(params)
    return base


def test_three_strategies_ranked():
    harness = RSIEvalHarness()
    readout = compareStrategies({
        "replay": _params(),
        "selective_retain": _params(tool_memory={"success_bonus": 0.15}),
        "refresh": _params(tool_memory={"decay_rate": 0.02}),
    }, harness=harness, baseline_params=_params())
    assert readout["state"] == "measured"
    assert set(readout["scores"].keys()) == {"replay", "selective_retain", "refresh"}
    assert readout["best"] in readout["scores"]
    assert "vs_baseline" in readout


def test_missing_strategy_reports_unevidenced():
    """红灯判据：策略缺档报 unevidenced（两策略不硬算三策略对比）。"""
    harness = RSIEvalHarness()
    readout = compareStrategies({
        "replay": _params(),
        "selective_retain": _params(),
    }, harness=harness)
    assert readout["state"] == "unevidenced"
    assert readout["missing"] == ["refresh"]


def test_comparator_uses_the_shared_harness():
    """结构格：对比器唯一——各策略分数与直接跑共享 harness 同读数。"""
    harness = RSIEvalHarness()
    params = _params()
    readout = compareStrategies({"replay": params, "selective_retain": params,
                                 "refresh": params}, harness=harness)
    direct = harness.run(params)["score"]
    assert readout["scores"]["replay"] == pytest.approx(direct), (
        "对比器没走共享 harness——第二套评分机器")
