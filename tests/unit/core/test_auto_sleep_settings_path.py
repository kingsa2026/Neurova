"""自动睡眠设置通路测试

根因修复 (SleepSettingsPage 反馈):
1. auto_sleep_enabled 等设置键全库无消费方 —— idle_tracker 的自动触发
   链从不读取, 开关形同摆设。现在阶段迁移前必须检查开关。
2. start_sleep 的 sleep_duration_minutes 名义时长无消费方; 手动入睡
   (POST /sleep?duration_minutes=) 不回退设置默认值。
3. update_settings 必须拒绝未知键外的值(已有), 且 get/update round-trip
   保持类型。
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from neurova.core.idle_tracker import IdleTimeTracker
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation


@pytest.fixture
def consolidation():
    return SleepConsolidation(memory_manager=None, storage=None)


@pytest.fixture
def tracker():
    t = IdleTimeTracker()
    # 不真正起线程: 手动注入状态
    t._monitor_running = False
    return t


class TestAutoSleepGate:
    """auto_sleep_enabled=False 时, 空闲阶段迁移链不得触发巩固"""

    def test_auto_sleep_enabled_blocks_consolidation(self, tracker, consolidation):
        tracker.set_sleep_consolidation(consolidation)
        tracker.set_memory_manager(MagicMock())

        consolidation.update_settings({"auto_sleep_enabled": False})

        # 强制满足迁移条件: 模式 time + 空闲超阈值
        tracker._sleep_mode = "time"
        tracker._current_phase = "active"
        tracker._last_activity_time = time.time() - 10**6

        next_phase = tracker.get_next_phase(current_temperature=None)
        # get_next_phase 仍给出候选, 但迁移入口必须被 auto_sleep_enabled 拦截
        assert tracker.check_and_update_phase() is None
        assert tracker.get_current_phase() == "active"
        assert next_phase in ("light_sleep", "deep_sleep", "rem", "hibernate")

    def test_auto_sleep_on_allows_transition(self, tracker, consolidation):
        tracker.set_sleep_consolidation(consolidation)
        tracker.set_memory_manager(MagicMock())

        # 默认 auto_sleep_enabled=True
        tracker._sleep_mode = "time"
        tracker._current_phase = "active"
        tracker._last_activity_time = time.time() - 10**6

        assert tracker.check_and_update_phase() == "light_sleep"
        assert tracker.get_current_phase() == "light_sleep"


class TestStartSleepDuration:
    """手动入睡: duration 缺省时回退 sleep_duration_minutes 设置"""

    def test_start_sleep_uses_settings_duration(self, consolidation):
        consolidation.update_settings({"sleep_duration_minutes": 90})
        result = consolidation.start_sleep()  # 不传 duration_minutes
        assert result.get("duration_minutes") == 90

    def test_start_sleep_explicit_overrides_settings(self, consolidation):
        consolidation.update_settings({"sleep_duration_minutes": 90})
        result = consolidation.start_sleep(duration_minutes=15)
        assert result.get("duration_minutes") == 15


class TestSettingsRoundTrip:
    def test_update_rejects_unknown_keys(self, consolidation):
        consolidation.update_settings({"nonexistent_key": 1})
        assert "nonexistent_key" not in consolidation.get_settings()

    def test_defaults(self, consolidation):
        s = consolidation.get_settings()
        assert s["auto_sleep_enabled"] is True
        assert s["sleep_threshold_minutes"] == 30
        assert s["sleep_duration_minutes"] == 60
        assert s["dream_replay_enabled"] is True
        assert s["memory_consolidation_enabled"] is True
