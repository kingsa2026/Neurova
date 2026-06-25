"""
MemorySettingsConfig — 记忆系统统一配置中心

所有可调参数的单一事实源。模块通过 get_memory_settings().get("section.param") 读取。
配置持久化到 JSON 文件，API 通过 update/save/reset 操作。
"""

import json
from neurova.core.logger import get_logger
import os
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 参数 Schema：定义所有可调参数的元信息
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSchema:
    """单个参数的 schema"""
    key: str            # 如 "temperature.decay_rate"
    default: Any        # 默认值
    param_type: str     # "float" | "int" | "bool"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    description: str = ""


# 所有可调参数 schema — 单一事实源
PARAM_SCHEMAS: List[ParamSchema] = [
    # ---- temperature: 记忆温度衰减 ----
    ParamSchema("temperature.decay_rate", 0.1, "float", 0.0, 1.0,
                "记忆温度衰减速率（每小时）"),
    ParamSchema("temperature.access_boost", 0.3, "float", 0.0, 1.0,
                "每次检索提升的温度量"),
    ParamSchema("temperature.min", 0.01, "float", 0.0, 1.0,
                "记忆温度下限"),
    ParamSchema("temperature.max", 1.0, "float", 0.0, 1.0,
                "记忆温度上限"),

    # ---- auto_context: 自动上下文维护 ----
    ParamSchema("auto_context.update_interval", 3600, "int", 60, 86400,
                "自动更新循环间隔（秒）"),
    ParamSchema("auto_context.compression_threshold_days", 30, "int", 1, 365,
                "触发压缩的天数阈值"),
    ParamSchema("auto_context.temperature_decay_rate", 1.0, "float", 0.0, 10.0,
                "自动温度衰减率"),

    # ---- compression: 记忆压缩 ----
    ParamSchema("compression.similarity_threshold", 0.7, "float", 0.0, 1.0,
                "语义压缩相似度阈值"),
    ParamSchema("compression.max_memories_per_group", 10, "int", 1, 100,
                "每组最大记忆数"),
    ParamSchema("compression.time_window_hours", 24, "int", 1, 720,
                "聚合时间窗口（小时）"),
    ParamSchema("compression.importance_threshold", 0.3, "float", 0.0, 1.0,
                "低重要性记忆清理阈值"),
    ParamSchema("compression.enable_llm_compression", True, "bool",
                "是否启用 LLM 辅助压缩"),

    # ---- activation: 增强检索激活 ----
    ParamSchema("activation.decay_rate", 0.1, "float", 0.0, 1.0,
                "激活状态衰减速率（每小时）"),
    ParamSchema("activation.weight_context", 1.0, "float", 0.0, 5.0,
                "上下文激活类型权重"),
    ParamSchema("activation.weight_semantic", 0.9, "float", 0.0, 5.0,
                "语义激活类型权重"),
    ParamSchema("activation.weight_emotional", 0.8, "float", 0.0, 5.0,
                "情感激活类型权重"),
    ParamSchema("activation.weight_temporal", 0.7, "float", 0.0, 5.0,
                "时间激活类型权重"),
    ParamSchema("activation.weight_frequency", 0.6, "float", 0.0, 5.0,
                "频率激活类型权重"),
    ParamSchema("activation.weight_spread", 0.5, "float", 0.0, 5.0,
                "扩散激活类型权重"),

    # ---- threshold: 多通道激活阈值 ----
    ParamSchema("threshold.default", 0.3, "float", 0.0, 1.0,
                "通道激活默认阈值"),

    # ---- graph: 图遍历参数 ----
    ParamSchema("graph.min_strength", 0.15, "float", 0.0, 1.0,
                "图遍历最小强度"),
    ParamSchema("graph.beam_width", 3, "int", 1, 20,
                "beam search 宽度"),
    ParamSchema("graph.time_decay", 0.8, "float", 0.0, 1.0,
                "图遍历时间衰减因子"),

    # ---- vector_search: 向量搜索 ----
    ParamSchema("vector_search.cache_max_size", 1000, "int", 10, 100000,
                "查询缓存上限"),
    ParamSchema("vector_search.max_features", 10000, "int", 100, 1000000,
                "TF-IDF 最大特征数"),
    ParamSchema("vector_search.min_df", 2, "int", 1, 100,
                "最小文档频率"),
    ParamSchema("vector_search.max_df", 0.95, "float", 0.5, 1.0,
                "最大文档频率比例"),

    # ---- manager: 记忆管理器默认值 ----
    ParamSchema("manager.new_memory_temperature", 100.0, "float", 0.0, 1000.0,
                "新记忆初始温度"),
    ParamSchema("manager.new_memory_importance", 50.0, "float", 0.0, 1000.0,
                "新记忆初始重要性"),
    ParamSchema("manager.hot_memories_threshold", 80.0, "float", 0.0, 1000.0,
                "高温记忆过滤阈值"),
    ParamSchema("manager.decay_hours", 1.0, "float", 0.1, 24.0,
                "衰减周期（小时）"),
    ParamSchema("manager.decay_rate", 1.0, "float", 0.0, 10.0,
                "衰减速率"),
]


# ---------------------------------------------------------------------------
# MemorySettingsConfig — 单例配置中心
# ---------------------------------------------------------------------------

class MemorySettingsConfig:
    """
    记忆系统统一配置。

    使用方式:
        cfg = get_memory_settings()
        decay = cfg.get("temperature.decay_rate")  # → 0.1
        cfg.update({"temperature.decay_rate": 0.2})
        cfg.save()
    """

    _instance: Optional["MemorySettingsConfig"] = None
    _lock = threading.Lock()

    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)
        self._file_path = self._data_dir / "memory_settings.json"
        self._values: Dict[str, Any] = {}
        self._write_lock = threading.Lock()
        self._load()

    # -- 单例 --

    @classmethod
    def get_instance(cls, data_dir: str = "data") -> "MemorySettingsConfig":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(data_dir)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    # -- 公开 API --

    def get(self, key: str, default: Any = None) -> Any:
        """读取单个参数值"""
        if key in self._values:
            return self._values[key]
        # 回退到 schema 默认值
        for s in PARAM_SCHEMAS:
            if s.key == key:
                return s.default
        return default

    def get_all(self) -> Dict[str, Any]:
        """读取所有参数（合并 schema 默认 + 用户覆盖）"""
        result = {}
        for s in PARAM_SCHEMAS:
            result[s.key] = self._values.get(s.key, s.default)
        return result

    def get_section(self, section: str) -> Dict[str, Any]:
        """读取某个分组的所有参数，如 get_section("temperature")"""
        prefix = section + "."
        result = {}
        for s in PARAM_SCHEMAS:
            if s.key.startswith(prefix):
                result[s.key] = self._values.get(s.key, s.default)
        return result

    def get_schema(self) -> List[Dict[str, Any]]:
        """返回所有参数的 schema（供 API 返回）"""
        return [
            {
                "key": s.key,
                "default": s.default,
                "type": s.param_type,
                "min": s.min_val,
                "max": s.max_val,
                "description": s.description,
                "current": self._values.get(s.key, s.default),
            }
            for s in PARAM_SCHEMAS
        ]

    def update(self, updates: Dict[str, Any]) -> List[str]:
        """
        批量更新参数。返回成功更新的 key 列表。
        校验类型、范围；无效值跳过并记录 warning。
        """
        schema_map = {s.key: s for s in PARAM_SCHEMAS}
        updated = []
        for key, value in updates.items():
            if key not in schema_map:
                logger.warning("Unknown memory setting key: %s", key)
                continue
            s = schema_map[key]
            # 类型校验
            if s.param_type == "float" and not isinstance(value, (int, float)):
                logger.warning("Type mismatch for %s: expected float, got %s", key, type(value).__name__)
                continue
            if s.param_type == "int" and not isinstance(value, int):
                logger.warning("Type mismatch for %s: expected int, got %s", key, type(value).__name__)
                continue
            if s.param_type == "bool" and not isinstance(value, bool):
                logger.warning("Type mismatch for %s: expected bool, got %s", key, type(value).__name__)
                continue
            # 范围校验（跳过 bool，因为 bool 是 int 子类）
            if s.param_type != "bool" and s.min_val is not None and isinstance(value, (int, float)) and value < s.min_val:
                logger.warning("Value %s for %s below min %s", value, key, s.min_val)
                continue
            if s.param_type != "bool" and s.max_val is not None and isinstance(value, (int, float)) and value > s.max_val:
                logger.warning("Value %s for %s above max %s", value, key, s.max_val)
                continue
            self._values[key] = value
            updated.append(key)
        return updated

    def save(self) -> None:
        """持久化到 JSON 文件"""
        with self._write_lock:
            try:
                self._data_dir.mkdir(parents=True, exist_ok=True)
                with open(self._file_path, "w", encoding="utf-8") as f:
                    json.dump(self._values, f, indent=2, ensure_ascii=False)
                logger.info("Memory settings saved to %s", self._file_path)
            except Exception as e:
                logger.error("Failed to save memory settings: %s", e)

    def reset(self, keys: Optional[List[str]] = None) -> None:
        """
        重置参数。keys=None 重置全部，否则只重置指定 key。
        """
        if keys is None:
            self._values.clear()
        else:
            for k in keys:
                self._values.pop(k, None)

    def reset_and_save(self, keys: Optional[List[str]] = None) -> None:
        """重置并保存"""
        self.reset(keys)
        self.save()

    def update_and_save(self, updates: Dict[str, Any]) -> List[str]:
        """更新并保存"""
        updated = self.update(updates)
        if updated:
            self.save()
        return updated

    # -- 内部 --

    def _load(self) -> None:
        """从 JSON 文件加载"""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    self._values = json.load(f)
                logger.info("Memory settings loaded from %s (%d overrides)",
                            self._file_path, len(self._values))
            except Exception as e:
                logger.warning("Failed to load memory settings from %s: %s",
                               self._file_path, e)
                self._values = {}
        else:
            self._values = {}


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def get_memory_settings(data_dir: str = "data") -> MemorySettingsConfig:
    """获取记忆系统配置单例"""
    return MemorySettingsConfig.get_instance(data_dir)


def reset_memory_settings() -> None:
    """重置单例（测试用）"""
    MemorySettingsConfig.reset_instance()
