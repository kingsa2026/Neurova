"""
测试睡眠阶段配置管理器
"""
import pytest
from neurova.core.sleep_phase_config_manager import SleepPhaseConfigManager


class TestSleepPhaseConfigManager:
    """测试SleepPhaseConfigManager类"""

    def test_init(self):
        """测试初始化"""
        manager = SleepPhaseConfigManager()
        assert manager is not None

    def test_get_sleep_mode(self):
        """测试获取睡眠模式"""
        manager = SleepPhaseConfigManager()
        mode = manager.get_sleep_mode()
        assert isinstance(mode, str)

    def test_get_idle_thresholds(self):
        """测试获取空闲阈值"""
        manager = SleepPhaseConfigManager()
        thresholds = manager.get_idle_thresholds()
        assert isinstance(thresholds, dict)

    def test_get_phase_durations(self):
        """测试获取阶段持续时间"""
        manager = SleepPhaseConfigManager()
        durations = manager.get_phase_durations()
        assert isinstance(durations, dict)

    def test_get_wake_conditions(self):
        """测试获取唤醒条件"""
        manager = SleepPhaseConfigManager()
        conditions = manager.get_wake_conditions()
        assert isinstance(conditions, dict)
