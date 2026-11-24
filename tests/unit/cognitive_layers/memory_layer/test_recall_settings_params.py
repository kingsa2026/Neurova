# -*- coding: utf-8 -*-
"""D7/D8 调优参数登记进记忆设置中心 + 运行期读取判据。"""
from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.settings_config import (
    PARAM_SCHEMAS,
    get_memory_settings,
    MemorySettingsConfig,
)

NEW_KEYS = {
    "recall.temp_channel_relevance_floor": 0.6,
    "recall.hit_gain": 0.25,
    "recall.hot_limit": 500,
}


@pytest.fixture
def settings(tmp_path):
    MemorySettingsConfig.reset_instance()
    # 单例必须绑定到 tmp：运行期读取（apply_recall_gain 等）走同一个单例
    cfg = get_memory_settings(str(tmp_path))
    yield cfg
    MemorySettingsConfig.reset_instance()


def test_recall_params_registered(settings):
    keys = {s.key: s for s in PARAM_SCHEMAS}
    for key, default in NEW_KEYS.items():
        assert key in keys, f"缺少参数登记：{key}"
        assert keys[key].default == default


def test_runtime_reads_hit_gain_from_settings(settings, monkeypatch):
    from neurova.cognitive_layers.memory_layer.temperature import apply_recall_gain

    settings.update({"recall.hit_gain": 0.5})
    monkeypatch.delenv("NEUROVA_MEMORY_HIT_GAIN", raising=False)
    # 20 + (100-20)*0.5 = 60
    assert apply_recall_gain(20.0) == pytest.approx(60.0)
    # 显式实参优先于设置
    assert apply_recall_gain(20.0, 0.1) == pytest.approx(28.0)


def test_runtime_reads_floor_from_settings(settings):
    import neurova.cognitive_layers.memory_layer.neurova_recall as nr

    settings.update({"recall.temp_channel_relevance_floor": 0.7})
    assert nr._temp_channel_floor() == 0.7
    settings.update({"recall.temp_channel_relevance_floor": 0.4})
    assert nr._temp_channel_floor() == 0.4
    # 越界值（绕过设置层范围校验直写 _values）→ 运行期回退常量 0.6
    settings._values["recall.temp_channel_relevance_floor"] = 9.9
    assert nr._temp_channel_floor() == 0.6


def test_runtime_reads_hot_limit_from_settings(settings, monkeypatch):
    import neurova.cognitive_layers.memory_layer.manager as mgr_mod

    monkeypatch.delenv("NEUROVA_MEMORY_HOT_LIMIT", raising=False)
    settings.update({"recall.hot_limit": 123})
    assert mgr_mod._memory_hot_limit() == 123
    # env 优先于设置（部署级覆写）
    monkeypatch.setenv("NEUROVA_MEMORY_HOT_LIMIT", "7")
    assert mgr_mod._memory_hot_limit() == 7
