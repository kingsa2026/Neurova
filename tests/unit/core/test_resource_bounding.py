"""资源消耗项防回归测试（第二轮 P1/P2 修复，2026-09-01）

覆盖（每项对应一个此前实测/代码核实的无界增长点）:
1. trace_recorder: end_trace 后活动注册表清空; _saved_traces 上限 100
2. tool_coordinator: 后台任务完成后移入有界留存, 活动字典不堆积
3. event_bus: 同 handler 重复订阅去重; 异步队列有界(满时丢弃计数)
4. unified_vector_store: 增量索引只对新文档做 IDF(消除每轮召回全库分词)
5. metrics collector: 时间序列键数量上限
6. tool_execution_manager: 终态上下文硬上限淘汰
"""
import asyncio
import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))


class TestTraceRecorderCleanup(unittest.TestCase):
    """P1-1: end_trace 清理注册表 + _saved_traces 上限"""

    def test_end_trace_clears_active_registry(self):
        from neurova.core.trace_recorder import TrajectoryRecorder

        rec = TrajectoryRecorder()
        rec._storage_dir = Path(tempfile.mkdtemp())
        rec._auto_save = False
        tid = rec.start_trace("sess-1", "agent-1", "user-1")
        self.assertIn(tid, rec._active_traces)
        self.assertTrue(rec._active_spans)
        self.assertIn("user-1", rec._active_traces_by_user)

        rec.end_trace(tid)
        self.assertEqual(len(rec._active_traces), 0, "end_trace 后活动轨迹必须清空")
        self.assertEqual(len(rec._active_spans), 0, "end_trace 后活动 span 必须清空")
        self.assertNotIn("user-1", rec._active_traces_by_user)

    def test_saved_traces_capped(self):
        from neurova.core.trace_recorder import TrajectoryRecorder

        rec = TrajectoryRecorder()
        rec._storage_dir = Path(tempfile.mkdtemp())
        rec._auto_save = True
        for i in range(105):
            tid = rec.start_trace(f"sess-{i}", "agent-1", "user-1")
            rec.end_trace(tid)
        self.assertLessEqual(
            len(rec._saved_traces),
            rec._max_traces_in_memory,
            "_saved_traces 超上限必须截断",
        )


class TestToolCoordinatorBounded(unittest.TestCase):
    """P1-3: 后台任务观察完成后移入有界留存"""

    def test_observe_moves_to_completed(self):
        from neurova.agent.tool_coordinator import ToolCoordinator

        async def _run():
            c = ToolCoordinator()
            c._background["bg_1"] = {
                "task": None, "tool_name": "web_search",
                "result": None, "error": None, "success": None,
            }
            task = asyncio.ensure_future(_succeed())
            await c._observe_background("web_search", "bg_1", task)
            return c

        c = asyncio.run(_run())
        self.assertNotIn("bg_1", c._background, "完成的任务必须从活动字典移除")
        self.assertIn("bg_1", c._completed, "完成的任务移入有界留存")
        self.assertTrue(c.get_background_status("bg_1")["success"])

    def test_completed_bounded(self):
        from neurova.agent.tool_coordinator import ToolCoordinator

        async def _run():
            c = ToolCoordinator()
            c._MAX_COMPLETED = 2
            for i in range(4):
                c._background[f"bg_{i}"] = {
                    "task": None, "tool_name": "t",
                    "result": None, "error": None, "success": None,
                }
                task = asyncio.ensure_future(_succeed())
                await c._observe_background("t", f"bg_{i}", task)
            return c

        c = asyncio.run(_run())
        self.assertLessEqual(len(c._completed), 2, "留存超上限必须淘汰最老")
        self.assertIsNone(c.get_background_status("bg_0"), "最老条目应被淘汰")


async def _succeed():
    return {"ok": True}


class TestEventBusBounded(unittest.TestCase):
    """P1-4: 订阅去重 + 异步队列有界"""

    def test_subscribe_dedup(self):
        from neurova.core.event_bus import EventBus

        bus = EventBus()
        handler = lambda event: None  # noqa: E731
        bus.subscribe("evt", handler, module_name="m")
        bus.subscribe("evt", handler, module_name="m")
        self.assertEqual(len(bus._subscribers["evt"]), 1, "同 handler 重复订阅必须去重")

    def test_async_queue_bounded(self):
        from neurova.core.event_bus import EventBus

        async def _run():
            bus = EventBus()
            bus._async_queue_max = 5

            async def slow_handler(event):
                await asyncio.sleep(2)

            bus.subscribe("evt", slow_handler, module_name="m")
            bus.start()  # 在运行中的 loop 内启动, 队列即创建
            for i in range(12):
                bus.publish("evt", {"i": i}, "test")
            size = bus._async_queue.qsize()
            dropped = bus._async_queue_full_dropped
            bus._async_task.cancel()
            try:
                await bus._async_task
            except asyncio.CancelledError:
                pass
            return size, dropped

        size, dropped = asyncio.run(_run())
        self.assertLessEqual(size, 5, "异步队列不得超过 maxsize")
        self.assertGreaterEqual(dropped, 5, "超限事件应被丢弃并计数")


class TestVectorStoreIncrementalIdf(unittest.TestCase):
    """P1-5: 增量索引只对新文档更新 IDF"""

    def test_incremental_skips_existing_idf(self):
        from neurova.cognitive_layers.memory_layer.unified_vector_store import (
            UnifiedVectorStore,
        )

        store = UnifiedVectorStore(backend="tfidf")
        docs = [
            {"id": f"m{i}", "content": f"这是第 {i} 条测试记忆内容，用于验证"}
            for i in range(20)
        ]
        with mock.patch.object(store, "_update_idf", wraps=store._update_idf) as spy:
            store.index_memories(docs, incremental=False)
            self.assertEqual(spy.call_count, 1)
            vocab_before = dict(store._tfidf_vocabulary)

            # 同一批再增量索引(模拟每轮召回传入全量) → 不应重新分词
            store.index_memories(docs, incremental=True)
            self.assertEqual(spy.call_count, 1, "已存在文档不应触发 IDF 重建")
            self.assertEqual(store._tfidf_vocabulary, vocab_before)

            # 新文档增量 → 才触发一次
            new_docs = [{"id": "new1", "content": "这是一条全新的记忆内容"}]
            store.index_memories(new_docs, incremental=True)
            self.assertEqual(spy.call_count, 2, "新文档应触发一次 IDF 更新")


class TestMetricsCollectorCaps(unittest.TestCase):
    """P1-8: 时间序列键数量上限"""

    def test_series_keys_bounded(self):
        from neurova.analytics.collector import MetricsCollector

        col = MetricsCollector()
        col._MAX_SERIES = 10
        for i in range(15):
            col._add_time_series_point(f"metric.key.{i}", 1.0)
        self.assertLessEqual(len(col._time_series), 10, "序列键数量必须被限制")


class TestToolExecutionManagerEviction(unittest.TestCase):
    """P1-2: 终态上下文硬上限淘汰"""

    def _make_context(self, cid, status, age_sec):
        from neurova.agent.tool_execution_manager import (
            ToolExecutionManager,
            ExecutionStatus,
        )
        from neurova.tool_layers.types import ToolExecutionContext

        ctx = ToolExecutionContext(
            context_id=cid,
            tool_name="t",
            params={},
            user_input="",
            status=status,
            completed_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=age_sec),
        )
        return ctx, ExecutionStatus

    def test_evict_over_capacity(self):
        from neurova.agent.tool_execution_manager import ToolExecutionManager

        mgr = ToolExecutionManager()
        mgr._MAX_CONTEXTS = 5
        ExecutionStatus = None  # noqa: F841
        from neurova.agent.tool_execution_manager import ExecutionStatus as ES

        for i in range(12):
            ctx, _ = self._make_context(f"ctx_{i}", ES.COMPLETED, age_sec=1000 + i)
            mgr._contexts[ctx.context_id] = ctx

        mgr._evict_over_capacity()
        self.assertLessEqual(len(mgr._contexts), mgr._MAX_CONTEXTS, "超出上限必须淘汰最老")
        self.assertNotIn("ctx_0", mgr._contexts, "最老上下文应被淘汰")


if __name__ == "__main__":
    unittest.main()
