# -*- coding: utf-8 -*-
"""F4 setpoint 治理（survey §10.2，拍板未答→按判断走明示降权＋分解路线）。

路线登记：校准路线需 F1 外部参考的真实数据（观测档下无从校准），诚实走
「明示降权＋逐项分解呈报」半——分解面让代理分可审计；校准记录字段是
提案 gate 的登记位（无校准记录＝出厂默认档，如实标注）。
"""

import pytest

from neurova.evolution.rsi.system_performance import (
    estimate_system_performance,
    setpointDecomposition,
)


def _params(**overrides):
    params = {"success_bonus": 0.1, "failure_penalty": 0.05,
              "decay_rate": 0.01, "muscle_memory_threshold": 0.8}
    params.update(overrides)
    return params


def test_decomposition_matches_estimate():
    """分解面与代理标量同算式（单一算式两处共用，教义第 6 条）。"""
    feedback = {"performance_score": 0.6}
    params = _params(success_bonus=0.2)  # 离 setpoint 有距离
    score = estimate_system_performance("tool_memory", feedback, params)
    decomp = setpointDecomposition("tool_memory", feedback, params)
    assert decomp["score"] == pytest.approx(round(score, 6)), (
        f"分解面与标量分叉：{decomp['score']} vs {score}")


def test_weights_explicit_and_per_param_distances():
    feedback = {"performance_score": 0.6}
    decomp = setpointDecomposition("tool_memory", feedback,
                                   _params(success_bonus=0.2))
    assert decomp["weights"] == {"base": 0.3, "param_proximity": 0.7}
    assert decomp["per_param"]["success_bonus"]["distance"] > 0
    assert decomp["per_param"]["muscle_memory_threshold"]["distance"] == 0


def test_calibration_field_is_proposal_gate_slot():
    """校准记录登记位：出厂默认档如实标注（无校准记录不冒充已校准）。"""
    decomp = setpointDecomposition("tool_memory", {"performance_score": 0.5},
                                   _params())
    assert decomp["calibration"] is None, (
        "无校准记录却带 calibration 值——冒充已校准")
