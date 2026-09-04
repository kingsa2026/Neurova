"""V3 元认知端到端闭环集成测试

一条测试贯通全部环节（不 mock 任何被测组件）：
  工具事件(tool_executor 同口径写入) → MetaLedger
  → SelfModelEngine.reflect 五算子 → 结构化教训落台账
  → check_tool_advisory 调控门数据源（含过期语义）
  → injector 教训注入系统提示（行为改变通道）
  → API 六端点契约（TestClient，前端消费 shape）
"""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    get_self_model_engine,
    reset_self_model_engine,
)

AGENT = "e2e_agent"


class V3ClosedLoopTest(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        self.engine = get_self_model_engine(AGENT)
        self.ledger = get_meta_ledger(AGENT)

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def _feed_degraded_tool(self, tool="web_search"):
        """模拟 tool_executor.on_tool_executed 的同口径写入（含上下文签名）。"""
        for _ in range(45):
            self.engine.record_tool_event(tool, True, duration_ms=500.0, source="builtin", context={"has_code_block": False})
        for _ in range(10):
            self.engine.record_tool_event(tool, False, duration_ms=2000.0, source="builtin", context={"has_code_block": True})

    def _make_client(self):
        from neurova.api.endpoints import metacognition_api

        app = FastAPI()
        app.include_router(metacognition_api.router, prefix="/api/v1/metacognition")
        return TestClient(app)

    def test_full_loop_event_to_lesson_to_gate_to_injection_to_api(self):
        # 1. 工具事件入台账
        self._feed_degraded_tool()
        rates = self.ledger.tool_success_rates(AGENT, min_calls=1)
        self.assertIn("web_search", rates)

        # 2. 洞察编译 → 教训 + 反思报告落台账
        report = self.engine.reflect(trigger="e2e")
        self.assertTrue(report["lessons"])
        lesson = next(l for l in report["lessons"] if l["subject"] == "web_search")
        self.assertEqual(lesson["recommendation"], "avoid_tool")
        self.assertEqual(lesson["source"], "template")

        # 3. 调控门数据源：活跃教训可查询（tool_executor 消费同一入口）
        advisory = self.engine.check_tool_advisory("web_search")
        self.assertIsNotNone(advisory)
        self.assertEqual(advisory["recommendation"], "avoid_tool")
        self.assertIsNone(self.engine.check_tool_advisory("healthy_tool"))

        # 4. 教训注入系统提示（injector 行为改变通道）
        from neurova.context.injector import UnifiedContextInjector
        from types import SimpleNamespace

        injector = UnifiedContextInjector(
            memory_manager=SimpleNamespace(), enable_cache=False, metacog_agent_id=AGENT
        )
        injected = injector._build_metacog_lessons(AGENT)
        self.assertIn("web_search", injected)

        # 5. API 全契约（前端消费 shape）
        client = self._make_client()
        base = f"/api/v1/metacognition/{AGENT}/metacognition"

        state = client.get(f"{base}/state").json()["data"]
        # 本测试无管线负荷写入 → state 端点兜底 shape 仍须可消费
        self.assertIn("load_score", state)

        lessons = client.get(f"{base}/lessons").json()["data"]["items"]
        self.assertTrue(any(l["subject"] == "web_search" for l in lessons))

        history = client.get(f"{base}/history").json()["data"]["items"]
        self.assertEqual(history[0]["trigger"], "e2e")

        stats = client.get(f"{base}/stats").json()["data"]
        self.assertEqual(stats["total_entries"], 0)  # 洞察/反思不计入条目统计

        created = client.post(
            base, json={"type": "strategy", "content": "改用 browser_read", "confidence": 0.7}
        ).json()["data"]
        self.assertEqual(created["type"], "strategy")
        stats2 = client.get(f"{base}/stats").json()["data"]
        self.assertEqual(stats2["total_entries"], 1)
        self.assertAlmostEqual(stats2["avg_confidence"], 0.7)

        # 6. 手动反思端点复用同一引擎
        reflect_res = client.post(f"{base}/reflect").json()["data"]
        self.assertIn("lessons", reflect_res)

    def test_loop_survives_ledger_singleton_reset(self):
        """台账单例重建（模拟后端重启）后，教训与调控建议仍在（SQLite 落底）。"""
        self._feed_degraded_tool()
        self.engine.reflect(trigger="e2e")
        from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger as _r

        _r()
        engine2 = get_self_model_engine(AGENT)
        self.assertIsNotNone(engine2.check_tool_advisory("web_search"))


if __name__ == "__main__":
    unittest.main()
