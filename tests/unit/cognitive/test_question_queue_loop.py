"""主动提问闭环测试（P1-A + P3）

覆盖 QuestionQueueManager 从零调用骨架到真实闭环的接入:
- P3: meta_cognition_layer/__init__.py 空骨架导出修复
- P1-A 生成端: 反思步骤在困惑/不确定触发时生成澄清型问题入队（带去重）
- P1-A 消费端: 主动提问步骤弹出问题并 mark_asked 进入冷却
- QuestionQueueManager 自身持久化断链: _load_questions_from_memory 调不存在的
  memory_manager.search(...)（真实 API 是 get_memories(category=...)）
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from neurova.cognitive_layers.meta_cognition_layer.question_queue import (
    QuestionQueueManager,
    QuestionStatus,
)
from neurova.post_chat_pipeline import PostChatPipeline


def _make_memory_manager(tmpdir):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(
        db_path=os.path.join(tmpdir, "question_loop.db"),
        agent_id="test_agent",
        user_id="test_user",
    )


class MetaCognitionExportsTest(unittest.TestCase):
    def test_package_exports_public_classes(self):
        from neurova.cognitive_layers import meta_cognition_layer as mcl

        self.assertTrue(hasattr(mcl, "GrowthLogManager"), "包应导出 GrowthLogManager")
        self.assertTrue(hasattr(mcl, "QuestionQueueManager"), "包应导出 QuestionQueueManager")
        self.assertTrue(hasattr(mcl, "ReflectionLogEntry"), "包应导出 ReflectionLogEntry")


class QuestionGenerationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mm = _make_memory_manager(self.tmpdir)
        self.queue = QuestionQueueManager(memory_manager=self.mm, default_cooldown=300.0)
        from neurova.cognitive_layers.meta_cognition_layer.growth_log import GrowthLogManager

        self.glm = GrowthLogManager(memory_manager=self.mm)
        agent = SimpleNamespace(
            growth_log_manager=self.glm,
            question_queue_manager=self.queue,
            _turn_count=0,
        )
        self.pipeline = PostChatPipeline(agent)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reflection_generates_question_on_confusion(self):
        asyncio.run(self.pipeline._step_reflection("我不明白这个结果是怎么来的", "这是计算得出的"))

        pending = self.queue.get_pending_questions()
        self.assertGreaterEqual(len(pending), 1, "困惑触发反思时应生成澄清型问题")
        self.assertIn("不明白", pending[0].content, "问题应引用用户原始困惑内容")

    def test_reflection_does_not_generate_on_periodic(self):
        # 无困惑/不确定关键词 + 非周期触发（_turn_count=0 不满足周期条件）
        # 周期触发路径需要 _turn_count 为 10 的倍数；这里用普通对话避免误触发
        agent = SimpleNamespace(
            growth_log_manager=self.glm,
            question_queue_manager=self.queue,
            _turn_count=10,
        )
        pipeline = PostChatPipeline(agent)
        asyncio.run(pipeline._step_reflection("今天天气不错", "是的，天气很好"))

        self.assertEqual(
            self.queue.get_pending_questions(),
            [],
            "周期性反思不应生成澄清型问题（避免打扰）",
        )

    def test_generation_dedupes_identical_pending(self):
        asyncio.run(self.pipeline._step_reflection("我不明白这个结果", "回答一"))
        asyncio.run(self.pipeline._step_reflection("我不明白这个结果", "回答二"))

        pending = self.queue.get_pending_questions()
        contents = [q.content for q in pending]
        self.assertEqual(
            len(contents),
            len(set(contents)),
            "同一困惑不应重复入队",
        )

    def test_question_queue_persists_via_memory_manager(self):
        """问题应通过 MemoryManager 持久化并可在新实例中恢复（category=system）"""
        self.queue.generate_question("跨重启的问题?")
        self.queue._save_questions_to_memory()

        restored = QuestionQueueManager(memory_manager=self.mm, default_cooldown=300.0)
        restored.on_initialize()

        self.assertEqual(len(restored._questions), 1)
        self.assertIn("跨重启的问题?", [q.content for q in restored._questions.values()])


class QuestionConsumptionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mm = _make_memory_manager(self.tmpdir)
        self.queue = QuestionQueueManager(memory_manager=self.mm, default_cooldown=300.0)
        agent = SimpleNamespace(question_queue_manager=self.queue)
        self.pipeline = PostChatPipeline(agent)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proactive_step_surfaces_next_question_and_marks_asked(self):
        self.queue.generate_question("要不要把结果导出成表格?")
        result = asyncio.run(self.pipeline._step_proactive_question("你好", "你好呀"))

        self.assertEqual(result, "要不要把结果导出成表格?")
        asked = self.queue.get_questions_by_status(QuestionStatus.ASKED)
        self.assertEqual(len(asked), 1, "弹出的问题应标记为已提问")
        self.assertIsNotNone(asked[0].cooldown_until, "已提问问题应进入冷却")

    def test_proactive_step_respects_cooldown(self):
        self.queue.generate_question("冷却中的问题?")
        first = asyncio.run(self.pipeline._step_proactive_question("a", "b"))
        second = asyncio.run(self.pipeline._step_proactive_question("a", "b"))

        self.assertIsNotNone(first)
        self.assertIsNone(second, "冷却期内不应重复提出同一问题")

    def test_proactive_step_returns_none_on_empty_queue(self):
        result = asyncio.run(self.pipeline._step_proactive_question("a", "b"))
        self.assertIsNone(result)


class QuestionQueueMarkAnsweredTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mm = _make_memory_manager(self.tmpdir)
        self.queue = QuestionQueueManager(memory_manager=self.mm, default_cooldown=300.0)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mark_answered(self):
        entry = self.queue.generate_question("待回答问题?")
        self.assertTrue(self.queue.mark_answered(entry.id, answer="答案内容"))

        stored = self.queue.get_question(entry.id)
        self.assertEqual(stored.status, QuestionStatus.ANSWERED)
        self.assertEqual(stored.metadata.get("answer"), "答案内容")
        self.assertIsNotNone(stored.answered_at)

    def test_state_changes_update_in_place_without_duplicates(self):
        """根因修复验证: 状态流转必须原位更新同一条记忆，不得每次 remember 复制"""
        import json as _json

        entry = self.queue.generate_question("原位更新的问题?")
        self.queue.mark_asked(entry.id)
        self.queue.mark_answered(entry.id, answer="好的")

        memories = self.mm.get_memories(category="system", limit=100)
        q_mems = [m for m in memories if (m.get("metadata") or {}).get("question_id") == entry.id]
        self.assertEqual(
            len(q_mems),
            1,
            "generate→asked→answered 三次保存应只占 1 条记忆",
        )
        stored = _json.loads(q_mems[0]["content"])
        self.assertEqual(stored["status"], "answered")
        self.assertEqual(stored["metadata"].get("answer"), "好的")


if __name__ == "__main__":
    unittest.main()
