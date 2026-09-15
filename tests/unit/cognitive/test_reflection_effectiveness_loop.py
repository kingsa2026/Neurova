"""反思效力闭环测试（2026-09-15 推荐方案 P0-P3）

根因：反思日志生命周期四个生产者全缺——注入不留痕、状态永不流转
（恒 pending）、applied/validated/archive 无人调用、回声内容无教训。
修复契约（TDD）：

P0a 注入留痕：选中注入的日志 id 挂 turn ContextVar → 随 assistant
    metadata.injected_reflections 落盘；注入时 pending→applied。
P0b 效力反馈：/chat/feedback 消费该痕迹——like→validated，
    dislike→降置信（跌破 0.3 转 rejected，原文保留不删）。
P0c 困惑降权：Step 8.5 检测到用户困惑且本轮有注入痕迹 → 逐条降置信。
P1 写侧教训化：Step 8.5 确定性合成 insights/action_items，
    content=教训句+全文对话（截断修复契约不回退）。
P2 生命周期治理：prune 重复 pending + 30 天归档（同步 maintain_lifecycle）。
P3 注入分层：validated 按置信 top2 优先，pending/applied 按时间补足，
    总 ≤3 条；envelope 教训行截断 60→单源 200。
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionLogStatus,
    ReflectionType,
)


def _make_glog(tmp_pool=[]):
    """真 MemoryManager（临时库）支撑的 GrowthLogManager——绝不连生产库（EKB 事故教训）"""
    d = tempfile.mkdtemp()
    tmp_pool.append(d)
    mm = MemoryManager(
        db_path=os.path.join(d, "eff.db"),
        agent_id="eff_agent",
        user_id="eff_user",
    )
    return GrowthLogManager(memory_manager=mm)


class RegisterNegativeFeedbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = []
        self.glog = _make_glog(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp[0], ignore_errors=True)

    def _add(self, confidence=0.5):
        return asyncio.run(
            self.glog.generate_log(
                type=ReflectionType.ERROR,
                title="t",
                content="c",
                confidence=confidence,
            )
        )

    def test_negative_feedback_demotes(self):
        e = self._add(0.5)
        self.glog.register_negative_feedback(e.id)
        self.assertAlmostEqual(self.glog._cache[e.id].confidence, 0.35, places=5)
        self.assertEqual(self.glog._cache[e.id].status, ReflectionLogStatus.PENDING)

    def test_double_negative_rejects_but_keeps_entry(self):
        e = self._add(0.5)
        self.glog.register_negative_feedback(e.id)
        self.glog.register_negative_feedback(e.id)
        entry = self.glog._cache[e.id]
        self.assertEqual(entry.status, ReflectionLogStatus.REJECTED)
        self.assertIn(e.id, self.glog._cache, "reject 只降不删，原文仍可语义召回")

    def test_unknown_id_returns_false(self):
        self.assertFalse(self.glog.register_negative_feedback("nope"))


class MaintainLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = []
        self.glog = _make_glog(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp[0], ignore_errors=True)

    def test_prune_duplicate_pending_keeps_latest(self):
        e1 = asyncio.run(
            self.glog.generate_log(type=ReflectionType.ERROR, title="对话反思", content="同样的回声正文A")
        )
        e2 = asyncio.run(
            self.glog.generate_log(type=ReflectionType.ERROR, title="对话反思", content="同样的回声正文A")
        )
        e1.timestamp -= 100  # e1 更旧
        e3 = asyncio.run(
            self.glog.generate_log(type=ReflectionType.ERROR, title="对话反思", content="不同的正文B")
        )
        changed = self.glog.maintain_lifecycle()
        self.assertEqual(self.glog._cache[e1.id].status, ReflectionLogStatus.ARCHIVED)
        self.assertEqual(self.glog._cache[e2.id].status, ReflectionLogStatus.PENDING)
        self.assertEqual(self.glog._cache[e3.id].status, ReflectionLogStatus.PENDING)
        self.assertGreaterEqual(changed["pruned"], 1)

    def test_archive_old_logs(self):
        e = asyncio.run(
            self.glog.generate_log(type=ReflectionType.PERFORMANCE, title="t", content="ancient")
        )
        e.timestamp -= 40 * 86400
        changed = self.glog.maintain_lifecycle(max_age_days=30)
        self.assertEqual(self.glog._cache[e.id].status, ReflectionLogStatus.ARCHIVED)
        self.assertGreaterEqual(changed["archived"], 1)

    def test_archive_old_logs_async_wrapper_still_works(self):
        e = asyncio.run(
            self.glog.generate_log(type=ReflectionType.PERFORMANCE, title="t", content="ancient2")
        )
        e.timestamp -= 40 * 86400
        n = asyncio.run(self.glog.archive_old_logs(max_age_days=30))
        self.assertGreaterEqual(n, 1)


class SelectAndMarkInjectionTest(unittest.TestCase):
    """P0a/P3：分层选择 + 注入即 applied + 轮次痕迹 ContextVar"""

    def setUp(self):
        self._tmp = []
        self.glog = _make_glog(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp[0], ignore_errors=True)

    def _add(self, type_=ReflectionType.ERROR, confidence=0.5, status=None):
        e = asyncio.run(self.glog.generate_log(type=type_, title="t", content="c" * 50, confidence=confidence))
        if status is not None:
            e.status = status
        return e

    def test_validated_top2_then_pending_fill(self):
        from neurova.context.orchestrator import select_reflection_logs

        self._add(confidence=0.9, status=ReflectionLogStatus.VALIDATED)
        self._add(confidence=0.8, status=ReflectionLogStatus.VALIDATED)
        self._add(confidence=0.99, status=ReflectionLogStatus.VALIDATED)
        p = self._add(confidence=0.4)  # pending 补位
        selected = select_reflection_logs(self.glog)
        self.assertEqual(len(selected), 3, "总预算 ≤3")
        confs = [e.confidence for e in selected if e.status == ReflectionLogStatus.VALIDATED]
        self.assertIn(0.99, confs)
        self.assertIn(0.9, confs)
        self.assertNotIn(0.8, confs, "validated 只取置信 top2")
        self.assertIn(p.id, [e.id for e in selected])

    def test_all_pending_cap3(self):
        from neurova.context.orchestrator import select_reflection_logs

        for i in range(5):
            self._add(confidence=0.5 + i / 10)
        selected = select_reflection_logs(self.glog)
        self.assertEqual(len(selected), 3)

    def test_rejected_archived_excluded(self):
        from neurova.context.orchestrator import select_reflection_logs

        self._add(confidence=0.9, status=ReflectionLogStatus.REJECTED)
        self._add(confidence=0.9, status=ReflectionLogStatus.ARCHIVED)
        self.assertEqual(select_reflection_logs(self.glog), [])

    def test_mark_injected_marks_pending_applied_and_records_trace(self):
        from neurova.context.orchestrator import mark_injected_logs, select_reflection_logs
        from neurova.core.turn_context import get_turn_injected_reflections

        e = self._add(confidence=0.6)
        logs = select_reflection_logs(self.glog)

        # 断言须与 set 同协程：asyncio.run 会创建子 task 复制上下文，
        # 其内 set() 不回传外层（生产链 build/post-chat 同 task，无此问题）
        async def scenario():
            await mark_injected_logs(self.glog, logs)
            return get_turn_injected_reflections()

        trace = asyncio.run(scenario())
        self.assertEqual(self.glog._cache[e.id].status, ReflectionLogStatus.APPLIED)
        self.assertEqual(trace, [e.id])

    def test_mark_injected_does_not_touch_validated(self):
        from neurova.context.orchestrator import mark_injected_logs, select_reflection_logs

        v = self._add(confidence=0.9, status=ReflectionLogStatus.VALIDATED)
        logs = select_reflection_logs(self.glog)
        asyncio.run(mark_injected_logs(self.glog, logs))
        self.assertEqual(self.glog._cache[v.id].status, ReflectionLogStatus.VALIDATED)


class EnvelopeLessonCapTest(unittest.TestCase):
    def test_envelope_lesson_not_clipped_at_60(self):
        """P3：信封块教训行截断从 60 放宽到单源 200（150 字教训须完整）"""
        self._tmp = []
        glog = _make_glog(self._tmp)
        try:
            long_lesson = "教" * 150
            asyncio.run(
                glog.generate_log(
                    type=ReflectionType.IMPROVEMENT,
                    title="t",
                    content="x",
                    insights=[long_lesson],
                )
            )
            from neurova.context.injector import UnifiedContextInjector

            injector = UnifiedContextInjector(memory_manager=MagicMock(), growth_log_manager=glog)
            ctx = injector._build_reflection_context()
            self.assertIn(long_lesson, ctx, "150 字教训应完整进入信封块（旧 [:60] 会腰斩）")
        finally:
            shutil.rmtree(self._tmp[0], ignore_errors=True)


class StepReflectionLessonTest(unittest.TestCase):
    """P1/P0c：Step 8.5 教训化 + 困惑降权注入痕迹"""

    def setUp(self):
        self._tmp = []
        self.glog = _make_glog(self._tmp)
        from neurova.post_chat_pipeline import PostChatPipeline

        agent = MagicMock()
        agent.turn_count = 23
        agent.growth_log_manager = self.glog
        self.pipeline = PostChatPipeline(agent)
        self.pipeline.configure(growth_log_manager=self.glog)

    def tearDown(self):
        shutil.rmtree(self._tmp[0], ignore_errors=True)

    def test_confusion_produces_lesson_insights(self):
        asyncio.run(self.pipeline._step_reflection("我不明白这个答案，能再解释吗", "回复" * 300))
        entries = self.glog.read_logs(limit=10)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertTrue(entry.insights, "教训化：insights 不得再恒为空")
        self.assertTrue(entry.action_items, "行动项须非空")
        self.assertIn("困惑", entry.insights[0])
        # 全文不丢：教训句 + 完整对话（截断修复契约不回退）
        self.assertIn("回复" * 300, entry.content)

    def test_confusion_demotes_injected_trace(self):
        from neurova.core.turn_context import set_turn_injected_reflections

        e = asyncio.run(
            self.glog.generate_log(
                type=ReflectionType.ERROR, title="注入过的教训", content="旧反思", confidence=0.5
            )
        )
        set_turn_injected_reflections([e.id])
        try:
            asyncio.run(self.pipeline._step_reflection("你说的不对，重新回答", "回复" * 10))
            self.assertAlmostEqual(self.glog._cache[e.id].confidence, 0.35, places=5)
        finally:
            set_turn_injected_reflections(None)

    def test_no_trace_no_demotion(self):
        from neurova.core.turn_context import set_turn_injected_reflections

        e = asyncio.run(
            self.glog.generate_log(type=ReflectionType.ERROR, title="无关于本轮", content="x", confidence=0.5)
        )
        set_turn_injected_reflections(None)
        asyncio.run(self.pipeline._step_reflection("不明白", "回复" * 10))
        self.assertAlmostEqual(self.glog._cache[e.id].confidence, 0.5, places=5)


class SaveSessionTraceTest(unittest.TestCase):
    """P0a：injected_reflections 随 assistant metadata 落盘"""

    def setUp(self):
        from neurova.post_chat_pipeline import PostChatPipeline

        self.agent = MagicMock()
        self.agent._save_to_session = MagicMock(return_value="sess-1")
        self.agent._collect_tool_messages = MagicMock(return_value=[])
        self.pipeline = PostChatPipeline(self.agent)

    def test_assistant_metadata_carries_trace(self):
        from neurova.core.turn_context import set_turn_injected_reflections

        set_turn_injected_reflections(["r1", "r2"])
        try:
            asyncio.run(
                self.pipeline._step_save_session(
                    user_input="q",
                    reply="a",
                    session_id="sess-1",
                    save_memory=True,
                    metadata={},
                )
            )
        finally:
            set_turn_injected_reflections(None)
        args, kwargs = self.agent._save_to_session.call_args
        assistant_meta = args[4] if len(args) > 4 else kwargs.get("assistant_metadata")
        self.assertEqual(assistant_meta.get("injected_reflections"), ["r1", "r2"])


class FeedbackConsumptionTest(unittest.TestCase):
    """P0b：/chat/feedback 消费 injected_reflections（helper 级契约）"""

    def setUp(self):
        self._tmp = []
        self.glog = _make_glog(self._tmp)
        self.agent = MagicMock()
        self.agent.growth_log_manager = self.glog

    def tearDown(self):
        shutil.rmtree(self._tmp[0], ignore_errors=True)

    def _round_repo(self, trace):
        repo = MagicMock()
        repo.get_round.return_value = {
            "assistant": {"content": "a", "metadata": {"injected_reflections": trace} if trace else {}}
        }
        return repo

    def test_like_validates_injected(self):
        from neurova.api.endpoints.console import _apply_feedback_to_reflections

        e1 = asyncio.run(self.glog.generate_log(type=ReflectionType.ERROR, title="t", content="c", confidence=0.5))
        e2 = asyncio.run(self.glog.generate_log(type=ReflectionType.ERROR, title="t2", content="c2", confidence=0.5))
        n = asyncio.run(_apply_feedback_to_reflections(self.agent, self._round_repo([e1.id, e2.id]), "s", "ts", "like"))
        self.assertEqual(n, 2)
        self.assertEqual(self.glog._cache[e1.id].status, ReflectionLogStatus.VALIDATED)
        self.assertEqual(self.glog._cache[e2.id].status, ReflectionLogStatus.VALIDATED)

    def test_dislike_demotes_injected(self):
        from neurova.api.endpoints.console import _apply_feedback_to_reflections

        e = asyncio.run(self.glog.generate_log(type=ReflectionType.ERROR, title="t", content="c", confidence=0.5))
        n = asyncio.run(_apply_feedback_to_reflections(self.agent, self._round_repo([e.id]), "s", "ts", "dislike"))
        self.assertEqual(n, 1)
        self.assertAlmostEqual(self.glog._cache[e.id].confidence, 0.35, places=5)

    def test_no_trace_zero_consumption(self):
        from neurova.api.endpoints.console import _apply_feedback_to_reflections

        n = asyncio.run(_apply_feedback_to_reflections(self.agent, self._round_repo(None), "s", "ts", "like"))
        self.assertEqual(n, 0)


class BuildContextInjectionTest(unittest.TestCase):
    """P3 最终验收：真 build_context 链路——反思经无损池归档，不再走
    截断 system 行（旧实现 f"[反思] {lesson[:400]+…}" 截断+双注）"""

    def setUp(self):
        self._tmp = []
        glog = _make_glog(self._tmp)
        self.entries = [
            asyncio.run(glog.generate_log(type=ReflectionType.ERROR, title="t", content="教训正文", insights=["先复述确认关注点再作答"], confidence=0.7)),
            asyncio.run(glog.generate_log(type=ReflectionType.PERFORMANCE, title="t2", content="正文乙", confidence=0.4)),
        ]
        self.glog = glog

        agent = MagicMock()
        agent.config.name = "A"
        agent.config.agent_id = "a"
        agent.growth_log_manager = glog
        agent._frozen_identity_snapshot = None
        agent.soul = "s"
        agent.personality = ""
        agent.config.constitution = ""
        agent.conversation_history = []
        agent.use_pool = True
        from neurova.context.orchestrator import ContextOrchestrator

        self.orchestrator = ContextOrchestrator(agent)
        # spy 替换真实池：断言归档行为，避开 embedding/draw 重依赖
        self.orchestrator.context_pool = MagicMock()
        self.orchestrator.context_pool.draw.return_value = []

    def tearDown(self):
        shutil.rmtree(self._tmp[0], ignore_errors=True)

    def test_full_chain(self):
        from neurova.context.pool_models import ContextSource
        from neurova.core.turn_context import get_turn_injected_reflections

        # 断言须在 build_context 同一协程内取痕迹：asyncio.run 子 task 的
        # contextvar set 不回传外层（生产链同 task 无此问题）
        async def scenario():
            msgs = await self.orchestrator.build_context("测试输入")
            return msgs, get_turn_injected_reflections()

        msgs, trace = asyncio.run(scenario())
        self.context_msgs = msgs

        contents, sources = [], []
        for c in self.orchestrator.context_pool.add_context.call_args_list:
            ci = c.args[0] if c.args else c.kwargs.get("need")
            contents.append(getattr(ci, "content", ""))
            sources.append(getattr(ci, "source", None))
        reflections = [c for s, c in zip(sources, contents) if s == ContextSource.REFLECTION]
        self.assertTrue(reflections, "反思应经池无损归档")
        for text in reflections:
            self.assertNotIn("…", text, "归档正文不得被截断")
        rendered = [m for m in self.context_msgs if str(m.get("content", "")).startswith("[反思]")]
        self.assertEqual(rendered, [], "反思不再作为截断 system 行直注")
        # P0a：痕迹 = 选中注入的 id（scenario 协程内已取）；pending→applied
        self.assertEqual(sorted(trace), sorted(e.id for e in self.entries))
        self.assertEqual(
            {self.glog._cache[e.id].status for e in self.entries},
            {ReflectionLogStatus.APPLIED},
        )


if __name__ == "__main__":
    unittest.main()
