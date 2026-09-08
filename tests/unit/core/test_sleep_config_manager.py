"""
测试睡眠配置管理器（对齐 neurova/core/sleep_config_manager.py 真实契约）
"""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock

from neurova.core.sleep_config_manager import (
    IdleThresholds,
    PhaseDurations,
    WakeConditions,
    TemperatureThresholds,
    PhaseDaysConfig,
    SleepConfigData,
    SleepConfigManager,
)


def _make_manager(tmp_path):
    """创建隔离的配置管理器（config_path 指向 tmp，不污染真实配置）"""
    return SleepConfigManager(config_path=str(tmp_path / "sleep_config.json"))


class TestIdleThresholds:
    """测试IdleThresholds数据类"""

    def test_create_idle_thresholds(self):
        """测试创建空闲阈值配置"""
        thresholds = IdleThresholds()

        assert thresholds.to_light_sleep == 3600
        assert thresholds.to_deep_sleep == 7200
        assert thresholds.to_rem == 10800
        assert thresholds.to_hibernate == 43200


class TestPhaseDurations:
    """测试PhaseDurations数据类"""

    def test_create_phase_durations(self):
        """测试创建阶段持续时间配置"""
        durations = PhaseDurations()

        assert durations.light_sleep == 1800
        assert durations.deep_sleep == 3600
        assert durations.rem == 7200
        assert durations.hibernate == 14400


class TestWakeConditions:
    """测试WakeConditions数据类"""

    def test_create_wake_conditions(self):
        """测试创建唤醒条件配置（rem 默认 time）"""
        conditions = WakeConditions()

        assert conditions.light_sleep == "either"
        assert conditions.deep_sleep == "temperature"
        assert conditions.rem == "time"
        assert conditions.hibernate == "time"


class TestTemperatureThresholds:
    """测试TemperatureThresholds数据类"""

    def test_create_temperature_thresholds(self):
        """测试创建温度阈值配置"""
        thresholds = TemperatureThresholds()

        assert thresholds.sleep_threshold == 30.0
        assert thresholds.wake_threshold == 70.0


class TestPhaseDaysConfig:
    """测试PhaseDaysConfig数据类"""

    def test_create_phase_days_config(self):
        """测试创建阶段天数配置（区间列表）"""
        config = PhaseDaysConfig()

        assert config.light_sleep_days_range == [1, 3]
        assert config.rem_days_range == [3, 7]
        assert config.deep_sleep_days_range == [7, 14]
        assert config.hibernate_days_range == [14, 30]


class TestSleepConfigData:
    """测试SleepConfigData数据类"""

    def test_create_sleep_config_data(self):
        """测试创建睡眠配置数据"""
        config = SleepConfigData()

        assert config.auto_sleep is True
        assert config.sleep_mode == "temperature"
        assert isinstance(config.idle_thresholds, IdleThresholds)
        assert isinstance(config.phase_durations, PhaseDurations)

    def test_to_dict(self):
        """测试转换为字典"""
        config = SleepConfigData()

        data = config.to_dict()

        assert "auto_sleep" in data
        assert "sleep_mode" in data
        assert "idle_thresholds" in data
        assert "phase_durations" in data

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "auto_sleep": False,
            "sleep_mode": "time",
            "idle_thresholds": {"to_light_sleep": 1800},
        }

        config = SleepConfigData.from_dict(data)

        assert config.auto_sleep is False
        assert config.sleep_mode == "time"
        assert config.idle_thresholds.to_light_sleep == 1800

    def test_from_dict_empty(self):
        """测试从空字典创建"""
        config = SleepConfigData.from_dict({})

        assert config.auto_sleep is True
        assert config.sleep_mode == "temperature"


class TestSleepConfigManager:
    """测试SleepConfigManager类"""

    def test_init(self):
        """测试初始化"""
        manager = SleepConfigManager()

        assert manager.MODULE_ID == "sleep_config_manager"
        assert manager.MODULE_NAME == "Sleep Config Manager"

    def test_get_config_default(self, tmp_path):
        """测试获取默认配置"""
        manager = _make_manager(tmp_path)

        config = manager.get_config()

        assert config is not None
        assert isinstance(config, SleepConfigData)

    def test_get_config_dict(self, tmp_path):
        """测试获取配置字典"""
        manager = _make_manager(tmp_path)

        config_dict = manager.get_config_dict()

        assert isinstance(config_dict, dict)
        assert "auto_sleep" in config_dict

    def test_validate_config_valid(self):
        """测试验证有效配置"""
        manager = SleepConfigManager()

        valid, error = manager.validate_config({
            "sleep_mode": "temperature",
            "idle_thresholds": {"to_light_sleep": 3600},
        })

        assert valid is True
        assert error is None

    def test_validate_config_invalid_mode(self):
        """测试验证无效模式（错误消息：sleep_mode must be ...）"""
        manager = SleepConfigManager()

        valid, error = manager.validate_config({
            "sleep_mode": "invalid_mode",
        })

        assert valid is False
        assert "sleep_mode must be temperature, time, or either" in error

    def test_validate_config_invalid_threshold_type(self):
        """测试验证非数值阈值"""
        manager = SleepConfigManager()

        valid, error = manager.validate_config({
            "idle_thresholds": {"to_light_sleep": "not-a-number"},
        })

        assert valid is False
        assert "must be number" in error

    def test_get_idle_thresholds_for_tracker(self, tmp_path):
        """测试获取适合Tracker的阈值（键面 to_light_sleep 等）"""
        manager = _make_manager(tmp_path)

        thresholds = manager.get_idle_thresholds_for_tracker()

        assert "to_light_sleep" in thresholds
        assert "to_deep_sleep" in thresholds
        assert thresholds["to_light_sleep"] == 3600

    def test_get_phase_durations_for_tracker(self, tmp_path):
        """测试获取适合Tracker的阶段持续时间"""
        manager = _make_manager(tmp_path)

        durations = manager.get_phase_durations_for_tracker()

        assert "light_sleep" in durations
        assert "deep_sleep" in durations

    def test_get_wake_conditions_for_tracker(self, tmp_path):
        """测试获取适合Tracker的唤醒条件"""
        manager = _make_manager(tmp_path)

        conditions = manager.get_wake_conditions_for_tracker()

        assert "light_sleep" in conditions
        assert "deep_sleep" in conditions

    def test_update_config_auto_sleep(self, tmp_path):
        """测试更新自动睡眠配置（同步方法）"""
        manager = _make_manager(tmp_path)

        success = manager.update_config({"auto_sleep": False})

        assert success is True
        assert manager.get_config().auto_sleep is False

    def test_update_config_invalid_mode_raises(self, tmp_path):
        """测试更新无效模式抛 ValueError"""
        manager = _make_manager(tmp_path)

        with pytest.raises(ValueError):
            manager.update_config({"sleep_mode": "invalid"})

    def test_update_config_idle_thresholds(self, tmp_path):
        """测试更新空闲阈值"""
        manager = _make_manager(tmp_path)

        success = manager.update_config({
            "idle_thresholds": {"to_light_sleep": 1800}
        })

        assert success is True
        assert manager.get_config().idle_thresholds.to_light_sleep == 1800

    def test_update_config_unknown_nested_key_ignored(self, tmp_path):
        """更新嵌套配置的未知键被静默忽略"""
        manager = _make_manager(tmp_path)

        success = manager.update_config({
            "idle_thresholds": {"nonexistent": 999}
        })

        assert success is True

    def test_update_config_persists_to_file(self, tmp_path):
        """更新后配置落盘，新实例恢复"""
        manager = _make_manager(tmp_path)
        manager.update_config({"auto_sleep": False})

        manager2 = _make_manager(tmp_path)
        manager2.load_config()

        assert manager2.get_config().auto_sleep is False

    def test_reset_to_default(self, tmp_path):
        """测试重置为默认配置"""
        manager = _make_manager(tmp_path)

        manager.update_config({"auto_sleep": False})
        assert manager.reset_to_default() is True

        assert manager.get_config().auto_sleep is True
