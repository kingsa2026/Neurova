"""
Tier 4B.1 RED 测试 — MemoryStorage 缺失方法验证

验证 Bug 10：storage.py 中 MemoryStorage 缺 get_recent_memories / delete_memory

调用方清单（8 处）：
- mem_core.py:486, 626 — self.storage.get_recent_memories(...)
- compression.py:176 — self._storage.get_recent_memories(...)
- compression.py:986 — self._storage.delete_memory(...)
- memory_layer.py:434 — self.storage.get_recent_memories(...)
- memory_layer.py:441 — self.storage.delete_memory(...)

预期 RED 结果：4 个测试全部 FAIL（AttributeError）
"""
from __future__ import annotations

import pytest


class TestMemoryStorageMissingMethods:
    """MemoryStorage 必须补全 get_recent_memories 和 delete_memory 方法"""

    def test_get_recent_memories_default(self, tmp_path):
        """RED: get_recent_memories(limit=10) 默认按 created_at DESC 返回 list"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        s = MemoryStorage(storage_dir=str(tmp_path))
        mid = s.save(content="hello world", memory_type="semantic", owner="u1")
        result = s.get_recent_memories(limit=10)
        assert isinstance(result, list), "RED: 缺 get_recent_memories 方法（Bug 10）"
        assert any(r.get("id") == mid for r in result), "保存的记忆应出现在结果中"

    def test_get_recent_memories_with_days_filter(self, tmp_path):
        """RED: days 参数过滤最近 N 天的记忆"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        s = MemoryStorage(storage_dir=str(tmp_path))
        s.save(content="recent memory", memory_type="semantic", owner="u1")
        # days=7 应包含刚保存的记忆
        result = s.get_recent_memories(days=7, limit=10)
        assert isinstance(result, list), "RED: 缺 get_recent_memories 方法（Bug 10）"
        assert len(result) >= 1, "刚保存的记忆应在 7 天窗口内"

    def test_get_recent_memories_respects_limit(self, tmp_path):
        """RED: limit 参数限制返回数量"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        s = MemoryStorage(storage_dir=str(tmp_path))
        for i in range(5):
            s.save(content=f"memory {i}", memory_type="semantic", owner="u1")
        result = s.get_recent_memories(limit=3)
        assert isinstance(result, list), "RED: 缺 get_recent_memories 方法（Bug 10）"
        assert len(result) == 3, "limit=3 应只返回 3 条"

    def test_delete_memory_existing(self, tmp_path):
        """RED: delete_memory 删除已存在的记忆返回 True"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        s = MemoryStorage(storage_dir=str(tmp_path))
        mid = s.save(content="to be deleted", memory_type="semantic", owner="u1")
        result = s.delete_memory(mid)
        assert result is True, "RED: 缺 delete_memory 方法或返回值错误（Bug 10）"
        # 删除后 get 应返回 None
        assert s.get(mid) is None, "删除后 get 应返回 None"

    def test_delete_memory_nonexistent(self, tmp_path):
        """RED: delete_memory 删除不存在的记忆返回 False"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        s = MemoryStorage(storage_dir=str(tmp_path))
        result = s.delete_memory("nonexistent_id_xxx")
        assert result is False, "RED: 缺 delete_memory 方法或返回值错误（Bug 10）"

    def test_delete_memory_removes_from_index(self, tmp_path):
        """RED: delete_memory 后 get_recent_memories 不再包含该记忆"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        s = MemoryStorage(storage_dir=str(tmp_path))
        mid = s.save(content="will be removed", memory_type="semantic", owner="u1")
        s.delete_memory(mid)
        result = s.get_recent_memories(limit=100)
        assert isinstance(result, list), "RED: 缺方法（Bug 10）"
        assert not any(r.get("id") == mid for r in result), "删除后不应出现在结果中"
