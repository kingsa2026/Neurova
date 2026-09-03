"""
Tier 4B.1 RED 测试 — MemoryManager._storage 生命周期验证

验证 Bug 8：manager.py:104 self._storage = None 永远不被重新赋值
验证 Bug 10：MemoryStorage 缺 get_recent_memories / delete_memory 方法

预期 RED 结果：
- test_storage_property_not_none_after_init FAIL（Bug 8）
- test_storage_has_get_recent_memories FAIL（Bug 8 + Bug 10）
- test_storage_has_delete_memory FAIL（Bug 8 + Bug 10）
- test_get_recent_memories_returns_list FAIL（Bug 8 + Bug 10）
"""
from __future__ import annotations

import pytest


class TestManagerStorageLifecycle:
    """MemoryManager 实例化后 storage property 必须非 None 且具备所需方法"""

    def test_storage_property_not_none_after_init(self, tmp_path):
        """RED: MemoryManager 实例化后 storage property 必须非 None（Bug 8）"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        mgr = MemoryManager(db_path=str(tmp_path / "test_mgr.db"))
        try:
            assert mgr.storage is not None, "RED: storage 永远 None（Bug 8）"
        finally:
            # 清理：若有 close 方法则调用
            if hasattr(mgr, "close"):
                mgr.close()

    def test_storage_has_get_recent_memories(self, tmp_path):
        """RED: storage 必须有 get_recent_memories 方法（Bug 10）"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        mgr = MemoryManager(db_path=str(tmp_path / "test_mgr.db"))
        try:
            assert mgr.storage is not None, "storage 为 None，无法检测方法"
            assert hasattr(mgr.storage, "get_recent_memories"), (
                "RED: 缺 get_recent_memories 方法（Bug 10）"
            )
        finally:
            if hasattr(mgr, "close"):
                mgr.close()

    def test_storage_has_delete_memory(self, tmp_path):
        """RED: storage 必须有 delete_memory 方法（Bug 10）"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        mgr = MemoryManager(db_path=str(tmp_path / "test_mgr.db"))
        try:
            assert mgr.storage is not None, "storage 为 None，无法检测方法"
            assert hasattr(mgr.storage, "delete_memory"), (
                "RED: 缺 delete_memory 方法（Bug 10）"
            )
        finally:
            if hasattr(mgr, "close"):
                mgr.close()

    def test_get_recent_memories_returns_list(self, tmp_path):
        """RED: storage.get_recent_memories(limit=10) 应返回 list"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        mgr = MemoryManager(db_path=str(tmp_path / "test_mgr.db"))
        try:
            assert mgr.storage is not None, "storage 为 None"
            result = mgr.storage.get_recent_memories(limit=10)
            assert isinstance(result, list), (
                f"RED: 返回类型错误，期望 list 实际 {type(result).__name__}"
            )
        finally:
            if hasattr(mgr, "close"):
                mgr.close()
