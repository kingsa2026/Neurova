"""
核心配置管理器 - 最小化实现

功能:
- 内存中存储配置键值对
- 支持 get/set 操作
- 兼容 knowledge/config.py 的 ConfigManager 接口
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """
    最小化配置管理器

    提供简单的键值对配置存储，支持从文件和环境变量加载。
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path
        self._data: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置配置值"""
        with self._lock:
            self._data[key] = value

    def has(self, key: str) -> bool:
        """检查配置是否存在"""
        return key in self._data

    def delete(self, key: str) -> bool:
        """删除配置"""
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        with self._lock:
            return dict(self._data)

    def load(self, path: Optional[str] = None) -> None:
        """从 JSON 文件加载配置"""
        load_path = path or self._config_path
        if not load_path or not Path(load_path).exists():
            return
        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._data.update(data)
        except Exception:
            pass

    def save(self, path: Optional[str] = None) -> None:
        """保存配置到 JSON 文件"""
        save_path = path or self._config_path
        if not save_path:
            return
        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_from_env(self, prefix: str = "NEUVA_") -> int:
        """从环境变量加载"""
        count = 0
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix) :].lower()
                self.set(config_key, value)
                count += 1
        return count

    def clear(self) -> None:
        """清空所有配置"""
        with self._lock:
            self._data.clear()
