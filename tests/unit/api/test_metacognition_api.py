"""元认知 API 契约测试（V3 — 前后端契约逐字对齐）

锁定 MetacognitionPage 实际消费的字段：
- entries: {id,type,content,context,confidence,created_at}
- stats:   {total_entries, by_type:[{type,count}], avg_confidence, recent_trend}
- state:   认知负荷真状态（B 写穿透）
- history: 反思时间线 {created_at,confidence,trigger,summary}
- reflect: 手动触发真反思（洞察编译器，零 LLM）
- memory 包僵尸路由（原读不存在的 agent.metacog_manager）→ 同源台账数据
"""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    reset_self_model_engine,
)

AGENT = "api_agent"


class MetacognitionApiTest(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        from neurova.api.endpoints import metacognition_api
        from neurova.api.endpoints.memory import metacognition as memory_metacog

        app = FastAPI()
        app.include_router(metacognition_api.router, prefix="/api/v1/metacognition")
        self.client = TestClient(app)

        app_mem = FastAPI()
        app_mem.include_router(memory_metacog.router, prefix="/api/v1/memory")
        self.mem_client = TestClient(app_mem)

        ledger = get_meta_ledger(AGENT)
        ledger.create_record(
            agent_id=AGENT, kind="thought", type="self_assessment",
            content="评估：本轮检索策略有效", context="聊天", confidence=0.8,
        )
        ledger.write_state(
            agent_id=AGENT, load_level="moderate", load_score=0.5,
            active_tasks=5, memory_usage=0.5, response_time_ms=2500.0, error_rate=0.1,
            metadata={"factors": {"tasks": 0.5, "memory": 0.5, "response": 0.5, "error": 0.1}},
        )

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_list_entries_contract(self):
        res = self.client.get(f"/api/v1/metacognition/{AGENT}/metacognition")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        for key in ("id", "type", "content", "context", "confidence", "created_at"):
            self.assertIn(key, item)
        self.assertEqual(item["type"], "self_assessment")

    def test_create_and_list_roundtrip(self):
        res = self.client.post(
            f"/api/v1/metacognition/{AGENT}/metacognition",
            json={"type": "strategy", "content": "改用分块检索", "context": "测试", "confidence": 0.7},
        )
        self.assertEqual(res.status_code, 200)
        res = self.client.get(f"/api/v1/metacognition/{AGENT}/metacognition")
        items = res.json()["data"]["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(any(i["type"] == "strategy" for i in items))

    def test_stats_contract(self):
        res = self.client.get(f"/api/v1/metacognition/{AGENT}/metacognition/stats")
        self.assertEqual(res.status_code, 200)
        stats = res.json()["data"]
        for key in ("total_entries", "by_type", "avg_confidence", "recent_trend"):
            self.assertIn(key, stats)
        self.assertEqual(stats["total_entries"], 1)

    def test_state_endpoint_returns_real_load(self):
        """指标卡数据源：B 写穿透的负荷快照 + 四因子。"""
        res = self.client.get(f"/api/v1/metacognition/{AGENT}/metacognition/state")
        self.assertEqual(res.status_code, 200)
        state = res.json()["data"]
        for key in ("load_level", "load_score", "active_tasks", "response_time_ms", "error_rate"):
            self.assertIn(key, state)
        self.assertEqual(state["active_tasks"], 5)
        self.assertIn("factors", state)

    def test_reflect_endpoint_returns_report(self):
        """手动触发真反思：结构化教训报告（零 LLM）。"""
        ledger = get_meta_ledger(AGENT)
        for _ in range(45):
            ledger.write_event(agent_id=AGENT, process_type="tool", description="bad_tool", success=True)
        for _ in range(10):
            ledger.write_event(agent_id=AGENT, process_type="tool", description="bad_tool", success=False)
        res = self.client.post(f"/api/v1/metacognition/{AGENT}/metacognition/reflect")
        self.assertEqual(res.status_code, 200)
        report = res.json()["data"]
        self.assertIn("lessons", report)
        self.assertTrue(any(l["subject"] == "bad_tool" for l in report["lessons"]))

    def test_lessons_endpoint_returns_structured_lessons(self):
        """洞察列表：kind=lesson 记录的 metadata（含 operator/recommendation）。"""
        ledger = get_meta_ledger(AGENT)
        for _ in range(45):
            ledger.write_event(agent_id=AGENT, process_type="tool", description="bad_tool", success=True)
        for _ in range(10):
            ledger.write_event(agent_id=AGENT, process_type="tool", description="bad_tool", success=False)
        from neurova.cognitive_layers.meta_cognition_layer.self_model import get_self_model_engine

        get_self_model_engine(AGENT).reflect(trigger="test")
        res = self.client.get(f"/api/v1/metacognition/{AGENT}/metacognition/lessons")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertGreaterEqual(data["total"], 1)
        self.assertIn("operator", data["items"][0])
        self.assertEqual(data["items"][0]["source"], "template")

    def test_history_after_reflect(self):
        ledger = get_meta_ledger(AGENT)
        from neurova.cognitive_layers.meta_cognition_layer.self_model import get_self_model_engine

        get_self_model_engine(AGENT).reflect(trigger="manual_test")
        res = self.client.get(f"/api/v1/metacognition/{AGENT}/metacognition/history")
        self.assertEqual(res.status_code, 200)
        items = res.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["trigger"], "manual_test")
        for key in ("created_at", "confidence", "trigger", "summary"):
            self.assertIn(key, items[0])

    def test_memory_zombie_routes_now_read_ledger(self):
        """原读 agent.metacog_manager（全仓无此属性，恒空）→ 改同源台账。"""
        res = self.mem_client.get(f"/api/v1/memory/{AGENT}/metacognition")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["type"], "self_assessment")

        res = self.mem_client.get(f"/api/v1/memory/{AGENT}/metacognition/stats")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
