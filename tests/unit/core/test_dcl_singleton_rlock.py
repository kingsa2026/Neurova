# -*- coding: utf-8 -*-
"""懒建单例锁规格守卫（审计 3.2-2，2026-11-17）：AGENTS.md §3 明文要求
懒创建型单例必须走 DCL + threading.RLock——构造过程可能回调到同一入口，
threading.Lock 在重入路径上自死锁。本档把文件域内全部单例守卫锁钉成
RLock 实例断言，防止未来新增单例又退回 Lock。
"""

from __future__ import annotations

import threading

import pytest

_RLOCK_TYPE = type(threading.RLock())


def _assertRLock(lock: object, where: str) -> None:
    assert type(lock) is _RLOCK_TYPE, (
        f"{where} 的单例守卫锁是 {type(lock).__name__} 而非 RLock——"
        "AGENTS.md §3 要求懒创建型单例走 DCL + RLock（构造可重入）"
    )


@pytest.mark.parametrize(
    "module_path,attr",
    [
        ("neurova.llm.provider_manager", "_provider_manager_lock"),
        ("neurova.llm.providers.capability_detector", "_detector_lock"),
        ("neurova.llm.providers.capability_detector", "_cache_lock"),
        ("neurova.llm.providers.multimodal_prober", "_singleton_lock"),
        ("neurova.core.aigc_usage", "_instance_lock"),
        ("neurova.core.usage_history", "_usage_lock"),
        ("neurova.core.annotation_store", "_annotation_store_lock"),
        ("neurova.knowledge.storage", "_singleton_lock"),
        ("neurova.cognitive_layers.memory_layer.security", "_instance_lock"),
        ("neurova.cognitive_layers.memory_layer.manager", "_manager_lock"),
        ("neurova.context.env_delta", "_TRACKER_LOCK"),
        ("neurova.memory.pending_memory", "_process_lock"),
    ],
)
def test_module_singleton_lock_is_rlock(module_path: str, attr: str):
    import importlib

    mod = importlib.import_module(module_path)
    _assertRLock(getattr(mod, attr), f"{module_path}.{attr}")


def test_tool_executor_fallback_memory_manager_lock_is_rlock():
    """tool_executor 的降级 MemoryManager 缓存锁是类属性，单独取。"""
    from neurova import tool_executor as te_mod

    holder = getattr(te_mod, "ToolExecutor", None)
    if holder is None:
        pytest.skip("tool_executor.ToolExecutor 结构变化，请更新本守卫取法")
    _assertRLock(
        holder._fallback_memory_manager_lock,
        "tool_executor.ToolExecutor._fallback_memory_manager_lock",
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
