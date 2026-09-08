"""
空闲时间追踪器测试（对齐 neurova/core/idle_tracker.py 真实契约）
测试 IdleTimeTracker 的空闲追踪、睡眠阶段迁移、配置更新、回调。
"""

import time
from unittest.mock import MagicMock

import pytest

from neurova.core.idle_tracker import (
    IdleTimeTracker,
    SleepPhaseThresholds,
    PhaseDuration,
    WakeCondition,
)


def _make_tracker(**kwargs):
    """构造 tracker（构造器不收配置 kwargs，配置走 update_config）"""
    return IdleTimeTracker(event_bus=MagicMock(), **kwargs)


class TestSleepPhaseThresholds:
    """测试睡眠阶段阈值配置"""

    def test_create_thresholds(self):
        """测试创建睡眠阶段阈值（字段面 idle_*_sleep）"""
        thresholds = SleepPhaseThresholds(
            idle_light_sleep=3600,
            idle_deep_sleep=7200,
            idle_rem=10800,
            idle_hibernate=43200,
        )
        assert thresholds.idle_light_sleep == 3600
        assert thresholds.idle_deep_sleep == 7200
        assert thresholds.idle_rem == 10800
        assert thresholds.idle_hibernate == 43200

    def test_default_thresholds(self):
        """测试默认阈值"""
        thresholds = SleepPhaseThresholds()
        assert thresholds.idle_light_sleep == 1800
        assert thresholds.idle_deep_sleep == 3600
        assert thresholds.idle_rem == 5400
        assert thresholds.idle_hibernate == 7200


class TestPhaseDuration:
    """测试阶段持续时间配置"""

    def test_create_duration(self):
        """测试创建阶段持续时间（字段面 active/warning/drowsy/light_sleep/deep_sleep）"""
        duration = PhaseDuration(light_sleep=900, deep_sleep=2700)
        assert duration.light_sleep == 900
        assert duration.deep_sleep == 2700
        assert duration.active == 0.0

    def test_default_duration(self):
        """测试默认持续时间"""
        duration = PhaseDuration()
        assert duration.warning == 300.0
        assert duration.drowsy == 600.0
        assert duration.light_sleep == 1800.0


class TestWakeCondition:
    """测试唤醒条件配置"""

    def test_create_wake_condition(self):
        """测试创建唤醒条件（字段面 min_temperature/min_activity_count/activity_window）"""
        condition = WakeCondition(min_temperature=0.5, min_activity_count=5, activity_window=120.0)
        assert condition.min_temperature == 0.5
        assert condition.min_activity_count == 5
        assert condition.activity_window == 120.0

    def test_default_wake_condition(self):
        """测试默认唤醒条件"""
        condition = WakeCondition()
        assert condition.min_temperature == 0.3
        assert condition.min_activity_count == 3


class TestIdleTimeTracker:
    """测试空闲时间追踪器"""

    @pytest.fixture
    def tracker(self):
        """创建追踪器实例（time 模式），收尾停止监控线程"""
        t = _make_tracker()
        t.update_config(sleep_mode="time")
        yield t
        t._stop_monitoring()

    def test_init(self, tracker):
        """测试初始化"""
        assert tracker is not None
        assert tracker._sleep_mode == "time"
        assert tracker._current_phase == "active"

    def test_record_activity(self, tracker):
        """测试记录活动（重置空闲时间）"""
        tracker._last_activity_time = time.time() - 1000

        tracker.record_activity()

        assert tracker.get_current_idle_time() == 0
        assert tracker._current_phase == "active"

    def test_record_activity_from_sleep_phase_resets(self, tracker):
        """非 active 阶段记录活动 → 复位为 active 并发事件"""
        tracker._current_phase = "light_sleep"
        tracker.record_activity()

        assert tracker._current_phase == "active"

    def test_get_current_idle_time(self, tracker):
        """测试获取当前空闲时间"""
        tracker._last_activity_time = time.time() - 100

        assert tracker.get_current_idle_time() >= 100

    def test_get_current_phase(self, tracker):
        """测试获取当前阶段"""
        assert tracker.get_current_phase() == "active"

    def test_get_phase_display_name(self, tracker):
        """测试获取阶段显示名称"""
        assert tracker.get_phase_display_name("active") == "活跃"
        assert tracker.get_phase_display_name("light_sleep") == "浅睡眠"
        assert tracker.get_phase_display_name("unknown_phase") == "unknown_phase"

    def test_should_enter_phase_time_mode(self, tracker):
        """测试时间模式判定：空闲超阈值即入睡"""
        tracker._last_activity_time = time.time() - 4000  # > idle_light_sleep(1800)

        assert tracker.should_enter_phase("light_sleep", 100.0) is True

        tracker._last_activity_time = time.time()
        assert tracker.should_enter_phase("light_sleep", 100.0) is False

    def test_should_enter_phase_temperature_mode(self, tracker):
        """测试温度模式判定（温度 ≤ 阈值入睡）"""
        tracker._sleep_mode = "temperature"

        assert tracker.should_enter_phase("light_sleep", 20.0) is True
        assert tracker.should_enter_phase("light_sleep", 80.0) is False

    def test_should_enter_phase_either_mode(self, tracker):
        """测试 either 模式判定（温度或时间任一满足）"""
        tracker._sleep_mode = "either"

        # 温度满足
        assert tracker.should_enter_phase("light_sleep", 20.0) is True

        # 时间满足
        tracker._last_activity_time = time.time() - 4000
        assert tracker.should_enter_phase("light_sleep", 99.0) is True

        # 都不满足
        tracker._last_activity_time = time.time()
        assert tracker.should_enter_phase("light_sleep", 99.0) is False

    def test_get_next_phase(self, tracker):
        """测试获取下一阶段（time 模式，空闲超阈值）"""
        tracker._last_activity_time = time.time() - 4000

        assert tracker.get_next_phase() == "light_sleep"

    def test_get_next_phase_no_transition(self, tracker):
        """测试无需转换"""
        tracker._last_activity_time = time.time()

        assert tracker.get_next_phase() is None

    def test_check_and_update_phase(self, tracker):
        """测试检查并更新阶段（返回新阶段并完成迁移）"""
        tracker._last_activity_time = time.time() - 4000

        next_phase = tracker.check_and_update_phase()
        assert next_phase == "light_sleep"
        assert tracker._current_phase == "light_sleep"

    def test_check_and_update_phase_no_change(self, tracker):
        """测试检查无变化"""
        tracker._last_activity_time = time.time()

        assert tracker.check_and_update_phase() is None
        assert tracker._current_phase == "active"

    def test_check_and_update_phase_autosleep_disabled(self, tracker):
        """auto_sleep_enabled=False 时跳过自动迁移（开关真实生效）"""
        consolidation = MagicMock()
        consolidation.get_settings.return_value = {"auto_sleep_enabled": False}
        tracker.set_sleep_consolidation(consolidation)
        tracker._last_activity_time = time.time() - 4000

        assert tracker.check_and_update_phase() is None
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

    def test_enter_manual_phase_active_resets(self, tracker):
        """手动进入 active 即重置活动"""
        tracker._current_phase = "light_sleep"

        assert tracker.enter_manual_phase("active") is True
        assert tracker._current_phase == "active"

    def test_enter_manual_phase_invalid(self, tracker):
        """测试手动进入无效阶段"""
        assert tracker.enter_manual_phase("invalid_phase") is False

    def test_register_callback(self, tracker):
        """测试注册回调"""
        callback = MagicMock()
        tracker.register_callback("phase_changed", callback)

        assert callback in tracker._callbacks["phase_changed"]

    def test_get_status_info(self, tracker):
        """测试获取状态信息（键面 current_phase_display 等）"""
        status = tracker.get_status_info()

        assert "current_phase" in status
        assert "current_phase_display" in status
        assert "current_idle_time" in status
        assert "next_phase" in status
        assert "sleep_mode" in status
        assert status["sleep_mode"] == "time"

    def test_update_config(self, tracker):
        """测试更新配置（已存在的键才生效，未知键静默忽略）"""
        tracker.update_config(
            sleep_mode="either",
            idle_thresholds={"idle_light_sleep": 3000, "nonexistent_key": 1},
        )

        config = tracker.get_config()
        assert config["sleep_mode"] == "either"
        assert config["idle_thresholds"]["idle_light_sleep"] == 3000
        assert "nonexistent_key" not in config["idle_thresholds"]

    def test_get_config(self, tracker):
        """测试获取配置键面"""
        config = tracker.get_config()

        assert "sleep_mode" in config
        assert "idle_thresholds" in config
        assert "phase_durations" in config
        assert "wake_conditions" in config

    def test_reset(self, tracker):
        """测试重置"""
        tracker._current_phase = "deep_sleep"

        tracker.reset()

        assert tracker._current_phase == "active"
        assert tracker.get_current_idle_time() == 0

    def test_phase_order(self, tracker):
        """测试阶段顺序"""
        assert tracker.PHASE_ORDER == ["active", "light_sleep", "deep_sleep", "rem", "hibernate"]

    def test_temperature_thresholds(self, tracker):
        """测试温度阈值（内置默认，light_sleep=30）"""
        assert tracker._get_temperature_threshold("light_sleep") == 30.0
        assert tracker._get_temperature_threshold("hibernate") == 15.0
        assert tracker._get_temperature_threshold("nonexistent") == 30.0


class TestMonitorOperations:
    """测试监控操作"""

    @pytest.fixture
    def tracker(self):
        t = _make_tracker()
        yield t
        t._stop_monitoring()

    def test_start_monitoring(self, tracker):
        """测试启动监控"""
        tracker._start_monitoring()
        assert tracker._monitor_running is True
        assert tracker._monitor_thread is not None

    def test_start_monitoring_idempotent(self, tracker):
        """重复启动不重复建线程"""
        tracker._start_monitoring()
        thread = tracker._monitor_thread
        tracker._start_monitoring()
        assert tracker._monitor_thread is thread

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
        """测试设置过短的监控间隔（下限 10s）"""
        tracker.set_monitor_interval(5)
        assert tracker._monitor_interval == 10


class TestConsolidationOperations:
    """测试整理操作"""

    @pytest.fixture
    def tracker(self):
        t = _make_tracker()
        yield t
        t._stop_monitoring()

    def test_get_last_consolidation_result_none(self, tracker):
        """测试获取无整理结果"""
        assert tracker.get_last_consolidation_result() is None

    def test_set_sleep_consolidation(self, tracker):
        """测试设置睡眠整理器"""
        consolidation = MagicMock()
        tracker.set_sleep_consolidation(consolidation)
        assert tracker._sleep_consolidation is consolidation

    def test_set_memory_manager(self, tracker):
        """测试设置记忆管理器"""
        memory_manager = MagicMock()
        tracker.set_memory_manager(memory_manager)
        assert tracker._memory_manager is memory_manager

    def test_get_phase_config_manager_default_none(self, tracker):
        """未挂接阶段配置管理器时返回 None"""
        assert tracker.get_phase_config_manager() is None

    def test_trigger_consolidation_missing_deps(self, tracker):
        """依赖缺失时触发巩固返回 None 不崩"""
        assert tracker.trigger_consolidation() is None

    def test_set_temperature_provider(self, tracker):
        """温度提供者注入生效，异常时回退 25.0"""
        tracker.set_temperature_provider(lambda: 18.5)
        assert tracker._current_memory_temperature() == 18.5

        tracker.set_temperature_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert tracker._current_memory_temperature() == 25.0


class TestLifecycleOperations:
    """测试生命周期（同步方法）"""

    def test_on_initialize_start_stop(self):
        """on_initialize/on_start/on_stop 同步执行，start 拉起监控"""
        tracker = _make_tracker()

        tracker.on_initialize()
        assert tracker._current_phase == "active"

        tracker.on_start()
        assert tracker._monitor_running is True

        tracker.on_stop()
        assert tracker._monitor_running is False


class TestEdgeCases:
    """测试边界情况"""

    def test_invalid_sleep_mode_stored_as_is(self):
        """无效睡眠模式原样存储（判定走 else=either 分支）"""
        tracker = _make_tracker()
        tracker.update_config(sleep_mode="invalid")
        assert tracker.get_config()["sleep_mode"] == "invalid"
        tracker._stop_monitoring()

    def test_empty_idle_thresholds_keeps_defaults(self):
        """空阈值更新保留内置默认"""
        tracker = _make_tracker()
        tracker.update_config(idle_thresholds={})
        thresholds = tracker.get_config()["idle_thresholds"]
        assert len(thresholds) > 0
        tracker._stop_monitoring()

    def test_zero_idle_time(self):
        """测试零空闲时间"""
        tracker = _make_tracker()
        tracker.record_activity()

        assert tracker.get_current_idle_time() == 0
        tracker._stop_monitoring()

    def test_manual_phase_zero_duration(self):
        """手动进入阶段（duration=0 不设定时器）"""
        tracker = _make_tracker()
        result = tracker.enter_manual_phase("deep_sleep", duration=0)
        assert result is True
        tracker._stop_monitoring()

    def test_phase_changed_callback(self):
        """测试阶段变更回调触发"""
        tracker = _make_tracker()
        callback = MagicMock()
        tracker.register_callback("phase_changed", callback)

        tracker._transition_to_phase("light_sleep")

        callback.assert_called_once()
        tracker._stop_monitoring()

    def test_multiple_callbacks(self):
        """测试多个回调全部触发"""
        tracker = _make_tracker()
        callback1 = MagicMock()
        callback2 = MagicMock()

        tracker.register_callback("phase_changed", callback1)
        tracker.register_callback("phase_changed", callback2)

        tracker._transition_to_phase("deep_sleep")

        callback1.assert_called_once()
        callback2.assert_called_once()
        tracker._stop_monitoring()

    def test_get_status_with_temperature(self):
        """测试获取状态（显式温度不读提供者）"""
        tracker = _make_tracker()
        status = tracker.get_status_info(current_temperature=60.0)
        assert "next_phase" in status
        tracker._stop_monitoring()
