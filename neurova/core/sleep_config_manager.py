"""
睡眠配置管理器

负责加载、保存和管理睡眠模块的所有配置。
支持配置的持久化和验证。
"""

import json
import typing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.base_module import BaseModule


@dataclass
class IdleThresholds:
    """空闲时间阈值配置（秒）"""

    to_light_sleep: int = 3600
    to_deep_sleep: int = 7200
    to_rem: int = 10800
    to_hibernate: int = 43200


@dataclass
class PhaseDurations:
    """睡眠阶段持续时间配置（秒）"""

    light_sleep: int = 1800
    deep_sleep: int = 3600
    rem: int = 7200
    hibernate: int = 14400


@dataclass
class WakeConditions:
    """唤醒条件配置"""

    light_sleep: str = "either"
    deep_sleep: str = "temperature"
    rem: str = "time"
    hibernate: str = "time"


@dataclass
class TemperatureThresholds:
    """温度阈值配置"""

    sleep_threshold: float = 30.0
    wake_threshold: float = 70.0


@dataclass
class PhaseDaysConfig:
    """各睡眠阶段的天数配置（前端可配置）"""

    light_sleep_days_range: typing.List[int] = None
    rem_days_range: typing.List[int] = None
    deep_sleep_days_range: typing.List[int] = None
    hibernate_days_range: typing.List[int] = None

    def __post_init__(self):
        if self.light_sleep_days_range is None:
            self.light_sleep_days_range = [1, 3]
        if self.rem_days_range is None:
            self.rem_days_range = [3, 7]
        if self.deep_sleep_days_range is None:
            self.deep_sleep_days_range = [7, 14]
        if self.hibernate_days_range is None:
            self.hibernate_days_range = [14, 30]


@dataclass
class SleepConfigData:
    """睡眠配置数据类"""

    auto_sleep: bool = True
    sleep_mode: str = "temperature"
    idle_thresholds: IdleThresholds = None
    phase_durations: PhaseDurations = None
    wake_conditions: WakeConditions = None
    temperature_thresholds: TemperatureThresholds = None
    phase_days_config: PhaseDaysConfig = None
    memory_merge_threshold: float = 0.75
    conflict_resolution: str = "latest"
    auto_cleanup_enabled: bool = True
    max_dream_logs: int = 100
    dream_analysis_enabled: bool = True
    memory_consolidation_enabled: bool = True
    sleep_schedule: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.idle_thresholds is None:
            self.idle_thresholds = IdleThresholds()
        if self.phase_durations is None:
            self.phase_durations = PhaseDurations()
        if self.wake_conditions is None:
            self.wake_conditions = WakeConditions()
        if self.temperature_thresholds is None:
            self.temperature_thresholds = TemperatureThresholds()
        if self.phase_days_config is None:
            self.phase_days_config = PhaseDaysConfig()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_sleep": self.auto_sleep,
            "sleep_mode": self.sleep_mode,
            "idle_thresholds": asdict(self.idle_thresholds),
            "phase_durations": asdict(self.phase_durations),
            "wake_conditions": asdict(self.wake_conditions),
            "temperature_thresholds": asdict(self.temperature_thresholds),
            "phase_days_config": asdict(self.phase_days_config),
            "memory_merge_threshold": self.memory_merge_threshold,
            "conflict_resolution": self.conflict_resolution,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SleepConfigData":
        return cls(
            auto_sleep=data.get("auto_sleep", True),
            sleep_mode=data.get("sleep_mode", "temperature"),
            idle_thresholds=IdleThresholds(**data.get("idle_thresholds", {})),
            phase_durations=PhaseDurations(**data.get("phase_durations", {})),
            wake_conditions=WakeConditions(**data.get("wake_conditions", {})),
            temperature_thresholds=TemperatureThresholds(**data.get("temperature_thresholds", {})),
            phase_days_config=PhaseDaysConfig(**data.get("phase_days_config", {})),
            memory_merge_threshold=data.get("memory_merge_threshold", 0.75),
            conflict_resolution=data.get("conflict_resolution", "latest"),
        )


class SleepConfigManager(BaseModule):
    """睡眠配置管理器

    负责加载、保存和管理睡眠模块的所有配置。
    支持配置的持久化和验证。
    """

    MODULE_ID = "sleep_config_manager"
    MODULE_NAME = "Sleep Config Manager"
    MODULE_VERSION = "1.0.0"

    DEFAULT_CONFIG = {
        "auto_sleep": True,
        "sleep_mode": "temperature",
        "idle_thresholds": {
            "to_light_sleep": 3600,
            "to_deep_sleep": 7200,
            "to_rem": 10800,
            "to_hibernate": 43200,
        },
        "phase_durations": {
            "light_sleep": 1800,
            "deep_sleep": 3600,
            "rem": 7200,
            "hibernate": 14400,
        },
        "wake_conditions": {
            "light_sleep": "either",
            "deep_sleep": "temperature",
            "rem": "time",
            "hibernate": "time",
        },
        "temperature_thresholds": {
            "sleep_threshold": 30.0,
            "wake_threshold": 70.0,
        },
        "phase_days_config": {
            "light_sleep_days_range": [1, 3],
            "rem_days_range": [3, 7],
            "deep_sleep_days_range": [7, 14],
            "hibernate_days_range": [14, 30],
        },
        "memory_merge_threshold": 0.75,
        "conflict_resolution": "latest",
        "auto_cleanup_enabled": True,
        "max_dream_logs": 100,
        "dream_analysis_enabled": True,
        "memory_consolidation_enabled": True,
    }

    def __init__(self, config_path: Optional[str] = None, event_bus=None, state_manager=None, log_manager=None):
        super().__init__(config={"config_path": config_path}, event_bus=event_bus)
        self._config_path = Path(config_path) if config_path else Path(__file__).parent / "sleep_config.json"
        self._config: Optional[SleepConfigData] = None

    def on_initialize(self) -> None:
        self.log_info("Initializing Sleep Config Manager")
        self.load_config()

    def on_start(self) -> None:
        self.log_info("Sleep Config Manager started")

    def on_stop(self) -> None:
        self.log_info("Sleep Config Manager stopped")

    def load_config(self) -> SleepConfigData:
        """加载配置"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = SleepConfigData.from_dict(data)
                self.log_info(f"Loaded config from {self._config_path}")
            except Exception as e:
                self.log_warning(f"Failed to load config: {e}, using defaults")
                self._config = SleepConfigData.from_dict(self.DEFAULT_CONFIG)
        else:
            self._config = SleepConfigData.from_dict(self.DEFAULT_CONFIG)
            self.log_info("No config file found, using defaults")

        return self._config

    def save_config(self) -> bool:
        """保存配置"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)
            self.log_info(f"Saved config to {self._config_path}")
            self.emit_event("config.saved", {"config_path": str(self._config_path)})
            return True
        except Exception as e:
            self.log_error(f"Failed to save config: {e}")
            return False

    def get_config(self) -> SleepConfigData:
        """获取配置"""
        if self._config is None:
            return SleepConfigData.from_dict(self.DEFAULT_CONFIG)
        return self._config

    def get_config_dict(self) -> Dict[str, Any]:
        """获取配置字典"""
        return self.get_config().to_dict()

    def update_config(self, updates: Dict[str, Any]) -> bool:
        """更新配置"""
        config = self.get_config()

        # 更新简单字段
        if "auto_sleep" in updates:
            config.auto_sleep = updates["auto_sleep"]
        if "sleep_mode" in updates:
            if updates["sleep_mode"] not in ["temperature", "time", "either"]:
                raise ValueError(f"Invalid sleep mode: {updates['sleep_mode']}")
            config.sleep_mode = updates["sleep_mode"]

        # 更新嵌套字段
        for field_name in ["idle_thresholds", "phase_durations", "wake_conditions", "temperature_thresholds"]:
            if field_name in updates:
                field_obj = getattr(config, field_name)
                for key, value in updates[field_name].items():
                    if hasattr(field_obj, key):
                        setattr(field_obj, key, int(value) if isinstance(value, (int, float)) else value)

        self._update_state()
        return self.save_config()

    def _update_state(self) -> None:
        """更新状态值"""
        config = self.get_config()
        self.set_state_value("auto_sleep", config.auto_sleep)
        self.set_state_value("sleep_mode", config.sleep_mode)
        self.set_state_value("idle_thresholds", asdict(config.idle_thresholds))
        self.set_state_value("phase_durations", asdict(config.phase_durations))
        self.set_state_value("wake_conditions", asdict(config.wake_conditions))
        self.set_state_value("temperature_thresholds", asdict(config.temperature_thresholds))

    def validate_config(self, config_dict: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证配置"""
        errors = []

        for key, value in config_dict.items():
            if key == "auto_sleep" and not isinstance(value, bool):
                errors.append("auto_sleep must be boolean")
            elif key == "sleep_mode" and value not in ["temperature", "time", "either"]:
                errors.append("sleep_mode must be temperature, time, or either")
            elif key == "idle_thresholds":
                if not isinstance(value, dict):
                    errors.append("idle_thresholds must be dict")
                else:
                    for k, v in value.items():
                        if not isinstance(v, (int, float)):
                            errors.append(f"idle_thresholds.{k} must be number")
            elif key == "phase_durations":
                if not isinstance(value, dict):
                    errors.append("phase_durations must be dict")
                else:
                    for k, v in value.items():
                        if not isinstance(v, (int, float)):
                            errors.append(f"phase_durations.{k} must be number")

        if errors:
            return False, "; ".join(errors)
        return True, None

    def get_idle_thresholds_for_tracker(self) -> Dict[str, int]:
        """获取空闲阈值（供追踪器使用）"""
        config = self.get_config()
        return {
            "to_light_sleep": config.idle_thresholds.to_light_sleep,
            "to_deep_sleep": config.idle_thresholds.to_deep_sleep,
            "to_rem": config.idle_thresholds.to_rem,
            "to_hibernate": config.idle_thresholds.to_hibernate,
        }

    def get_phase_durations_for_tracker(self) -> Dict[str, int]:
        """获取阶段持续时间（供追踪器使用）"""
        config = self.get_config()
        return {
            "light_sleep": config.phase_durations.light_sleep,
            "deep_sleep": config.phase_durations.deep_sleep,
            "rem": config.phase_durations.rem,
            "hibernate": config.phase_durations.hibernate,
        }

    def get_wake_conditions_for_tracker(self) -> Dict[str, str]:
        """获取唤醒条件（供追踪器使用）"""
        config = self.get_config()
        return {
            "light_sleep": config.wake_conditions.light_sleep,
            "deep_sleep": config.wake_conditions.deep_sleep,
            "rem": config.wake_conditions.rem,
            "hibernate": config.wake_conditions.hibernate,
        }

    def reset_to_default(self) -> bool:
        """重置为默认配置"""
        try:
            self._config = SleepConfigData.from_dict(self.DEFAULT_CONFIG)
            if self.save_config():
                self._update_state()
                self.log_info("Reset config to defaults")
                return True
        except Exception as e:
            self.log_error(f"Failed to reset config: {e}")
        return False


__all__ = [
    "IdleThresholds",
    "PhaseDurations",
    "WakeConditions",
    "TemperatureThresholds",
    "PhaseDaysConfig",
    "SleepConfigData",
    "SleepConfigManager",
]
