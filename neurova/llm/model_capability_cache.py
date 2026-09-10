# -*- coding: utf-8 -*-
"""学习型模型能力缓存（对齐 QwenPaw providers/model_capability_cache.py）。

试错发现的模型能力（如：标记支持多模态却拒绝图片输入、thinking 模式
要求每条 assistant 消息带 reasoning_content）按 ``provider_id:model`` 键
缓存在此，避免切换模型后同样的首次调用失败反复发生。

进程级缓存（不持久化），刻意保守：只在确认的失败-恢复回路后写入。
条目按 TTL 过期，防止上游瞬态问题的过期发现长期压制某项输入。
TTL=0（env ``NEUROVA_CAPABILITY_CACHE_TTL_SECONDS``）关闭过期。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

CAPABILITY_CACHE_TTL_SECONDS = float(
    os.environ.get("NEUROVA_CAPABILITY_CACHE_TTL_SECONDS", "86400")
)

# 已知能力键（与 QwenPaw 语义对齐）
CAP_NEEDS_REASONING_CONTENT = "needs_reasoning_content"
CAP_REJECTS_MEDIA = "rejects_media"
CAP_REJECTS_AUDIO = "rejects_audio"
CAP_SUPPORTS_MULTIMODAL = "supports_multimodal"


class _CacheEntry:
    """学习值 + 写入时的单调时钟。"""

    __slots__ = ("value", "set_at")

    def __init__(self, value: Any, set_at: float) -> None:
        self.value = value
        self.set_at = set_at


class ModelCapabilityCache:
    """线程安全、进程级模型能力缓存：``{model_key: {capability: entry}}``。"""

    _instance: Optional["ModelCapabilityCache"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._learned: dict = {}
        self._data_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ModelCapabilityCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def learn(self, model_key: str, capability: str, value: Any) -> None:
        """记录 *model_key* 的一个学习值。"""
        now = time.monotonic()
        with self._data_lock:
            bucket = self._learned.setdefault(model_key, {})
            existing = bucket.get(capability)
            if existing is not None and existing.value == value:
                existing.set_at = now
                return
            bucket[capability] = _CacheEntry(value=value, set_at=now)
            logger.info("学习模型能力 %s: %s=%r", model_key, capability, value)

    def get(self, model_key: str, capability: str, default: Any = None) -> Any:
        """返回缓存值；未学习或已过期返回 *default*。"""
        with self._data_lock:
            bucket = self._learned.get(model_key)
            if bucket is None:
                return default
            entry = bucket.get(capability)
            if entry is None:
                return default
            if CAPABILITY_CACHE_TTL_SECONDS > 0:
                age = time.monotonic() - entry.set_at
                if age >= CAPABILITY_CACHE_TTL_SECONDS:
                    del bucket[capability]
                    if not bucket:
                        self._learned.pop(model_key, None)
                    return default
            return entry.value

    def clear(self, model_key: Optional[str] = None) -> None:
        """清空学习值；给 *model_key* 只清该模型，否则全清。"""
        with self._data_lock:
            if model_key is None:
                self._learned.clear()
            else:
                self._learned.pop(model_key, None)

    def forget(self, model_key: str, capability: str) -> None:
        """删除 *model_key* 的单个能力条目（保留其余能力与其他模型）。"""
        with self._data_lock:
            bucket = self._learned.get(model_key)
            if bucket is None:
                return
            bucket.pop(capability, None)
            if not bucket:
                self._learned.pop(model_key, None)


def get_capability_cache() -> ModelCapabilityCache:
    """全局单例。"""
    return ModelCapabilityCache.get_instance()


def reset_capability_cache() -> None:
    """重置单例（测试用）。"""
    with ModelCapabilityCache._lock:
        ModelCapabilityCache._instance = None
