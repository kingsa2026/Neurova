from __future__ import annotations

"""
统一配置管理模块 - 集中管理应用配置

功能:
- 分层配置 (默认/应用/模块/环境)
- 配置验证
- 动态配置热更新
- 配置持久化
- 配置导入/导出
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ConfigLevel(Enum):
    """配置层级"""

    DEFAULT = 0  # 默认配置（最低优先级）
    APPLICATION = 10  # 应用级配置
    MODULE = 20  # 模块级配置
    ENVIRONMENT = 30  # 环境变量配置（最高优先级）


@dataclass
class ConfigEntry:
    """配置条目"""

    key: str
    value: Any
    level: ConfigLevel = ConfigLevel.APPLICATION
    description: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    read_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "level": self.level.value,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "read_only": self.read_only,
        }


class ConfigManager:
    """
    统一配置管理器

    支持分层配置、验证、热更新和持久化。
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径（可选）
        """
        self._config_path = config_path
        self._lock = threading.RLock()

        # 分层配置存储: key -> {level: ConfigEntry}
        self._configs: Dict[str, Dict[int, ConfigEntry]] = {}

        # 验证器: key -> validator_func
        self._validators: Dict[str, Callable[[Any], bool]] = {}

        # 变更回调列表
        self._change_callbacks: List[Callable[[str, Any, Any], None]] = []

        # 只读 key 集合
        self._read_only_keys: Set[str] = set()

        # 变更事件队列（用于批量通知）
        self._pending_changes: List[tuple] = []

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（返回最高优先级的值）

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        with self._lock:
            levels = self._configs.get(key)
            if not levels:
                return default

            # 返回最高优先级的值
            max_level = max(levels.keys())
            return levels[max_level].value

    def set(
        self,
        key: str,
        value: Any,
        level: ConfigLevel = ConfigLevel.APPLICATION,
        description: str = "",
    ) -> None:
        """
        设置配置值

        Args:
            key: 配置键
            value: 配置值
            level: 配置层级
            description: 配置描述
        """
        with self._lock:
            if key in self._read_only_keys:
                logger.warning("Attempted to set read-only config: %s", key)
                return

            # 验证
            if key in self._validators and not self._validators[key](value):
                raise ValueError(f"Config validation failed for key '{key}': {value}")

            old_value = self.get(key)

            if key not in self._configs:
                self._configs[key] = {}

            self._configs[key][level.value] = ConfigEntry(
                key=key,
                value=value,
                level=level,
                description=description,
                updated_at=time.time(),
            )

            # 通知变更
            if old_value != value:
                self._notify_change(key, old_value, value)

    def delete(self, key: str, level: Optional[ConfigLevel] = None) -> bool:
        """
        删除配置

        Args:
            key: 配置键
            level: 指定层级删除，为 None 时删除所有层级

        Returns:
            是否成功删除
        """
        with self._lock:
            if key in self._read_only_keys:
                return False

            if key not in self._configs:
                return False

            old_value = self.get(key)

            if level is None:
                del self._configs[key]
            else:
                self._configs[key].pop(level.value, None)
                if not self._configs[key]:
                    del self._configs[key]

            new_value = self.get(key)
            if old_value != new_value:
                self._notify_change(key, old_value, new_value)
            return True

    def has(self, key: str) -> bool:
        """检查配置是否存在"""
        return key in self._configs and len(self._configs[key]) > 0

    def get_all(self, flat: bool = True) -> Dict[str, Any]:
        """
        获取所有配置

        Args:
            flat: True 返回扁平字典，False 返回分层结构

        Returns:
            配置字典
        """
        with self._lock:
            if flat:
                return {key: self.get(key) for key in self._configs}
            else:
                result = {}
                for key, levels in self._configs.items():
                    result[key] = {level: entry.value for level, entry in levels.items()}
                return result

    def bulk_set(
        self,
        configs: Dict[str, Any],
        level: ConfigLevel = ConfigLevel.APPLICATION,
    ) -> None:
        """
        批量设置配置

        Args:
            configs: 配置字典
            level: 配置层级
        """
        for key, value in configs.items():
            self.set(key, value, level)

    def register_validator(self, key: str, validator: Callable[[Any], bool]) -> None:
        """
        注册配置验证器

        Args:
            key: 配置键
            validator: 验证函数，返回 True 表示有效
        """
        self._validators[key] = validator

    def validate_all(self) -> List[str]:
        """
        验证所有配置

        Returns:
            验证失败的键列表
        """
        failed = []
        with self._lock:
            for key, validator in self._validators.items():
                value = self.get(key)
                if value is not None and not validator(value):
                    failed.append(key)
        return failed

    def on_change(self, callback: Callable[[str, Any, Any], None]) -> None:
        """
        注册变更回调

        Args:
            callback: 回调函数 (key, old_value, new_value)
        """
        self._change_callbacks.append(callback)

    def remove_change_callback(self, callback: Callable) -> bool:
        """移除变更回调"""
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)
            return True
        return False

    def _notify_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """通知单个配置变更"""
        for cb in self._change_callbacks:
            try:
                cb(key, old_value, new_value)
            except Exception as e:
                logger.error("Config change callback error: %s", e)

    def _notify_bulk_change(self, changes: List[tuple]) -> None:
        """通知批量配置变更"""
        for key, old_value, new_value in changes:
            self._notify_change(key, old_value, new_value)

    def _emit_config_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """发出配置事件"""
        logger.debug("Config event: %s - %s", event_type, data)

    def save(self, path: Optional[str] = None) -> None:
        """
        保存配置到文件

        Args:
            path: 文件路径，为 None 时使用初始化路径
        """
        save_path = path or self._config_path
        if not save_path:
            logger.warning("No config path specified, skipping save")
            return

        with self._lock:
            data = {}
            for key, levels in self._configs.items():
                # 保存最高优先级
                max_level = max(levels.keys())
                data[key] = levels[max_level].value

        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Config saved to %s", save_path)
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    def load(self, path: Optional[str] = None) -> None:
        """
        从文件加载配置

        Args:
            path: 文件路径
        """
        load_path = path or self._config_path
        if not load_path or not Path(load_path).exists():
            return

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.load_from_dict(data, ConfigLevel.APPLICATION)
            logger.info("Config loaded from %s", load_path)
        except Exception as e:
            logger.error("Failed to load config: %s", e)

    def load_from_dict(self, data: Dict[str, Any], level: ConfigLevel = ConfigLevel.APPLICATION) -> None:
        """
        从字典加载配置

        Args:
            data: 配置字典
            level: 配置层级
        """
        changes = []
        with self._lock:
            for key, value in data.items():
                old_value = self.get(key)
                if key not in self._configs:
                    self._configs[key] = {}
                self._configs[key][level.value] = ConfigEntry(key=key, value=value, level=level)
                if old_value != value:
                    changes.append((key, old_value, value))

        self._notify_bulk_change(changes)

    def export(self, include_levels: bool = False) -> Dict[str, Any]:
        """
        导出配置

        Args:
            include_levels: 是否包含层级信息

        Returns:
            配置字典
        """
        return self.get_all(flat=not include_levels)

    def load_from_env(self, prefix: str = "NEUVA_") -> int:
        """
        从环境变量加载配置

        Args:
            prefix: 环境变量前缀

        Returns:
            加载的配置数量
        """
        count = 0
        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                config_key = env_key[len(prefix) :].lower()
                value = self._convert_env_value(env_value)
                self.set(config_key, value, ConfigLevel.ENVIRONMENT)
                count += 1
        return count

    @staticmethod
    def _convert_env_value(value: str) -> Any:
        """转换环境变量值为合适的 Python 类型"""
        # Boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False

        # Number
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass

        # JSON
        if value.startswith(("{", "[")):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass

        return value

    def config_count(self) -> int:
        """返回配置键总数"""
        return len(self._configs)

    def read_only_keys(self) -> Set[str]:
        """返回只读键集合"""
        return self._read_only_keys.copy()


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_config_manager: Optional[ConfigManager] = None
_manager_lock = threading.Lock()


def get_config_manager(config_path: Optional[str] = None) -> ConfigManager:
    """获取全局配置管理器"""
    global _config_manager
    if _config_manager is None:
        with _manager_lock:
            if _config_manager is None:
                _config_manager = ConfigManager(config_path=config_path)
                _config_manager.load()
    return _config_manager


def reset_config_manager() -> None:
    """重置全局配置管理器（主要用于测试）"""
    global _config_manager
    with _manager_lock:
        _config_manager = None
