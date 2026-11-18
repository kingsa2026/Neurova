# -*- coding: utf-8 -*-
"""未知模型按 0 计费必须留痕（fullrepo 审计 2026-11-18 D 组）。

红灯依据：_calculate_cost_from_usage 查不到价目表时静默返回 0.0——
「未计价」被记成「免费」，成本面静默失真。修复：每 (provider, model)
只警告一次（不刷屏），口径是「未计价 ≠ 免费」。
"""
import logging

from neurova.models import cost_tracking as ct


def test_unknown_model_returns_zero_and_warns_once(caplog):
    with caplog.at_level(logging.WARNING, logger="neurova.models.cost_tracking"):
        first = ct._calculate_cost_from_usage(
            "no-such-provider", "ghost-model-x", {"prompt_tokens": 11, "completion_tokens": 3})
        second = ct._calculate_cost_from_usage(
            "no-such-provider", "ghost-model-x", {"prompt_tokens": 11, "completion_tokens": 3})
    assert first == 0.0 and second == 0.0, "缺价目表仍按 0 返回（行为不变）"
    warned = [r for r in caplog.records if "ghost-model-x" in r.getMessage()]
    assert warned, "未知模型按 0 计费必须留下警告信号"
    assert len(warned) == 1, f"同一 (provider, model) 只警告一次，实际 {len(warned)} 条"
