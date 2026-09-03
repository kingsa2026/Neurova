"""
空闲时间追踪器测试
测试 IdleTimeTracker 的各种功能，包括空闲时间追踪、睡眠阶段管理、回调等。
"""

import pytest
import sys
import os
import time
import asyncio
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.idle_tracker import (
    IdleTimeTracker,
    SleepPhaseThresholds,
    PhaseDuration,
    WakeCondition
)


class TestSleepPhaseThresholds:
    """测试睡眠阶段阈值配置"""

    def test_create_thresholds(self):
        """测试创建睡眠阶段阈值"""
        thresholds = SleepPhaseThresholds(
            idle_to_light_sleep=3600,
            idle_to_deep_sleep=7200,
            idle_to_rem=10800,
            idle_to_hibernate=43200
        )
        assert thresholds.idle_to_light_sleep == 3600
        assert thresholds.idle_to_deep_sleep == 7200
        assert thresholds.idle_to_rem == 10800
        assert thresholds.idle_to_hibernate == 43200

    def test_default_thresholds(self):
        """测试默认阈值"""
        thresholds = SleepPhaseThresholds()
        assert thresholds.idle_to_light_sleep == 3600
        assert thresholds.idle_to_deep_sleep == 7200


class TestPhaseDuration:
    """测试睡眠阶段持续时间配置"""

    def test_create_duration(self):
        """测试创建阶段持续时间"""
        duration = PhaseDuration(
            light_sleep=1800,
            deep_sleep=3600,
            rem=7200,
            hibernate=14400
        )
        assert duration.light_sleep == 1800
        assert duration.deep_sleep == 3600
        assert duration.rem == 7200
        assert duration.hibernate == 14400


class TestWakeCondition:
    """测试唤醒条件配置"""

    def test_create_wake_condition(self):
        """测试创建唤醒条件"""
        condition = WakeCondition(
            light_sleep="either",
            deep_sleep="temperature",
            rem="temperature",
            hibernate="time"
        )
        assert condition.light_sleep == "either"
        assert condition.deep_sleep == "temperature"
        assert condition.rem == "temperature"
        assert condition.hibernate == "time"


class TestIdleTimeTracker:
    """测试空闲时间追踪器"""

    @pytest.fixture
    def tracker(self, mock_event_bus, mock_logger):
        """创建追踪器实例"""
        return IdleTimeTracker(
            event_bus=mock_event_bus,
            state_manager=MagicMock(),
            log_manager=mock_logger,
            error_handler=MagicMock(),
            idle_thresholds={
                "light_sleep": 3600,
                "deep_sleep": 7200,
                "rem": 10800,
                "hibernate": 43200
            },
            sleep_mode="time"
        )

    def test_init(self, tracker):
        """测试初始化"""
        assert tracker is not None
        assert tracker._sleep_mode == "time"
        assert tracker._current_phase == "active"

    def test_record_activity(self, tracker):
        """测试记录活动"""
        tracker._last_activity_time = time.time() - 1000
        
        tracker.record_activity()
        
        idle_time = tracker.get_current_idle_time()
        assert idle_time == 0
        assert tracker._current_phase == "active"

    def test_get_current_idle_time(self, tracker):
        """测试获取当前空闲时间"""
        tracker._last_activity_time = time.time() - 100
        
        idle_time = tracker.get_current_idle_time()
        assert idle_time >= 100

    def test_get_current_phase(self, tracker):
        """测试获取当前阶段"""
        phase = tracker.get_current_phase()
        assert phase == "active"

    def test_get_phase_display_name(self, tracker):
        """测试获取阶段显示名称"""
        name = tracker.get_phase_display_name("active")
        assert name == "活跃中"
        
        name = tracker.get_phase_display_name("light_sleep")
        assert name == "浅睡期"

    def test_should_enter_phase_time_mode(self, tracker):
        """测试是否应进入阶段（时间模式）"""
        tracker._sleep_mode = "time"
        tracker._last_activity_time = time.time() - 4000
        
        should_enter = tracker.should_enter_phase("light_sleep")
        assert should_enter is True

    def test_should_enter_phase_temperature_mode(self, tracker):
        """测试是否应进入阶段（温度模式）"""
        tracker._sleep_mode = "temperature"
        
        should_enter = tracker.should_enter_phase("light_sleep", current_temperature=60.0)
        assert should_enter is True
        
        should_enter = tracker.should_enter_phase("light_sleep", current_temperature=80.0)
        assert should_enter is False

    def test_should_enter_phase_hybrid_mode(self, tracker):
        """测试是否应进入阶段（混合模式）"""
        tracker._sleep_mode = "hybrid"
        tracker._last_activity_time = time.time() - 4000
        
        should_enter = tracker.should_enter_phase("light_sleep", current_temperature=60.0)
        assert should_enter is True

    def test_get_next_phase(self, tracker):
        """测试获取下一阶段"""
        tracker._current_phase = "active"
        tracker._last_activity_time = time.time() - 4000
        
        next_phase = tracker.get_next_phase()
        assert next_phase == "light_sleep"

    def test_get_next_phase_no_transition(self, tracker):
        """测试获取下一阶段（无需转换）"""
        tracker._current_phase = "active"
        tracker._last_activity_time = time.time()
        
        next_phase = tracker.get_next_phase()
        assert next_phase is None

    def test_check_and_update_phase(self, tracker):
        """测试检查并更新阶段"""
        tracker._current_phase = "active"
        tracker._last_activity_time = time.time() - 4000
        
        next_phase = tracker.check_and_update_phase()
        assert next_phase == "light_sleep"
        assert tracker._current_phase == "light_sleep"

    def test_check_and_update_phase_no_change(self, tracker):
        """测试检查并更新阶段（无变化）"""
        tracker._current_phase = "active"
        tracker._last_activity_time = time.time()
        
        next_phase = tracker.check_and_update_phase()
        assert next_phase is None
        assert tracker._current_phase == "active"

    def test_transition_to_phase(self, tracker):
        """测试转换到阶段"""
        tracker._transition_to_phase("light_sleep")
        
        assert tracker._current_phase == "light_sleep"

    def test_enter_manual_phase(self, tracker):
        """测试手动进入阶段"""
        result = tracker.enter_manual_phase("light_sleep", duration=3600)
        assert result is True
        assert tracker._current_phase == "light_sleep"

    def test_enter_manual_phase_invalid(self, tracker):
        """测试手动进入无效阶段"""
        result = tracker.enter_manual_phase("invalid_phase")
        assert result is False

    def test_register_callback(self, tracker):
        """测试注册回调"""
        callback = MagicMock()
        tracker.register_callback("phase_changed", callback)
        
        assert callback in tracker._callbacks["phase_changed"]

    def test_get_status_info(self, tracker):
        """测试获取状态信息"""
        status = tracker.get_status_info()
        
        assert "current_phase" in status
        assert "phase_display_name" in status
        assert "current_idle_time" in status
        assert "sleep_mode" in status
        assert status["sleep_mode"] == "time"

    def test_update_config(self, tracker):
        """测试更新配置"""
        tracker.update_config(
            sleep_mode="hybrid",
            idle_thresholds={"light_sleep": 3000}
        )
        
        config = tracker.get_config()
        assert config["sleep_mode"] == "hybrid"
        assert config["idle_thresholds"]["light_sleep"] == 3000

    def test_get_config(self, tracker):
        """测试获取配置"""
        config = tracker.get_config()
        
        assert "sleep_mode" in config
        assert "idle_thresholds" in config
        assert "phase_durations" in config
        assert "wake_conditions" in config

    def test_reset(self, tracker):
        """测试重置"""
        tracker._current_phase = "deep_sleep"
        tracker._last_activity_time = time.time() - 10000
        
        tracker.reset()
        
        assert tracker._current_phase == "active"
        idle_time = tracker.get_current_idle_time()
        assert idle_time == 0

    def test_phase_order(self, tracker):
        """测试阶段顺序"""
        assert "active" in tracker.PHASE_ORDER
        assert "light_sleep" in tracker.PHASE_ORDER
        assert "deep_sleep" in tracker.PHASE_ORDER
        assert "rem" in tracker.PHASE_ORDER
        assert "hibernate" in tracker.PHASE_ORDER

    def test_temperature_thresholds(self, tracker):
        """测试温度阈值"""
        thresholds = tracker._idle_thresholds
        
        assert "light_sleep" in thresholds
        assert "deep_sleep" in thresholds
        assert "rem" in thresholds
        assert "hibernate" in thresholds


class TestMonitorOperations:
    """测试监控操作"""

    @pytest.fixture
    def tracker(self, mock_event_bus, mock_logger):
        """创建追踪器实例"""
        return IdleTimeTracker(
            event_bus=mock_event_bus,
            state_manager=MagicMock(),
            sleep_mode="time"
        )

    def test_start_monitoring(self, tracker):
        """测试启动监控"""
        tracker._start_monitoring()
        assert tracker._monitor_running is True
        assert tracker._monitor_thread is not None

    def test_stop_monitoring(self, tracker):
        """测试停止监控"""
        tracker._start_monitoring()
        tracker._stop_monitoring()
        assert tracker._monitor_running is False

    def test_set_monitor_interval(self, tracker):
        """测试设置监控间隔"""
        tracker.set_monitor_interval(120)
        assert tracker._monitor_interval == 120

    def test_set_monitor_interval_too_short(self, tracker):
        """测试设置过短的监控间隔"""
        tracker.set_monitor_interval(5)
        assert tracker._monitor_interval == 10


class TestConsolidationOperations:
    """测试整理操作"""

    @pytest.fixture
    def tracker(self, mock_event_bus, mock_logger):
        """创建追踪器实例"""
        return IdleTimeTracker(
            event_bus=mock_event_bus,
            state_manager=MagicMock(),
            sleep_mode="time"
        )

    def test_get_last_consolidation_result_none(self, tracker):
        """测试获取无整理结果"""
        result = tracker.get_last_consolidation_result()
        assert result is None

    def test_set_sleep_consolidation(self, tracker):
        """测试设置睡眠整理"""
        consolidation = MagicMock()
        tracker.set_sleep_consolidation(consolidation)
        assert tracker._sleep_consolidation == consolidation

    def test_set_memory_manager(self, tracker):
        """测试设置记忆管理器"""
        memory_manager = MagicMock()
        tracker.set_memory_manager(memory_manager)
        assert tracker._memory_manager == memory_manager

    def test_get_phase_config_manager(self, tracker):
        """测试获取阶段配置管理器"""
        manager = tracker.get_phase_config_manager()
        assert manager is not None


class TestAsyncOperations:
    """测试异步操作"""

    @pytest.fixture
    def tracker(self, mock_event_bus, mock_logger):
        """创建追踪器实例"""
        return IdleTimeTracker(
            event_bus=mock_event_bus,
            state_manager=MagicMock()
        )

    @pytest.mark.asyncio
    async def test_on_initialize(self, tracker):
        """测试初始化阶段"""
        await tracker.on_initialize()

    @pytest.mark.asyncio
    async def test_on_start(self, tracker):
        """测试启动阶段"""
        await tracker.on_start()
        assert tracker._monitor_running is True

    @pytest.mark.asyncio
    async def test_on_stop(self, tracker):
        """测试停止阶段"""
        await tracker.on_start()
        await tracker.on_stop()
        assert tracker._monitor_running is False


class TestEdgeCases:
    """测试边界情况"""

    def test_invalid_sleep_mode(self):
        """测试无效的睡眠模式"""
        tracker = IdleTimeTracker(sleep_mode="invalid")
        assert tracker._sleep_mode == "invalid"

    def test_empty_idle_thresholds(self):
        """测试空的空闲阈值"""
        tracker = IdleTimeTracker(idle_thresholds={})
        thresholds = tracker.get_config()["idle_thresholds"]
        assert len(thresholds) > 0

    def test_zero_idle_time(self):
        """测试零空闲时间"""
        tracker = IdleTimeTracker()
        tracker.record_activity()
        
        idle_time = tracker.get_current_idle_time()
        assert idle_time == 0

    def test_manual_phase_with_none_duration(self):
        """测试手动进入阶段（无持续时间）"""
        tracker = IdleTimeTracker()
        result = tracker.enter_manual_phase("deep_sleep", duration=None)
        assert result is True

    def test_phase_changed_callback(self):
        """测试阶段变更回调"""
        tracker = IdleTimeTracker()
        callback = MagicMock()
        tracker.register_callback("phase_changed", callback)
        
        tracker._transition_to_phase("light_sleep")
        
        assert callback.called

    def test_multiple_callbacks(self):
        """测试多个回调"""
        tracker = IdleTimeTracker()
        callback1 = MagicMock()
        callback2 = MagicMock()
        
        tracker.register_callback("phase_changed", callback1)
        tracker.register_callback("phase_changed", callback2)
        
        tracker._transition_to_phase("deep_sleep")
        
        assert callback1.called
        assert callback2.called

    def test_get_status_with_temperature(self):
        """测试获取状态（带温度）"""
        tracker = IdleTimeTracker()
        status = tracker.get_status_info(current_temperature=60.0)
        assert "next_phase" in status
