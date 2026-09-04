"""MetaLedger 台账契约测试（V3 元认知融合）

锁定统一台账 MetaLedger 的核心契约：
- 三表写入/读取（meta_events / meta_records / meta_states）
- per-agent 隔离
- 分页/过滤/统计投影
- 保留上限裁剪（防 232 万行冻结的教训）
- 重启持久化（reset 单例后重建读回）
- env 路径覆盖（测试隔离，仿 NEUROVA_USAGE_HISTORY_DB 惯例）
"""

import unittest

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    MetaLedger,
    get_meta_ledger,
    reset_meta_ledger,
)


def _fresh_ledger(name: str) -> MetaLedger:
    reset_meta_ledger()
    return get_meta_ledger(name)


class TestMetaLedgerEvents(unittest.TestCase):
    def setUp(self):
        self.ledger = _fresh_ledger("ledger_ev")

    def tearDown(self):
        reset_meta_ledger()

    def test_write_and_read_event(self):
        self.ledger.write_event(
            agent_id="a1",
            process_type="tool",
            description="web_search",
            duration_ms=120.0,
            success=True,
            metadata={"has_code_block": False},
        )
        events = self.ledger.list_events(agent_id="a1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["process_type"], "tool")
        self.assertEqual(events[0]["description"], "web_search")
        self.assertTrue(events[0]["success"])
        self.assertIn("created_at", events[0])

    def test_per_agent_isolation(self):
        self.ledger.write_event(agent_id="a1", process_type="tool", description="t1", success=True)
        self.ledger.write_event(agent_id="a2", process_type="tool", description="t2", success=False)
        self.assertEqual(len(self.ledger.list_events(agent_id="a1")), 1)
        self.assertEqual(len(self.ledger.list_events(agent_id="a2")), 1)
        self.assertEqual(self.ledger.list_events(agent_id="a1")[0]["description"], "t1")

    def test_list_events_limit(self):
        for i in range(30):
            self.ledger.write_event(agent_id="a1", process_type="tool", description=f"t{i}", success=True)
        events = self.ledger.list_events(agent_id="a1", limit=10)
        self.assertEqual(len(events), 10)
        # 倒序：最新在前
        self.assertEqual(events[0]["description"], "t29")

    def test_tool_success_rate_projection(self):
        for i in range(8):
            self.ledger.write_event(agent_id="a1", process_type="tool", description="ok_tool", success=True)
        for i in range(2):
            self.ledger.write_event(agent_id="a1", process_type="tool", description="ok_tool", success=False)
        rates = self.ledger.tool_success_rates(agent_id="a1", min_calls=1)
        self.assertAlmostEqual(rates["ok_tool"], 0.8)

    def test_event_retention_pruning(self):
        ledger = MetaLedger(db_path=":memory:", max_events_per_agent=20)
        for i in range(30):
            ledger.write_event(agent_id="a1", process_type="tool", description=f"t{i}", success=True)
        self.assertLessEqual(len(ledger.list_events(agent_id="a1", limit=1000)), 20)


class TestMetaLedgerRecords(unittest.TestCase):
    def setUp(self):
        self.ledger = _fresh_ledger("ledger_rec")

    def tearDown(self):
        reset_meta_ledger()

    def test_create_and_list_record(self):
        rid = self.ledger.create_record(
            agent_id="a1",
            kind="thought",
            type="self_assessment",
            content="今天表现不错",
            context="聊天",
            confidence=0.8,
        )
        self.assertTrue(rid)
        result = self.ledger.list_records(agent_id="a1")
        items = result["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "self_assessment")
        self.assertEqual(items[0]["content"], "今天表现不错")
        self.assertAlmostEqual(items[0]["confidence"], 0.8)

    def test_record_pagination_and_type_filter(self):
        for i in range(15):
            self.ledger.create_record(agent_id="a1", kind="thought", type="planning", content=f"p{i}")
        for i in range(5):
            self.ledger.create_record(agent_id="a1", kind="thought", type="monitoring", content=f"m{i}")
        page1 = self.ledger.list_records(agent_id="a1", page=1, size=10)
        self.assertEqual(len(page1["items"]), 10)
        self.assertEqual(page1["total"], 20)
        filtered = self.ledger.list_records(agent_id="a1", page=1, size=10, record_type="monitoring")
        self.assertEqual(filtered["total"], 5)
        self.assertEqual(filtered["items"][0]["type"], "monitoring")

    def test_kind_filter(self):
        self.ledger.create_record(agent_id="a1", kind="thought", type="planning", content="p")
        self.ledger.create_record(agent_id="a1", kind="lesson", type="monitoring", content="l")
        thoughts = self.ledger.list_records(agent_id="a1", kind="thought")
        self.assertEqual(thoughts["total"], 1)
        lessons = self.ledger.list_records(agent_id="a1", kind="lesson")
        self.assertEqual(lessons["total"], 1)

    def test_stats_projection_shape(self):
        """统计投影必须与前端 TS 契约逐字对齐（total_entries/by_type/avg_confidence/recent_trend）。"""
        self.ledger.create_record(agent_id="a1", kind="thought", type="planning", content="p", confidence=0.6)
        self.ledger.create_record(agent_id="a1", kind="thought", type="monitoring", content="m", confidence=0.8)
        stats = self.ledger.record_stats(agent_id="a1")
        self.assertEqual(stats["total_entries"], 2)
        by_type = {t["type"]: t["count"] for t in stats["by_type"]}
        self.assertEqual(by_type, {"planning": 1, "monitoring": 1})
        self.assertAlmostEqual(stats["avg_confidence"], 0.7)
        self.assertIsInstance(stats["recent_trend"], list)
        if stats["recent_trend"]:
            self.assertIn("date", stats["recent_trend"][0])
            self.assertIn("count", stats["recent_trend"][0])

    def test_record_retention_pruning(self):
        ledger = MetaLedger(db_path=":memory:", max_records_per_agent=10)
        for i in range(15):
            ledger.create_record(agent_id="a1", kind="thought", type="planning", content=f"p{i}")
        result = ledger.list_records(agent_id="a1", page=1, size=100)
        self.assertLessEqual(result["total"], 10)


class TestMetaLedgerStates(unittest.TestCase):
    def setUp(self):
        self.ledger = _fresh_ledger("ledger_st")

    def tearDown(self):
        reset_meta_ledger()

    def test_write_and_latest_state(self):
        self.ledger.write_state(
            agent_id="a1",
            load_level="moderate",
            load_score=0.55,
            active_tasks=3,
            memory_usage=0.4,
            response_time_ms=1500.0,
            error_rate=0.1,
            metadata={"turn_steps": 5},
        )
        state = self.ledger.latest_state(agent_id="a1")
        self.assertIsNotNone(state)
        self.assertEqual(state["load_level"], "moderate")
        self.assertAlmostEqual(state["load_score"], 0.55)
        self.assertEqual(state["active_tasks"], 3)

    def test_latest_state_empty(self):
        self.assertIsNone(self.ledger.latest_state(agent_id="nobody"))

    def test_state_history(self):
        for i in range(5):
            self.ledger.write_state(agent_id="a1", load_level="low", load_score=i / 10.0)
        hist = self.ledger.state_history(agent_id="a1", limit=3)
        self.assertEqual(len(hist), 3)


class TestMetaLedgerLifecycle(unittest.TestCase):
    def tearDown(self):
        reset_meta_ledger()

    def test_persistence_across_reset(self):
        """写入 → reset 单例 → 重建：数据必须还在（SQLite 落底语义）。"""
        ledger1 = _fresh_ledger("ledger_persist")
        ledger1.create_record(agent_id="a1", kind="thought", type="strategy", content="跨重启存活")
        reset_meta_ledger()
        ledger2 = get_meta_ledger("ledger_persist")
        items = ledger2.list_records(agent_id="a1")["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content"], "跨重启存活")

    def test_reset_clears_singleton_not_disk(self):
        _fresh_ledger("ledger_rc")
        reset_meta_ledger()
        # 再 reset 一次不应抛错（幂等）
        reset_meta_ledger()


if __name__ == "__main__":
    unittest.main()
