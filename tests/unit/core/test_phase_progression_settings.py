"""阶段推进参数设置通路测试

遗留问题: 各阶段温度阈值(30/25/20/15)、时间模式阈值(30/60/90/120 分钟)、
60s 监控间隔全部硬编码在 idle_tracker, 判定模式(temperature/time/either)
也无法切换 —— 设置页只能调"何时开始睡", 调不了"睡多深的节奏"。

修复: 这些参数并入 SleepConsolidation 设置管道(持久化/API/设置页),
IdleTimeTracker 每轮判定前读取设置快照并应用。默认值与原硬编码完全一致,
行为零漂移。

顺带修复: either 模式文档语义为"温度或时间任一满足", 原 get_next_phase
只查时间 —— 现与文档对齐。
"""

import time
from unittest.mock import MagicMock

import pytest

from neurova.core.idle_tracker import IdleTimeTracker
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation


@pytest.fixture
def consolidation():
    return SleepConsolidation(memory_manager=None, storage=None)


def _tracker(consolidation: SleepConsolidation, settings: dict) -> IdleTimeTracker:
    t = IdleTimeTracker()
    t._monitor_running = False
    t.set_sleep_consolidation(consolidation)
    t.set_memory_manager(MagicMock())
    t._current_phase = "active"
    t._last_activity_time = time.time() - 3600  # 默认空闲 60 分钟, 越过首迁空闲门
    base = {"sleep_threshold_minutes": 0}  # 隔离首迁空闲门, 聚焦阶段阈值
    base.update(settings)
    consolidation.update_settings(base)
    return t


class TestDefaults:
    def test_new_settings_keys_match_hardcoded_defaults(self, consolidation):
        s = consolidation.get_settings()
        assert s["sleep_mode"] == "temperature"
        assert s["temp_threshold_light_sleep"] == 30.0
        assert s["temp_threshold_deep_sleep"] == 25.0
        assert s["temp_threshold_rem"] == 20.0
        assert s["temp_threshold_hibernate"] == 15.0
        assert s["idle_threshold_light_sleep"] == 30
        assert s["idle_threshold_deep_sleep"] == 60
        assert s["idle_threshold_rem"] == 90
        assert s["idle_threshold_hibernate"] == 120
        assert s["monitor_interval_seconds"] == 60


class TestTemperatureThresholdFromSettings:
    def test_custom_threshold_allows_transition(self, consolidation):
        t = _tracker(consolidation, {"temp_threshold_light_sleep": 40.0})
        t._temperature_provider = lambda: 35.0  # 35 ≤ 40 → 迁移

        assert t.check_and_update_phase() == "light_sleep"

    def test_default_threshold_still_blocks(self, consolidation):
        t = _tracker(consolidation, {})
        t._temperature_provider = lambda: 35.0  # 35 > 30 → 不迁移

        assert t.check_and_update_phase() is None


class TestIdleThresholdFromSettings:
    def test_time_mode_custom_minutes(self, consolidation):
        t = _tracker(consolidation, {"sleep_mode": "time", "idle_threshold_light_sleep": 10})
        t._temperature_provider = lambda: 99.0  # 高温, time 模式不关心

        t._last_activity_time = time.time() - 11 * 60  # 空闲 11 分钟 ≥ 10
        assert t.check_and_update_phase() == "light_sleep"

        t._current_phase = "active"
        t._last_activity_time = time.time() - 5 * 60  # 空闲 5 分钟 < 10
        assert t.check_and_update_phase() is None


class TestSleepModeFromSettings:
    def test_mode_switched_via_settings(self, consolidation):
        """高温 + 空闲充足: temperature 模式不会迁移, time 模式会 —— 证明模式生效"""
        t = _tracker(consolidation, {"sleep_mode": "time"})
        t._temperature_provider = lambda: 99.0
        t._last_activity_time = time.time() - 31 * 60

        assert t.check_and_update_phase() == "light_sleep"

    def test_invalid_mode_ignored(self, consolidation):
        t = _tracker(consolidation, {"sleep_mode": "bogus"})
        t._temperature_provider = lambda: 10.0  # 温度模式下 10 ≤ 30 → 迁移

        assert t.check_and_update_phase() == "light_sleep"


class TestMonitorIntervalFromSettings:
    def test_interval_applied(self, consolidation):
        t = _tracker(consolidation, {"monitor_interval_seconds": 120})
        t.check_and_update_phase()
        assert t._monitor_interval == 120

    def test_invalid_interval_ignored(self, consolidation):
        t = _tracker(consolidation, {"monitor_interval_seconds": 5})
        t.check_and_update_phase()
        assert t._monitor_interval == 60


class TestEitherMode:
    def test_either_temperature_condition_alone(self, consolidation):
        """either 语义 = 温度或时间任一满足 (原实现只查时间, 与文档不符)"""
        t = _tracker(consolidation, {"sleep_mode": "either", "temp_threshold_light_sleep": 40.0})
        t._temperature_provider = lambda: 35.0  # 温度满足
        t._last_activity_time = time.time() - 60  # 空闲 1 分钟, 时间不满足

        assert t.check_and_update_phase() == "light_sleep"

    def test_either_time_condition_alone(self, consolidation):
        t = _tracker(consolidation, {"sleep_mode": "either"})
        t._temperature_provider = lambda: 99.0  # 温度不满足
        t._last_activity_time = time.time() - 31 * 60  # 时间满足

        assert t.check_and_update_phase() == "light_sleep"
