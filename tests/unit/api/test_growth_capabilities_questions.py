"""成长页能力数据与问题队列状态契约（2026-09-15 反思/成长链路排查修复）

根因（排查见 docs 台账 / memory neurova-reflection-growth-trigger-audit-2026-09-15）:
1. GrowthAnalyzer 每轮写 growth.json，但 neurova/api 全层零端点消费 → 能力成长
   数据是信息孤岛，前端成长页永远看不到（"成长一直没有数据"的结构性根因）。
2. GET /growth/questions 只返回 pending+cooldown；主动提问闭环运行后状态即
   ASKED 终态 → 队列页面恒空（生产库 22 条全 asked）。
3. 条目字段缺 id/answered/created_at，前端 GrowthQuestion 契约对不上；
   overview 端点同样只取 pending。
"""

import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.cognitive_layers.growth_layer.analyzer import (
    GrowthAnalyzer,
    GrowthDimension,
)
from neurova.cognitive_layers.meta_cognition_layer.question_queue import (
    QuestionQueueManager,
)


def _agent_stub(tmpdir, with_analyzer=True):
    analyzer = None
    if with_analyzer:
        analyzer = GrowthAnalyzer(agent_id="test_agent", workspace_path=os.path.join(tmpdir, "growth"))
        analyzer.record_learning(
            dimension=GrowthDimension.LEARNING, score=42.0, task_type="conversation", description="契约测试"
        )
    qqm = QuestionQueueManager(memory_manager=None, default_cooldown=300.0)
    return types.SimpleNamespace(growth_analyzer=analyzer, question_queue_manager=qqm), analyzer, qqm


class GrowthCapabilitiesEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.agent, self.analyzer, self.qqm = _agent_stub(self.tmpdir)

        from neurova.api.endpoints import growth as growth_api

        self.growth_api = growth_api
        app = FastAPI()
        app.include_router(growth_api.router, prefix="/api/v1/growth")
        from neurova.api.auth import get_current_user as _gcu

        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser",
            "username": "tuser",
            "role": "admin",
            "neuser_id": "tuser",
        }
        self.client = TestClient(app)
        self._patcher = patch.object(growth_api, "_get_agent", return_value=self.agent)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_capabilities_returns_real_analyzer_data(self):
        """成长页必须能读到 GrowthAnalyzer 的真实能力分数（修复前端点 404）"""
        resp = self.client.get("/api/v1/growth/capabilities", params={"agent_id": "test_agent"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIsNotNone(data)
        self.assertIn("learning", data["dimension_statuses"])
        self.assertGreater(data["dimension_statuses"]["learning"]["score"], 0)
        self.assertGreaterEqual(data["total_records"], 1)

    def test_capabilities_honest_without_analyzer(self):
        """analyzer 未装配时 data 必须为 null，不得造默认分数"""
        self.agent.growth_analyzer = None
        resp = self.client.get("/api/v1/growth/capabilities", params={"agent_id": "test_agent"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["data"])

    def test_overview_carries_capabilities(self):
        resp = self.client.get("/api/v1/growth", params={"agent_id": "test_agent"})
        data = resp.json()["data"]
        self.assertIsNotNone(data.get("capabilities"))
        self.assertGreater(data["capabilities"]["dimension_statuses"]["learning"]["score"], 0)


class GrowthQuestionsStatusContractTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.agent, self.analyzer, self.qqm = _agent_stub(self.tmpdir, with_analyzer=False)

        from neurova.api.endpoints import growth as growth_api

        app = FastAPI()
        app.include_router(growth_api.router, prefix="/api/v1/growth")
        from neurova.api.auth import get_current_user as _gcu

        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser",
            "username": "tuser",
            "role": "admin",
            "neuser_id": "tuser",
        }
        self.client = TestClient(app)
        self._patcher = patch.object(growth_api, "_get_agent", return_value=self.agent)
        self._patcher.start()

        # 预置三种状态各一条：pending（新入队）/ asked（已提问）/ answered（已回答）
        self.q_pending = self.qqm.generate_question(content="待处理问题?")
        self.q_asked = self.qqm.generate_question(content="已提问问题?")
        self.q_answered = self.qqm.generate_question(content="已回答问题?")
        self.assertTrue(self.qqm.mark_asked(self.q_asked.id))
        self.assertTrue(self.qqm.mark_answered(self.q_answered.id, "答案X"))

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_includes_asked_entries(self):
        """生产闭环下问题终态是 asked——列表必须可见（修复前只返回 pending+cooldown 恒空）"""
        resp = self.client.get("/api/v1/growth/questions", params={"agent_id": "test_agent"})
        self.assertEqual(resp.status_code, 200)
        questions = resp.json()
        ids = {q["question_id"] for q in questions}
        self.assertIn(self.q_asked.id, ids, "asked 态问题必须返回")
        self.assertIn(self.q_pending.id, ids)
        self.assertIn(self.q_answered.id, ids)

    def test_items_carry_frontend_contract_fields(self):
        resp = self.client.get("/api/v1/growth/questions", params={"agent_id": "test_agent"})
        item = resp.json()[0]
        for key in ("id", "question_id", "question", "status", "answered", "answer", "created_at", "priority"):
            self.assertIn(key, item, f"前端 GrowthQuestion 契约缺字段 {key}")
        self.assertEqual(item["id"], item["question_id"])

    def test_answered_filter(self):
        resp = self.client.get("/api/v1/growth/questions", params={"agent_id": "test_agent", "answered": True})
        answered = resp.json()
        self.assertTrue(all(q["answered"] for q in answered))
        self.assertEqual({q["question_id"] for q in answered}, {self.q_answered.id})

        resp2 = self.client.get("/api/v1/growth/questions", params={"agent_id": "test_agent", "answered": False})
        unanswered = {q["question_id"] for q in resp2.json()}
        self.assertEqual(unanswered, {self.q_pending.id, self.q_asked.id})

    def test_overview_questions_visible_when_all_asked(self):
        """overview 同步契约：全 asked 时成长页问题区不得为空（原只取 pending）"""
        self.q_pending.status = type(self.q_pending.status).ASKED
        resp = self.client.get("/api/v1/growth", params={"agent_id": "test_agent"})
        data = resp.json()["data"]
        ids = {q["question_id"] for q in data["questions"]}
        self.assertIn(self.q_asked.id, ids)


if __name__ == "__main__":
    unittest.main()
