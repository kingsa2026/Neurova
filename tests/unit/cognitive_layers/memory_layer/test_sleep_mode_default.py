# -*- coding: utf-8 -*-
"""D5 后续拍板（2026-11-24）：系统默认睡眠触发模式 temperature → either。

理由：temperature 模式下"从未使用的 agent 均温恒 60°，够不到 ≤30/25/20/15
的入睡线"——睡眠门从内侧锁死，休眠 agent 永不整理。either（温度或空闲
时长任一满足）让休眠 agent 也能按空闲时长走进睡眠整理，且对活跃 agent
行为不变（空闲 30 分钟门槛 + 温度门仍需同时满足才更早入睡）。
三处默认值必须同源：SleepConsolidation 设置字典 / IdleTimeTracker 预置
模式 / SleepSettings API 模型。
"""
from __future__ import annotations

from neurova.core.idle_tracker import IdleTimeTracker


def test_sleep_consolidation_default_mode_is_either():
    from neurova.cognitive_layers.memory_layer.sleep import (
        DEFAULT_SLEEP_MODE,
        SleepConsolidation,
    )

    assert DEFAULT_SLEEP_MODE == "either"
    assert SleepConsolidation().get_settings()["sleep_mode"] == "either"


def test_idle_tracker_preset_mode_is_either():
    tracker = IdleTimeTracker()
    assert tracker._sleep_mode == "either"


def test_sleep_settings_api_model_default_is_either():
    from neurova.api.endpoints.sleep import SleepSettings

    assert SleepSettings().sleep_mode == "either"
