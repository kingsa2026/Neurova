"""反思闭环接线测试（P0）

覆盖两条断链的根因修复:
- P0-1: injector 读侧访问 ReflectionLogEntry 上不存在的字段
  （log.situation/log.lesson/log.reflection_type → 实际字段为 title/content/type/insights），
  异常被 try/except 吞掉后反思上下文永远是空字符串。
- P0-2: GrowthLogManager 与 MemoryManager 真实 API 错配
  （remember/search_memories/update_memory 是同步方法却被 await；
  search_memories(query, limit) 没有 memory_type 参数；on_initialize 无人调用）。
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionType,
)
from neurova.context.injector import UnifiedContextInjector


class ReflectionClosedLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "reflection_loop.db")
        self.memory_manager = MemoryManager(
            db_path=self.db_path,
            agent_id="test_agent",
            user_id="test_user",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_manager(self):
        return GrowthLogManager(memory_manager=self.memory_manager)

    def _make_entry(self, glm):
        return asyncio.run(
            glm.generate_log(
                type=ReflectionType.ERROR,
                title="工具调用失败反思",
                content="应先检查参数类型再调用工具",
                insights=["调用前先验证参数"],
                action_items=["补充参数校验"],
                confidence=0.7,
            )
        )

    def test_generate_log_persists_to_memory_manager(self):
        glm = self._make_manager()
        entry = self._make_entry(glm)
        self.assertTrue(entry.memory_id, "generate_log 应同步落库并回填 memory_id")

    def test_load_existing_logs_restores_from_same_manager(self):
        glm = self._make_manager()
        entry = self._make_entry(glm)

        glm2 = self._make_manager()
        glm2._load_existing_logs()

        self.assertEqual(len(glm2._cache), 1)
        restored = next(iter(glm2._cache.values()))
        self.assertEqual(restored.content, entry.content)
        self.assertEqual(restored.title, entry.title)
        self.assertEqual(restored.memory_id, entry.memory_id)

    def test_reflection_memory_roundtrip_via_category(self):
        """反思日志必须以 category=reflection 落库（MemoryType 无 reflection 值），且可按分类找回"""
        glm = self._make_manager()
        self._make_entry(glm)

        all_memories = self.memory_manager.get_all_memories()
        reflections = [m for m in all_memories if m.get("category") == "reflection"]
        self.assertEqual(len(reflections), 1)
        self.assertIn("reflection_log", reflections[0].get("metadata", {}))

    def test_injector_builds_reflection_context_from_real_fields(self):
        glm = self._make_manager()
        entry = self._make_entry(glm)

        injector = UnifiedContextInjector(
            memory_manager=self.memory_manager,
            growth_log_manager=glm,
        )

        ctx = injector._build_reflection_context()
        self.assertTrue(ctx.strip(), "反思上下文不应为空（读侧字段错位会被 except 吞成空串）")
        self.assertIn(entry.title, ctx)
        # 格式契约: 标题 → 教训（有洞察用洞察，否则回退正文）
        self.assertIn(entry.insights[0], ctx)

    def test_injector_get_reflection_logs_for_context(self):
        glm = self._make_manager()
        entry = self._make_entry(glm)

        injector = UnifiedContextInjector(
            memory_manager=self.memory_manager,
            growth_log_manager=glm,
        )

        ctx = injector.get_reflection_logs_for_context()
        self.assertTrue(ctx.strip())
        self.assertIn(ReflectionType.ERROR.value, ctx)
        self.assertIn(entry.content, ctx)


if __name__ == "__main__":
    unittest.main()
