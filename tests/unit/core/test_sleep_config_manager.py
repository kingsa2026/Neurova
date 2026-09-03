"""
测试睡眠配置管理器
"""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from neurova.core.sleep_config_manager import (
    IdleThresholds,
    PhaseDurations,
    WakeConditions,
    TemperatureThresholds,
    PhaseDaysConfig,
    SleepConfigData,
    SleepConfigManager,
)


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
        """测试创建唤醒条件配置"""
        conditions = WakeConditions()
        
        assert conditions.light_sleep == "either"
        assert conditions.deep_sleep == "temperature"
        assert conditions.rem == "temperature"
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
        """测试创建阶段天数配置"""
        config = PhaseDaysConfig()
        
        assert config.light_sleep_days_range == 3
        assert config.rem_days_range == 7
        assert config.deep_sleep_days_range == 30
        assert config.hibernate_days_range == 90


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
    
    def test_get_config_default(self):
        """测试获取默认配置"""
        manager = SleepConfigManager()
        
        config = manager.get_config()
        
        assert config is not None
        assert isinstance(config, SleepConfigData)
    
    def test_get_config_dict(self):
        """测试获取配置字典"""
        manager = SleepConfigManager()
        
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
        """测试验证无效模式"""
        manager = SleepConfigManager()
        
        valid, error = manager.validate_config({
            "sleep_mode": "invalid_mode",
        })
        
        assert valid is False
        assert "Invalid sleep mode" in error
    
    def test_validate_config_invalid_threshold(self):
        """测试验证无效阈值"""
        manager = SleepConfigManager()
        
        valid, error = manager.validate_config({
            "idle_thresholds": {"to_light_sleep": -100},
        })
        
        assert valid is False
        assert "Invalid idle threshold" in error
    
    def test_get_idle_thresholds_for_tracker(self):
        """测试获取适合Tracker的阈值"""
        manager = SleepConfigManager()
        
        thresholds = manager.get_idle_thresholds_for_tracker()
        
        assert "light_sleep" in thresholds
        assert "deep_sleep" in thresholds
        assert thresholds["light_sleep"] == 3600
    
    def test_get_phase_durations_for_tracker(self):
        """测试获取适合Tracker的阶段持续时间"""
        manager = SleepConfigManager()
        
        durations = manager.get_phase_durations_for_tracker()
        
        assert "light_sleep" in durations
        assert "deep_sleep" in durations
    
    def test_get_wake_conditions_for_tracker(self):
        """测试获取适合Tracker的唤醒条件"""
        manager = SleepConfigManager()
        
        conditions = manager.get_wake_conditions_for_tracker()
        
        assert "light_sleep" in conditions
        assert "deep_sleep" in conditions
    
    @pytest.mark.asyncio
    async def test_update_config_auto_sleep(self):
        """测试更新自动睡眠配置"""
        manager = SleepConfigManager()
        
        success = await manager.update_config({"auto_sleep": False})
        
        assert success is True
        assert manager.get_config().auto_sleep is False
    
    @pytest.mark.asyncio
    async def test_update_config_invalid_mode(self):
        """测试更新无效模式"""
        manager = SleepConfigManager()
        
        success = await manager.update_config({"sleep_mode": "invalid"})
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_update_config_idle_thresholds(self):
        """测试更新空闲阈值"""
        manager = SleepConfigManager()
        
        success = await manager.update_config({
            "idle_thresholds": {"to_light_sleep": 1800}
        })
        
        assert success is True
        assert manager.get_config().idle_thresholds.to_light_sleep == 1800
    
    @pytest.mark.asyncio
    async def test_reset_to_default(self):
        """测试重置为默认配置"""
        manager = SleepConfigManager()
        
        await manager.update_config({"auto_sleep": False})
        await manager.reset_to_default()
        
        assert manager.get_config().auto_sleep is True
