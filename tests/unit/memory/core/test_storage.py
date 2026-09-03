"""
MemoryStorage（JSON 文件存储）单元测试 — 按当前真实 API 重写

真实 API:
- MemoryStorage(storage_dir)
- save(content, memory_type, owner, tags, metadata, importance, isolation_context) -> str(id)
- get / delete / count / get_stats / update_memory / batch_save / batch_delete
- query / list_all / list_by_tags / get_recent_memories / increment_access / clear
"""

import tempfile
import unittest
from pathlib import Path


class TestMemoryStorage(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage_dir = self._tmp.name

    def _create_store(self):
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        return MemoryStorage(storage_dir=self.storage_dir)

    # ----------------------------- 基础 CRUD -----------------------------

    def test_storage_ready_after_init(self):
        store = self._create_store()
        self.assertEqual(store.count(), 0)
        self.assertTrue(self.storage_dir)

    def test_save_returns_id_and_get_roundtrip(self):
        store = self._create_store()
        mem_id = store.save(content="测试记忆内容", memory_type="episodic", owner="a1")
        self.assertTrue(mem_id)

        mem = store.get(mem_id)
        self.assertIsNotNone(mem)
        self.assertEqual(mem["content"], "测试记忆内容")
        self.assertEqual(mem["memory_type"], "episodic")
        store.close() if hasattr(store, "close") else None

    def test_save_with_metadata_and_tags(self):
        store = self._create_store()
        mem_id = store.save(
            content="带标签",
            memory_type="semantic",
            tags=["旅行", "计划"],
            metadata={"source": "chat"},
            importance=0.8,
        )
        mem = store.get(mem_id)
        self.assertIn("旅行", mem.get("tags", []))
        self.assertEqual(mem.get("metadata", {}).get("source"), "chat")

    def test_get_missing_returns_none(self):
        store = self._create_store()
        self.assertIsNone(store.get("ghost"))

    def test_delete(self):
        store = self._create_store()
        mem_id = store.save(content="待删除", memory_type="episodic")
        self.assertTrue(store.delete(mem_id))
        self.assertIsNone(store.get(mem_id))

    def test_persistence_across_reopen(self):
        """重启模拟：新实例仍能读到已保存数据"""
        store = self._create_store()
        mem_id = store.save(content="跨实例存活", memory_type="episodic")
        del store

        reopened = self._create_store()
        self.assertIsNotNone(reopened.get(mem_id))
        self.assertEqual(reopened.get(mem_id)["content"], "跨实例存活")

    # ----------------------------- 列表与统计 -----------------------------

    def test_count_and_list_all(self):
        store = self._create_store()
        for i in range(3):
            store.save(content=f"记忆{i}", memory_type="episodic")
        self.assertEqual(store.count(), 3)
        self.assertEqual(len(store.list_all()), 3)

    def test_list_by_tags(self):
        store = self._create_store()
        store.save(content="A", memory_type="episodic", tags=["work"])
        store.save(content="B", memory_type="episodic", tags=["life"])
        hits = store.list_by_tags(["work"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["content"], "A")

    def test_query_filters_by_type_and_tags(self):
        store = self._create_store()
        store.save(content="青海湖之旅", memory_type="episodic", tags=["travel"])
        store.save(content="写代码", memory_type="semantic", tags=["work"])

        by_type = store.query(memory_type="semantic")
        self.assertEqual(len(by_type), 1)
        self.assertIn("写代码", by_type[0]["content"])

        by_tag = store.query(tags=["travel"])
        self.assertEqual(len(by_tag), 1)
        self.assertIn("青海湖之旅", by_tag[0]["content"])

    def test_get_stats(self):
        store = self._create_store()
        store.save(content="s1", memory_type="episodic")
        stats = store.get_stats()
        self.assertIsInstance(stats, dict)

    # ----------------------------- 更新与批量 -----------------------------

    def test_update_memory(self):
        store = self._create_store()
        mem_id = store.save(content="原始", memory_type="episodic")
        result = store.update_memory(mem_id, content="更新后")
        mem = store.get(mem_id)
        self.assertTrue(result or (mem and mem["content"] == "更新后"))

    def test_batch_save_and_delete(self):
        store = self._create_store()
        items = [
            {"content": f"b{i}", "memory_type": "episodic"} for i in range(3)
        ]
        ids = store.batch_save(items)
        self.assertEqual(len(ids), 3)
        self.assertEqual(store.count(), 3)
        deleted = store.batch_delete(ids[:2])
        self.assertEqual(deleted, 2)
        self.assertEqual(store.count(), 1)


if __name__ == "__main__":
    unittest.main()
