"""MemoryExporter 记忆可解释性（Markdown 导出/导入）单元测试。

对齐升级方案 P1-2.2：
- 把 17 维记忆转成可读 Markdown（含时间戳、置信度、关联）
- 用户在 Web 端编辑后写回；写回走「版本化 diff」，仅编辑文本层，
  不触碰向量索引/embedding（方案 7 风险对策）。
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock


def _memory(mid="mem-001", content="用户喜欢简洁的回复", category="preference",
            importance=0.8, temperature=0.5):
    return {
        "id": mid,
        "content": content,
        "category": category,
        "importance": importance,
        "temperature": temperature,
        "lifecycle_stage": "active",
        "created_at": "2026-08-01T10:00:00",
        "updated_at": "2026-08-02T11:00:00",
        "access_count": 5,
    }


def _make_manager(memories=None):
    mgr = MagicMock()
    mgr.get_memories.return_value = list(memories or [])
    def _get(memory_id):
        for m in memories or []:
            if m["id"] == memory_id:
                return dict(m)
        return None
    mgr.get_memory.side_effect = _get
    return mgr


class TestMarkdownExport(unittest.TestCase):
    """导出为可读 Markdown。"""

    def test_export_contains_header_and_entry(self):
        from neurova.cognitive_layers.memory_layer.memory_exporter import MemoryExporter

        exporter = MemoryExporter(_make_manager([_memory()]))
        md = exporter.export_markdown()
        self.assertIn("# Neurova 记忆导出", md)
        self.assertIn("mem-001", md)
        self.assertIn("preference", md)
        self.assertIn("用户喜欢简洁的回复", md)

    def test_export_includes_metadata_line(self):
        from neurova.cognitive_layers.memory_layer.memory_exporter import MemoryExporter

        md = MemoryExporter(_make_manager([_memory(importance=0.9)])).export_markdown()
        self.assertIn("重要度: 0.90", md)

    def test_export_multiple_memories_have_entries(self):
        from neurova.cognitive_layers.memory_layer.memory_exporter import MemoryExporter

        mems = [_memory("m1"), _memory("m2", content="第二条")]
        md = MemoryExporter(_make_manager(mems)).export_markdown()
        self.assertIn("m1", md)
        self.assertIn("m2", md)

    def test_export_empty_returns_valid_markdown(self):
        from neurova.cognitive_layers.memory_layer.memory_exporter import MemoryExporter

        md = MemoryExporter(_make_manager([])).export_markdown()
        self.assertIn("# Neurova 记忆导出", md)


class TestImportVersionedDiff(unittest.TestCase):
    """导入走版本化 diff：只改文本层。"""

    def setUp(self):
        from neurova.cognitive_layers.memory_layer.memory_exporter import MemoryExporter

        self.MemoryExporter = MemoryExporter
        self.manager = _make_manager([_memory()])
        self.exporter = MemoryExporter(self.manager)

    def test_roundtrip_unmodified_yields_no_changes(self):
        md = self.exporter.export_markdown()
        plan = self.exporter.parse_edited_markdown(md)
        self.assertEqual(len(plan.entries), 1)
        self.assertFalse(plan.entries[0].changed)

    def test_edited_body_produces_diff(self):
        md = self.exporter.export_markdown()
        edited = md.replace("用户喜欢简洁的回复", "用户偏好要点式回复")
        plan = self.exporter.parse_edited_markdown(edited)
        entry = plan.entries[0]
        self.assertTrue(entry.changed)
        self.assertEqual(entry.old_content, "用户喜欢简洁的回复")
        self.assertEqual(entry.new_content, "用户偏好要点式回复")
        # 版本化：记录基准版本（原 updated_at），用于并发冲突检测
        self.assertEqual(entry.base_version, "2026-08-02T11:00:00")

    def test_apply_updates_only_changed_via_text_layer(self):
        md = self.exporter.export_markdown()
        edited = md.replace("用户喜欢简洁的回复", "新正文")
        plan = self.exporter.parse_edited_markdown(edited)
        stats = self.exporter.apply(plan, manager=self.manager)

        self.assertEqual(stats["updated"], 1)
        # 关键约束：仅更新 content 文本层 —— 不传 embedding 相关字段，
        # 向量索引保持不动（方案 7 风险对策）
        args, kwargs = self.manager.update_memory.call_args
        self.assertEqual(args[0], "mem-001")
        self.assertEqual(kwargs.get("content"), "新正文")
        self.assertNotIn("embedding", kwargs)

    def test_apply_skips_unchanged(self):
        md = self.exporter.export_markdown()
        plan = self.exporter.parse_edited_markdown(md)
        stats = self.exporter.apply(plan, manager=self.manager)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats["unchanged"], 1)
        self.manager.update_memory.assert_not_called()

    def test_missing_memory_reported_not_crash(self):
        md = self.exporter.export_markdown().replace("mem-001", "ghost-id")
        plan = self.exporter.parse_edited_markdown(md)
        stats = self.exporter.apply(plan, manager=self.manager)
        self.assertEqual(stats["missing"], 1)

    def test_version_conflict_detected(self):
        """base_version 与当前 updated_at 不一致 → 冲突，不覆盖。"""
        md = self.exporter.export_markdown()
        edited = md.replace("用户喜欢简洁的回复", "并发期间的新编辑")
        plan = self.exporter.parse_edited_markdown(edited)
        # 模拟另一端已更新该记忆
        self.manager.get_memory.side_effect = None
        current = _memory()
        current["updated_at"] = "2026-08-03T00:00:00"
        self.manager.get_memory.return_value = current

        stats = self.exporter.apply(plan, manager=self.manager, strict_version=True)
        self.assertEqual(stats.get("conflicts"), 1)
        self.assertEqual(stats.get("updated", 0), 0)
        self.manager.update_memory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
