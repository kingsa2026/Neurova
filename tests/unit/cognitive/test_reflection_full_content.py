"""反思日志正文源端截断根因测试（2026-09-15）

问题：反思日志页"打开"详情看到的正文停在半句——不是显示不全，而是
生成时就被真截断：post_chat_pipeline Step 8.5 用
`user_input[:200] / reply[:200]` 切片后才写入 generate_log，
落库的 content 里根本没有后面的内容，前端/注入层无从恢复。

根因修复契约：
1. 生成侧存全文（截断只允许发生在"展示/注入"层）；
2. 注入侧预算守卫：[反思] 行在渲染进 prompt 时封顶，
   防止存全文后每轮恒定注入把提示词撑爆；
3. 存储链（GrowthLogManager→MemoryManager→重启恢复）不引入新截断。
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionType,
)


class _FakeGrowthLogManager:
    """捕获 generate_log 入参，验证生成侧写入内容"""

    def __init__(self):
        self.calls = []

    async def generate_log(self, **kwargs):
        self.calls.append(kwargs)
        entry = MagicMock()
        entry.id = "test-reflection-id"
        return entry


def _make_pipeline(growth_log_manager):
    from neurova.post_chat_pipeline import PostChatPipeline

    agent = MagicMock()
    agent.turn_count = 25  # 非 10 的倍数，只允许关键词触发反思
    agent.growth_log_manager = growth_log_manager
    pipeline = PostChatPipeline(agent)
    pipeline.configure(growth_log_manager=growth_log_manager)
    return pipeline


class ReflectionSourceNoTruncationTest(unittest.TestCase):
    def test_step_reflection_stores_full_user_input_and_reply(self):
        """用户输入与 Agent 回复超过 200 字时，落库 content 必须含完整原文"""
        glog = _FakeGrowthLogManager()
        pipeline = _make_pipeline(glog)

        # 尾部必须唯一：纯重复文本的 [:200] 头部会"碰巧"含尾段子串，造成假绿
        long_user = "不明白，这个问题为什么这样处理，请解释一下原因。" * 30 + "<<用户输入结束标记>>"
        long_reply = "关于你的疑问，这里给出完整解释。" * 60 + "<<回复结束标记>>"

        asyncio.run(pipeline._step_reflection(long_user, long_reply))

        self.assertEqual(len(glog.calls), 1, "困惑关键词应触发一条反思日志")
        content = glog.calls[0]["content"]
        self.assertIn(
            long_reply[-20:],
            content,
            "正文尾部出现在 content 中——若被 [:200] 切片此处必然失败（源端真截断）",
        )
        self.assertIn(
            long_user[-20:],
            content,
            "用户输入同样必须完整保留",
        )

    def test_step_reflection_context_keeps_lengths(self):
        """context 中的长度元信息与实际原文一致（截断修复后不得造假）"""
        glog = _FakeGrowthLogManager()
        pipeline = _make_pipeline(glog)

        user_input = "不明白"
        reply = "回复" * 300

        asyncio.run(pipeline._step_reflection(user_input, reply))

        ctx = glog.calls[0]["context"]
        self.assertEqual(ctx["user_input_length"], len(user_input))
        self.assertEqual(ctx["reply_length"], len(reply))


class ReflectionPromptInjectionBudgetTest(unittest.TestCase):
    def test_render_reflection_line_clips_long_lesson(self):
        """[反思] 行渲染封顶（信封/注入层单源，见 models）"""
        from neurova.context.models import render_reflection_line

        long_lesson = "工" * 2000
        line = render_reflection_line({"lesson": long_lesson, "status": "pending"})
        self.assertTrue(line.startswith("[反思]"))
        self.assertLessEqual(
            len(line),
            500,
            "注入行应被封顶在预算内（约 400 字 + 前缀/省略号）",
        )

    def test_render_reflection_line_keeps_short_lesson_intact(self):
        from neurova.context.models import render_reflection_line

        lesson = "工具执行失败后应降低自动执行置信度"
        line = render_reflection_line({"lesson": lesson, "status": "pending"})
        self.assertEqual(line, f"[反思] {lesson}")


class ReflectionStorageRoundtripTest(unittest.TestCase):
    """回归钉：存储/恢复链对长正文零截断（修复后防复发）"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory_manager = MemoryManager(
            db_path=os.path.join(self.tmpdir, "reflection_full.db"),
            agent_id="test_agent",
            user_id="test_user",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_long_content_survives_persist_and_reload(self):
        full_text = "完整反思正文。" * 1000  # 5000 字
        glm = GrowthLogManager(memory_manager=self.memory_manager)
        entry = asyncio.run(
            glm.generate_log(
                type=ReflectionType.IMPROVEMENT,
                title="长正文回归",
                content=full_text,
            )
        )
        self.assertEqual(entry.content, full_text)

        glm2 = GrowthLogManager(memory_manager=self.memory_manager)
        restored = next(iter(glm2._cache.values()))
        self.assertEqual(restored.content, full_text, "重启恢复链不得引入截断")


if __name__ == "__main__":
    unittest.main()
