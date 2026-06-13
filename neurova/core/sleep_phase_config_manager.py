"""
睡眠阶段配置管理器

为 IdleTimeTracker 提供睡眠阶段配置。
"""

from typing import Any, Dict, Optional

from neurova.core.sleep_config_manager import SleepConfigManager


class SleepPhaseConfigManager:
    """睡眠阶段配置管理器

    为 IdleTimeTracker 提供睡眠阶段配置。
    这是一个适配器类，将 SleepConfigManager 的接口适配为 IdleTimeTracker 所需的接口。
    """

    def __init__(self, config_manager: Optional[SleepConfigManager] = None):
        self._config_manager = config_manager or SleepConfigManager()

    def on_initialize(self) -> None:
        """初始化"""
        self._config_manager.initialize()

    def on_start(self) -> None:
        """启动"""
        self._config_manager.start()

    def on_stop(self) -> None:
        """停止"""
        self._config_manager.stop()

    def get_idle_thresholds(self) -> Dict[str, int]:
        """获取空闲阈值"""
        return self._config_manager.get_idle_thresholds_for_tracker()

    def get_phase_durations(self) -> Dict[str, int]:
        """获取阶段持续时间"""
        return self._config_manager.get_phase_durations_for_tracker()

    def get_wake_conditions(self) -> Dict[str, str]:
        """获取唤醒条件"""
        return self._config_manager.get_wake_conditions_for_tracker()

    def get_sleep_mode(self) -> str:
        """获取睡眠模式"""
        config = self._config_manager.get_config()
        return config.sleep_mode

    def update_config(self, updates: Dict[str, Any]) -> bool:
        """更新配置"""
        return self._config_manager.update_config(updates)


__all__ = ["SleepPhaseConfigManager"]
