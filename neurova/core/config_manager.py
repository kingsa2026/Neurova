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

from neurova.core.logger import get_logger  # 修复 P0-10: 新增 logger

logger = get_logger(__name__)  # 修复 P0-10: 新增 logger 实例


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
        """从 JSON 文件加载配置

        修复 P0-10: 区分异常类型并记录日志（warning 级别，配置缺失可降级到默认值）
        """
        load_path = path or self._config_path
        if not load_path or not Path(load_path).exists():
            return
        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._data.update(data)
        except json.JSONDecodeError as e:
            # 修复 P0-10: JSON 损坏 — 记录 warning，保留旧配置
            logger.warning("配置文件 %s JSON 格式错误，已忽略: %s", load_path, e)
        except OSError as e:
            # 修复 P0-10: IO 错误（权限/磁盘） — 记录 warning
            logger.warning("配置文件 %s 读取失败: %s", load_path, e)
        except Exception as e:
            # 修复 P0-10: 其他未知异常 — 记录 warning
            logger.warning("配置文件 %s 加载异常: %s", load_path, e)

    def save(self, path: Optional[str] = None) -> None:
        """保存配置到 JSON 文件

        修复 P0-10: 区分异常类型并记录日志（error 级别，保存失败=用户数据丢失）
        """
        save_path = path or self._config_path
        if not save_path:
            return
        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            # 修复 P0-10: 磁盘满/权限拒绝 — 严重，用户数据丢失
            logger.error("配置文件 %s 保存失败（IO 错误），数据未写入: %s", save_path, e)
        except (TypeError, ValueError) as e:
            # 修复 P0-10: 数据本身不可序列化 — 严重
            logger.error("配置文件 %s 保存失败（数据不可序列化）: %s", save_path, e)
        except Exception as e:
            # 修复 P0-10: 其他未知异常 — 严重
            logger.error("配置文件 %s 保存异常: %s", save_path, e)

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
