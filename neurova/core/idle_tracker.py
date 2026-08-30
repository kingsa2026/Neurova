"""
空闲时间追踪器

负责追踪用户空闲时长，并根据配置的阈值判断应该进入的睡眠阶段。
支持三种睡眠触发模式：
- temperature: 仅基于温度判断（传统模式）
- time: 仅基于时间判断
- either: 温度或时间任一满足即可
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.core.base_module import BaseModule
from neurova.core.sleep_phase_config_manager import SleepPhaseConfigManager


@dataclass
class SleepPhaseThresholds:
    """睡眠阶段阈值配置"""

    idle_warning: float = 300.0  # 5分钟
    idle_drowsy: float = 600.0  # 10分钟
    idle_light_sleep: float = 1800.0  # 30分钟
    idle_deep_sleep: float = 3600.0  # 60分钟
    idle_rem: float = 5400.0  # 90分钟
    idle_hibernate: float = 7200.0  # 120分钟


@dataclass
class PhaseDuration:
    """阶段持续时间配置"""

    active: float = 0.0
    warning: float = 300.0
    drowsy: float = 600.0
    light_sleep: float = 1800.0
    deep_sleep: float = 3600.0


@dataclass
class WakeCondition:
    """唤醒条件配置"""

    min_temperature: float = 0.3
    min_activity_count: int = 3
    activity_window: float = 60.0


class IdleTimeTracker(BaseModule):
    """
    空闲时间追踪器

    负责追踪用户空闲时长，并根据配置的阈值判断应该进入的睡眠阶段。
    支持三种睡眠触发模式：
    - temperature: 仅基于温度判断（传统模式）
    - time: 仅基于时间判断
    - either: 温度或时间任一满足即可
    """

    MODULE_ID = "idle_tracker"
    MODULE_NAME = "Idle Time Tracker"
    MODULE_VERSION = "1.0.0"

    # 睡眠阶段顺序
    PHASE_ORDER = ["active", "light_sleep", "deep_sleep", "rem", "hibernate"]
    PHASE_DISPLAY_NAMES = {
        "active": "活跃",
        "light_sleep": "浅睡眠",
        "deep_sleep": "深睡眠",
        "rem": "REM睡眠",
        "hibernate": "休眠",
    }

    # 根因修复: 阶段 → SleepPhaseThresholds 字段映射。原实现用 f"to_{phase}"
    # 拼键（如 to_light_sleep），字段根本不存在 → getattr 默认 0 → 阶段迁移错乱。
    _PHASE_THRESHOLD_KEYS = {
        "light_sleep": "idle_light_sleep",
        "deep_sleep": "idle_deep_sleep",
        "rem": "idle_rem",
        "hibernate": "idle_hibernate",
    }

    def __init__(self, event_bus=None, state_manager=None, log_manager=None, error_handler=None):
        super().__init__(config={}, event_bus=event_bus)
        self._last_activity_time = time.time()
        self._current_idle_time = 0.0
        self._current_phase = "active"
        self._phase_start_time = time.time()
        self._phase_config_manager: Optional[SleepPhaseConfigManager] = None
        self._sleep_consolidation: Optional[SleepConsolidation] = None
        self._sleep_mode = "temperature"
        self._idle_thresholds = SleepPhaseThresholds()
        self._phase_durations = PhaseDuration()
        self._wake_conditions = WakeCondition()
        self._monitor_interval = 60  # 秒
        self._monitor_running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._last_consolidation_result: Optional[Dict[str, Any]] = None
        self._memory_manager = None
        # P2-6: 真实记忆温度来源（由 agent 注入 memory_manager.get_average_temperature）
        self._temperature_provider: Optional[Callable[[], float]] = None

    def set_temperature_provider(self, provider: Callable[[], float]) -> None:
        """设置真实记忆温度提供者（无注入时退回 25.0 中性默认值）"""
        self._temperature_provider = provider

    def _current_memory_temperature(self) -> float:
        """获取当前真实平均记忆温度"""
        if self._temperature_provider:
            try:
                return float(self._temperature_provider())
            except Exception as e:
                self.log_warning(f"获取记忆温度失败，回退默认值: {e}")
        return 25.0

    def on_initialize(self) -> None:
        self.log_info("Initializing Idle Time Tracker")
        if self._phase_config_manager:
            self._phase_config_manager.on_initialize()
        if self._sleep_consolidation:
            self._sleep_consolidation.set_state_value("initialized", True)
        self._current_phase = "active"

    def on_start(self) -> None:
        self.log_info("Starting Idle Time Tracker")
        if self._phase_config_manager:
            self._phase_config_manager.on_start()
        if self._sleep_consolidation:
            self._sleep_consolidation.set_state_value("started", True)
        # 根因修复: _on_phase_changed 此前从未注册，阶段迁移永远不触发记忆巩固
        self.register_callback("phase_changed", self._on_phase_changed)
        self._start_monitoring()
        self.set_state_value("running", True)

    def on_stop(self) -> None:
        self.log_info("Stopping Idle Time Tracker")
        self._stop_monitoring()
        if self._phase_config_manager:
            self._phase_config_manager.on_stop()
        if self._sleep_consolidation:
            self._sleep_consolidation.set_state_value("stopped", True)
        self.set_state_value("running", False)

    def _start_monitoring(self) -> None:
        """启动监控线程"""
        if self._monitor_running:
            return

        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_phase, daemon=True, name="idle-tracker-monitor")
        self._monitor_thread.start()
        self.log_info(f"Started monitoring with interval {self._monitor_interval}s")

    def _stop_monitoring(self) -> None:
        """停止监控线程"""
        if not self._monitor_running:
            return

        self._monitor_running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
            if self._monitor_thread.is_alive():
                self.log_warning("Monitor thread did not stop gracefully")

        self.log_info("Stopped monitoring")

    def _monitor_phase(self) -> None:
        """监控线程主循环"""
        self.log_info("Monitor thread started")
        while self._monitor_running:
            try:
                self.check_and_update_phase()
            except Exception as e:
                self.log_error(f"Error in monitor phase: {e}")

            # 等待下一次检查
            for _ in range(int(self._monitor_interval)):
                if not self._monitor_running:
                    break
                time.sleep(1)

    def set_monitor_interval(self, interval: int) -> None:
        """设置监控间隔"""
        if interval < 10:
            self.log_warning(f"Monitor interval {interval}s too small, setting to 10s")
            interval = 10
        self._monitor_interval = interval
        self.log_info(f"Monitor interval set to {interval}s")

    def adjust_parameters_based_on_sleep_quality(self) -> Dict[str, Any]:
        """根据睡眠质量调整参数"""
        # 简化实现：检查是否有存储的梦境报告统计
        try:
            from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

            if isinstance(self._storage, MemoryStorage):
                stats = self._storage.get_dream_report_stats()
                if stats:
                    avg_quality = stats.get("average_quality", 0)
                    self.log_info(f"Average dream quality: {avg_quality:.2f}")
                    # 根据质量调整监控间隔
                    if avg_quality > 0.7:
                        self._monitor_interval = max(30, self._monitor_interval - 10)
                    elif avg_quality < 0.3:
                        self._monitor_interval = min(120, self._monitor_interval + 10)
        except Exception as e:
            self.log_debug(f"Could not adjust parameters: {e}")

        return {
            "monitor_interval": self._monitor_interval,
            "current_phase": self._current_phase,
        }

    def _on_phase_changed(self, old_phase: str, new_phase: str, event_data: Optional[Dict] = None) -> None:
        """阶段变更回调"""
        if self._sleep_consolidation:
            self.log_info(f"Phase changed: {old_phase} -> {new_phase}")
            self._trigger_consolidation(new_phase)

    def _trigger_consolidation(self, phase: Optional[str] = None) -> None:
        """触发记忆巩固"""
        if not self._sleep_consolidation or not self._memory_manager:
            self.log_warning("Cannot trigger consolidation: missing consolidation or memory manager")
            return

        try:
            memories = self._memory_manager.get_all_memories()
            if memories:
                # 转换Dict为MemoryRecord
                from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

                memory_records = [MemoryRecord.from_dict(m) for m in memories]
                result = self._sleep_consolidation.run_sleep_cycle(memory_records)
                self._last_consolidation_result = result
                self.log_info(f"Consolidation completed: {len(memories)} memories processed")

                # 写回合并后的记忆
                self._write_back_consolidated_memories(result)

                # 通知回调
                for callback in self._callbacks.get("consolidation", []):
                    try:
                        callback(result)
                    except Exception as e:
                        self.log_error(f"Error in consolidation callback: {e}")
        except Exception as e:
            self.log_error(f"Error during consolidation: {e}")

    def _write_back_consolidated_memories(self, result: Dict) -> None:
        """将合并后的记忆写回MemoryManager

        根因修复: 此前这里维护着一份与 sleep_writeback.write_back_consolidation_result
        不一致的私有实现——收集了 source_ids 却从不删除 → 每次空闲整理记忆翻倍。
        现统一委托给共享写回实现（含"仅删除真实合并源记忆"的契约）。
        """
        if not self._memory_manager:
            return

        try:
            from neurova.cognitive_layers.memory_layer.sleep_writeback import (
                write_back_consolidation_result,
            )

            stats = write_back_consolidation_result(self._memory_manager, result)
            self.log_info(f"Write-back completed: {stats}")
        except Exception as e:
            self.log_error(f"Error during write-back: {e}")

    def trigger_consolidation(self) -> Optional[Dict[str, Any]]:
        """公开入口: 触发一次记忆巩固（供认知负荷过载后整合等场景调用）

        Returns:
            最近一次巩固结果；依赖缺失时返回 None
        """
        if not self._sleep_consolidation or not self._memory_manager:
            self.log_warning("Cannot trigger consolidation: missing consolidation or memory manager")
            return None
        self._trigger_consolidation()
        return self._last_consolidation_result

    def get_last_consolidation_result(self) -> Optional[Dict[str, Any]]:
        """获取最近一次巩固结果"""
        return self._last_consolidation_result

    def set_sleep_consolidation(self, consolidation: SleepConsolidation) -> None:
        """设置睡眠巩固器"""
        self._sleep_consolidation = consolidation

    def set_memory_manager(self, memory_manager) -> None:
        """设置记忆管理器"""
        self._memory_manager = memory_manager

    def get_phase_config_manager(self) -> Optional[SleepPhaseConfigManager]:
        """获取阶段配置管理器"""
        return self._phase_config_manager

    def record_activity(self) -> None:
        """记录用户活动（重置空闲时间）

        根因修复: 原实现只在非 active 阶段才重置时间戳，用户持续聊天时
        _last_activity_time 停留在初始化时刻，空闲时长被虚增。
        """
        old_phase = self._current_phase
        self._last_activity_time = time.time()
        self._current_idle_time = 0.0
        if old_phase != "active":
            self.log_info(f"Activity recorded, resetting from phase: {old_phase}")
            self._current_phase = "active"
            self._phase_start_time = time.time()
            self._emit_phase_changed(old_phase, "active")
            self.set_state_value("current_phase", "active")

    def get_current_idle_time(self) -> int:
        """获取当前空闲时间（秒）"""
        if self._current_phase == "active":
            return int(time.time() - self._last_activity_time)
        else:
            return int(time.time() - self._phase_start_time)

    def get_current_phase(self) -> str:
        """获取当前阶段"""
        return self._current_phase

    def get_phase_display_name(self, phase: str) -> str:
        """获取阶段显示名称"""
        return self.PHASE_DISPLAY_NAMES.get(phase, phase)

    def _idle_threshold_for(self, phase: str) -> float:
        """获取阶段的空闲秒数阈值（无映射的阶段返回 0）"""
        key = self._PHASE_THRESHOLD_KEYS.get(phase)
        if not key:
            return 0.0
        return getattr(self._idle_thresholds, key, 0.0)

    def should_enter_phase(self, target_phase: str, current_temperature: float) -> bool:
        """检查是否应该进入目标阶段"""
        current_idle = self.get_current_idle_time()

        # 根据睡眠模式判断
        if self._sleep_mode == "temperature":
            threshold = self._get_temperature_threshold(target_phase)
            return current_temperature <= threshold
        elif self._sleep_mode == "time":
            phase_index = self.PHASE_ORDER.index(target_phase) if target_phase in self.PHASE_ORDER else -1
            if phase_index > 0:
                return current_idle >= self._idle_threshold_for(target_phase)
            return False
        else:  # either
            # 检查温度条件
            threshold = self._get_temperature_threshold(target_phase)
            if current_temperature <= threshold:
                return True
            # 检查时间条件
            phase_index = self.PHASE_ORDER.index(target_phase) if target_phase in self.PHASE_ORDER else -1
            if phase_index > 0:
                return current_idle >= self._idle_threshold_for(target_phase)
            return False

    def _get_temperature_threshold(self, phase: str) -> float:
        """获取阶段的温度阈值"""
        # 简化实现：使用默认阈值
        thresholds = {
            "light_sleep": 30.0,
            "deep_sleep": 25.0,
            "rem": 20.0,
            "hibernate": 15.0,
        }
        return thresholds.get(phase, 30.0)

    def get_next_phase(self, current_temperature: Optional[float] = None) -> Optional[str]:
        """获取下一个应该进入的阶段"""
        if current_temperature is None:
            current_temperature = self._current_memory_temperature()

        current_index = self.PHASE_ORDER.index(self._current_phase) if self._current_phase in self.PHASE_ORDER else 0

        # 检查后续阶段
        for i in range(current_index + 1, len(self.PHASE_ORDER)):
            phase = self.PHASE_ORDER[i]
            if phase == "active":
                continue

            current_idle = self.get_current_idle_time()
            threshold = self._idle_threshold_for(phase)

            if self._sleep_mode == "temperature":
                temp_threshold = self._get_temperature_threshold(phase)
                if current_temperature <= temp_threshold:
                    return phase
            elif self._sleep_mode == "time":
                if current_idle >= threshold:
                    return phase
            else:  # either
                if current_idle >= threshold:
                    return phase

        return None

    def check_and_update_phase(self, current_temperature: Optional[float] = None) -> Optional[str]:
        """检查并更新阶段（不传温度时读取真实记忆平均温度）"""
        next_phase = self.get_next_phase(current_temperature)
        if next_phase and next_phase != self._current_phase:
            self._transition_to_phase(next_phase)
            return next_phase
        return None

    def _transition_to_phase(self, new_phase: str) -> None:
        """过渡到新阶段"""
        old_phase = self._current_phase
        self._current_phase = new_phase
        self._phase_start_time = time.time()
        self.set_state_value("current_phase", new_phase)
        self._emit_phase_changed(old_phase, new_phase)
        self.log_info(f"Transitioned to phase: {new_phase}")

    def _emit_phase_changed(self, old_phase: str, new_phase: str) -> None:
        """发送阶段变更事件"""
        event_data = {
            "old_phase": old_phase,
            "new_phase": new_phase,
            "timestamp": datetime.now().isoformat(),
        }

        # 调用回调
        for callback in self._callbacks.get("phase_changed", []):
            try:
                callback(old_phase, new_phase, event_data)
            except Exception as e:
                self.log_error(f"Error in phase change callback: {e}")

        # 发送事件
        self.emit_event("phase.changed", event_data)

    def enter_manual_phase(self, target_phase: str, duration: int = 0) -> bool:
        """手动进入指定阶段"""
        if target_phase not in self.PHASE_ORDER:
            self.log_error(f"Invalid phase: {target_phase}")
            return False

        # 如果是活跃阶段，重置活动
        if target_phase == "active":
            self.record_activity()
            return True

        # 进入目标阶段
        self._transition_to_phase(target_phase)

        # 如果设置了持续时间，设置定时器
        if duration > 0:
            phase_duration = self._phase_durations.__dict__.get(target_phase, 0)
            actual_duration = min(duration, phase_duration) if phase_duration > 0 else duration

            # 设置定时器
            def timer_callback():
                self.record_activity()

            timer = threading.Timer(actual_duration, timer_callback)
            timer.daemon = True
            timer.start()

            self.emit_event(
                "phase.manual_entered",
                {
                    "phase": target_phase,
                    "duration": actual_duration,
                    "end_time": datetime.now().isoformat(),
                },
            )

        return True

    def register_callback(self, event_type: str, callback: Callable) -> None:
        """注册回调"""
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(callback)

    def get_status_info(self, current_temperature: Optional[float] = None) -> Dict[str, Any]:
        """获取状态信息"""
        if current_temperature is None:
            current_temperature = self._current_memory_temperature()
        current_idle = self.get_current_idle_time()
        next_phase = self.get_next_phase(current_temperature)

        return {
            "current_idle_time": current_idle,
            "current_phase": self._current_phase,
            "current_phase_display": self.get_phase_display_name(self._current_phase),
            "next_phase": next_phase,
            "next_phase_display": self.get_phase_display_name(next_phase) if next_phase else None,
            "time_until_next": self._calculate_time_until_next(next_phase),
            "phase_start_time": self._phase_start_time,
            "last_activity_time": self._last_activity_time,
            "sleep_mode": self._sleep_mode,
            "thresholds": self._idle_thresholds.__dict__,
            "phase_durations": self._phase_durations.__dict__,
            "wake_conditions": self._wake_conditions.__dict__,
        }

    def _calculate_time_until_next(self, next_phase: Optional[str]) -> Optional[int]:
        """计算距离下一阶段的时间"""
        if not next_phase:
            return None

        current_idle = self.get_current_idle_time()
        remaining = self._idle_threshold_for(next_phase) - current_idle
        return max(0, int(remaining))

    def update_config(
        self,
        sleep_mode: Optional[str] = None,
        idle_thresholds: Optional[Dict[str, int]] = None,
        phase_durations: Optional[Dict[str, int]] = None,
        wake_conditions: Optional[Dict[str, str]] = None,
    ) -> None:
        """更新配置"""
        if sleep_mode:
            self._sleep_mode = sleep_mode
            self.set_state_value("sleep_mode", sleep_mode)

        if idle_thresholds:
            for key, value in idle_thresholds.items():
                if hasattr(self._idle_thresholds, key):
                    setattr(self._idle_thresholds, key, int(value))

        if phase_durations:
            for key, value in phase_durations.items():
                if hasattr(self._phase_durations, key):
                    setattr(self._phase_durations, key, int(value))

        if wake_conditions:
            for key, value in wake_conditions.items():
                if hasattr(self._wake_conditions, key):
                    setattr(self._wake_conditions, key, value)

        self.log_info(f"Updated config: sleep_mode={self._sleep_mode}")

    def get_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        return {
            "sleep_mode": self._sleep_mode,
            "idle_thresholds": self._idle_thresholds.__dict__,
            "phase_durations": self._phase_durations.__dict__,
            "wake_conditions": self._wake_conditions.__dict__,
        }

    def reset(self) -> None:
        """重置追踪器"""
        self.record_activity()
        self._current_phase = "active"
        self._phase_start_time = time.time()
        self.set_state_value("current_phase", "active")
        self.log_info("Tracker reset to active state")


__all__ = [
    "SleepPhaseThresholds",
    "PhaseDuration",
    "WakeCondition",
    "IdleTimeTracker",
]
