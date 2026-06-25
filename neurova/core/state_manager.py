from __future__ import annotations

"""
统一状态管理模块 - 集中管理应用状态

功能:
- 状态树结构
- 状态变更追踪
- 状态持久化
- 状态快照/回滚
"""

import copy
import json
from neurova.core.logger import get_logger
import threading
import time
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = get_logger(__name__)


class StateStatus(Enum):
    """状态管理器状态"""

    IDLE = "idle"
    LOADING = "loading"
    SAVING = "saving"
    ERROR = "error"


@dataclass
class StateChange:
    """状态变更记录"""

    key: str
    old_value: typing.Any
    new_value: typing.Any
    timestamp: float = field(default_factory=time.time)


@dataclass
class StateSnapshot:
    """状态快照"""

    snapshot_id: str
    description: str
    state: dict
    timestamp: float = field(default_factory=time.time)


class StateManager:
    """
    统一状态管理器

    支持点号分隔的嵌套键访问（如 "user.profile.name"）
    """

    def __init__(self):
        self._state: dict = {}
        self._lock = threading.RLock()
        self._listeners: dict[str, list[typing.Callable]] = {}
        self._any_listeners: list[typing.Callable] = []
        self._snapshots: dict[str, StateSnapshot] = {}
        self._change_log: list[StateChange] = []
        self._persist_path: typing.Optional[Path] = None
        self._status = StateStatus.IDLE

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        """
        获取状态值

        Args:
            key: 点号分隔的键路径
            default: 默认值

        Returns:
            状态值
        """
        with self._lock:
            return self._get_nested(self._state, key, default)

    def set(self, key: str, value: typing.Any) -> None:
        """
        设置状态值

        Args:
            key: 点号分隔的键路径
            value: 要设置的值
        """
        with self._lock:
            old_value = self._get_nested(self._state, key)
            self._set_nested(self._state, key, value)

            change = StateChange(key=key, old_value=old_value, new_value=value)
            self._change_log.append(change)

            self._notify_listeners(key, old_value, value)
            self._emit_state_event(key, old_value, value)

    def delete(self, key: str) -> typing.Any:
        """
        删除状态值

        Args:
            key: 点号分隔的键路径

        Returns:
            被删除的值，不存在则返回 None
        """
        with self._lock:
            old_value = self._get_nested(self._state, key)
            if old_value is None and not self._key_exists(self._state, key):
                return None

            self._delete_nested(self._state, key)

            change = StateChange(key=key, old_value=old_value, new_value=None)
            self._change_log.append(change)

            self._notify_listeners(key, old_value, None)
            return old_value

    def has(self, key: str) -> bool:
        """
        检查键是否存在

        Args:
            key: 点号分隔的键路径

        Returns:
            是否存在
        """
        with self._lock:
            return self._key_exists(self._state, key)

    def keys(self) -> list[str]:
        """获取所有顶层键"""
        with self._lock:
            return list(self._state.keys())

    def get_all(self) -> dict:
        """获取完整状态（深拷贝）"""
        with self._lock:
            return copy.deepcopy(self._state)

    def update(self, updates: dict) -> list[StateChange]:
        """
        批量更新状态

        Args:
            updates: 键值对字典

        Returns:
            变更列表
        """
        with self._lock:
            changes = []
            for key, value in updates.items():
                old_value = self._get_nested(self._state, key)
                self._set_nested(self._state, key, value)
                change = StateChange(key=key, old_value=old_value, new_value=value)
                changes.append(change)
                self._change_log.append(change)
                self._notify_listeners(key, old_value, value)
            return changes

    def reset(self) -> None:
        """重置状态"""
        with self._lock:
            self._state.clear()
            self._change_log.clear()

    def on_change(self, key: str, listener: typing.Callable) -> None:
        """
        注册键变更监听器

        Args:
            key: 监听的键
            listener: 回调函数 (key, old_value, new_value)
        """
        with self._lock:
            if key not in self._listeners:
                self._listeners[key] = []
            self._listeners[key].append(listener)

    def on_any_change(self, listener: typing.Callable) -> None:
        """
        注册全局变更监听器

        Args:
            listener: 回调函数 (key, old_value, new_value)
        """
        with self._lock:
            self._any_listeners.append(listener)

    def remove_listener(self, listener: typing.Callable) -> None:
        """移除监听器"""
        with self._lock:
            for key in list(self._listeners.keys()):
                if listener in self._listeners[key]:
                    self._listeners[key].remove(listener)
            if listener in self._any_listeners:
                self._any_listeners.remove(listener)

    def _notify_listeners(self, key: str, old_value: typing.Any, new_value: typing.Any) -> None:
        """通知键监听器"""
        listeners = self._listeners.get(key, [])
        for listener in listeners:
            try:
                listener(key, old_value, new_value)
            except Exception as e:
                logger.error("监听器执行失败: %s", e)

    def _emit_state_event(self, key: str, old_value: typing.Any, new_value: typing.Any) -> None:
        """通知全局监听器"""
        for listener in self._any_listeners:
            try:
                listener(key, old_value, new_value)
            except Exception as e:
                logger.error("全局监听器执行失败: %s", e)

    def create_snapshot(self, description: str = "") -> str:
        """
        创建状态快照

        Args:
            description: 快照描述

        Returns:
            快照 ID
        """
        with self._lock:
            snapshot_id = str(uuid.uuid4())
            snapshot = StateSnapshot(snapshot_id=snapshot_id, description=description, state=copy.deepcopy(self._state))
            self._snapshots[snapshot_id] = snapshot
            return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """
        恢复状态快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            是否恢复成功
        """
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            if not snapshot:
                return False
            self._state = copy.deepcopy(snapshot.state)
            return True

    def list_snapshots(self) -> list[dict]:
        """列出所有快照"""
        with self._lock:
            return [
                {"id": s.snapshot_id, "description": s.description, "timestamp": s.timestamp}
                for s in self._snapshots.values()
            ]

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """删除快照"""
        with self._lock:
            if snapshot_id in self._snapshots:
                del self._snapshots[snapshot_id]
                return True
            return False

    def get_change_log(self) -> list[dict]:
        """获取变更日志"""
        with self._lock:
            return [
                {"key": c.key, "old_value": c.old_value, "new_value": c.new_value, "timestamp": c.timestamp}
                for c in self._change_log
            ]

    def clear_change_log(self) -> None:
        """清空变更日志"""
        with self._lock:
            self._change_log.clear()

    def set_persist_path(self, path: typing.Union[str, Path]) -> None:
        """设置持久化文件路径"""
        self._persist_path = Path(path)

    def save(self) -> bool:
        """保存状态到文件"""
        if not self._persist_path:
            logger.warning("未设置持久化路径")
            return False

        with self._lock:
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._persist_path, "w", encoding="utf-8") as f:
                    json.dump(self._state, f, ensure_ascii=False, indent=2, default=str)
                return True
            except Exception as e:
                logger.error("保存状态失败: %s", e)
                return False

    def load(self) -> bool:
        """从文件加载状态"""
        if not self._persist_path or not self._persist_path.exists():
            return False

        with self._lock:
            try:
                with open(self._persist_path, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                return True
            except Exception as e:
                logger.error("加载状态失败: %s", e)
                return False

    @property
    def change_count(self) -> int:
        """变更记录数"""
        return len(self._change_log)

    @property
    def snapshot_count(self) -> int:
        """快照数"""
        return len(self._snapshots)

    # ── 内部工具方法 ──

    def _get_nested(self, data: dict, key: str, default: typing.Any = None) -> typing.Any:
        """获取嵌套字典值"""
        keys = key.split(".")
        current = data
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current

    def _set_nested(self, data: dict, key: str, value: typing.Any) -> None:
        """设置嵌套字典值"""
        keys = key.split(".")
        current = data
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    def _delete_nested(self, data: dict, key: str) -> None:
        """删除嵌套字典值"""
        keys = key.split(".")
        current = data
        for k in keys[:-1]:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return
        if isinstance(current, dict) and keys[-1] in current:
            del current[keys[-1]]

    def _key_exists(self, data: dict, key: str) -> bool:
        """检查嵌套键是否存在"""
        keys = key.split(".")
        current = data
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return False
        return True


# ── 全局单例 ──

_global_state_manager: typing.Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """获取全局状态管理器"""
    global _global_state_manager
    if _global_state_manager is None:
        _global_state_manager = StateManager()
    return _global_state_manager


def reset_state_manager() -> None:
    """重置全局状态管理器 (主要用于测试)"""
    global _global_state_manager
    _global_state_manager = None
