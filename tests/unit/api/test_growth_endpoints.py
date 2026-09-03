"""成长端点真实数据契约测试（P0-A）

覆盖 api/endpoints/growth.py 与 api/endpoints/context.py 的断链:
- growth.py 调用 GrowthLogManager 上不存在的 get_recent_logs/add_log/get_stats
  （真实方法: read_logs/generate_log/get_statistics）→ 反思数据永远为空或假数据
- growth.py 问题路由调用不存在的 get_questions/add_question/mark_answered
- context.py GET /inject/reflection 因 hasattr 守卫永远返回空列表
- 有真实管理器时端点不得返回 mock 假数据
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionType,
)
from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionQueueManager


def _make_manager(tmpdir):
    mm = MemoryManager(
        db_path=os.path.join(tmpdir, "growth_endpoints.db"),
        agent_id="test_agent",
        user_id="test_user",
    )
    glm = GrowthLogManager(memory_manager=mm)
    qqm = QuestionQueueManager(memory_manager=mm, default_cooldown=300.0)
    return glm, qqm


class GrowthReflectionEndpointsTest(unittest.TestCase):
    def setUp(self):
        import types

        self.tmpdir = tempfile.mkdtemp()
        glm, qqm = _make_manager(self.tmpdir)
        self.glm = glm
        agent = types.SimpleNamespace(growth_log_manager=glm, question_queue_manager=qqm)

        from neurova.api.endpoints import growth as growth_api
        from neurova.api.endpoints import context as context_api

        self.growth_api = growth_api

        app = FastAPI()
        app.include_router(growth_api.router, prefix="/api/v1/growth")
        self.client = TestClient(app)
        self._patcher = patch.object(growth_api, "_get_agent", return_value=agent)
        self._patcher.start()

        # context 路由单独挂载
        app_ctx = FastAPI()
        app_ctx.include_router(context_api.router, prefix="/api/v1/context")
        self.ctx_client = TestClient(app_ctx)
        self._ctx_patcher = patch.object(context_api, "_get_agent", return_value=agent)
        self._ctx_patcher.start()

        # 预置一条真实反思日志
        asyncio.run(
            glm.generate_log(
                type=ReflectionType.ERROR,
                title="反思标题A",
                content="反思正文B",
                insights=["洞察C"],
                confidence=0.8,
            )
        )

    def tearDown(self):
        self._patcher.stop()
        self._ctx_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_reflection_logs_returns_real_data(self):
        resp = self.client.get("/api/v1/growth/reflection")
        self.assertEqual(resp.status_code, 200)
        logs = resp.json()
        self.assertEqual(len(logs), 1, "应返回真实的 1 条反思日志，而非 5 条 mock")
        self.assertEqual(logs[0]["content"], "反思正文B")
        self.assertEqual(logs[0]["log_id"], logs[0]["log_id"])
        self.assertNotIn("Reflection on conversation topic", logs[0]["content"])

    def test_get_reflection_logs_empty_without_mock(self):
        """无反思日志时返回空列表而非 mock 假数据"""
        glm2, _ = _make_manager(os.path.join(self.tmpdir, "empty"))
        import types

        agent = types.SimpleNamespace(growth_log_manager=glm2, question_queue_manager=None)
        with patch.object(self.growth_api, "_get_agent", return_value=agent):
            resp = self.client.get("/api/v1/growth/reflection")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_create_reflection_log_persists(self):
        resp = self.client.post(
            "/api/v1/growth/reflection",
            params={"agent_id": "test_agent"},
            json={"reflection_type": "improvement", "content": "新建反思X", "insights": ["洞察Y"], "confidence": 0.6},
        )
        self.assertEqual(resp.status_code, 200)
        created = resp.json()
        self.assertEqual(created["content"], "新建反思X")
        # 真实落库（read_logs 可读回）
        contents = [e.content for e in self.glm.read_logs(limit=10)]
        self.assertIn("新建反思X", contents)

    def test_reflection_stats_uses_real_statistics(self):
        resp = self.client.get("/api/v1/growth/reflection/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["total"], 1, "get_statistics 返回真实统计（total 键）")

    def test_context_inject_reflection_returns_real_logs(self):
        resp = self.ctx_client.get("/api/v1/context/inject/reflection")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["count"], 1, "inject/reflection 应返回真实反思日志（此前恒为空）")
        self.assertEqual(data["reflection_logs"][0]["content"], "反思正文B")


class GrowthQuestionEndpointsTest(unittest.TestCase):
    def setUp(self):
        import types

        self.tmpdir = tempfile.mkdtemp()
        glm, qqm = _make_manager(self.tmpdir)
        selfqqm = qqm
        self.qqm = qqm
        agent = types.SimpleNamespace(growth_log_manager=glm, question_queue_manager=qqm)

        from neurova.api.endpoints import growth as growth_api

        app = FastAPI()
        app.include_router(growth_api.router, prefix="/api/v1/growth")
        self.client = TestClient(app)
        self._patcher = patch.object(growth_api, "_get_agent", return_value=agent)
        self._patcher.start()
        self.growth_api = growth_api

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_list_questions_real(self):
        resp = self.client.post(
            "/api/v1/growth/questions",
            params={"agent_id": "test_agent"},
            json={"question_type": "curiosity", "question": "为什么天空是蓝色的?", "priority": 1},
        )
        self.assertEqual(resp.status_code, 200)

        resp2 = self.client.get("/api/v1/growth/questions")
        self.assertEqual(resp2.status_code, 200)
        questions = resp2.json()
        self.assertEqual(len(questions), 1, "应返回真实问题，而非 3 条 mock")
        self.assertEqual(questions[0]["question"], "为什么天空是蓝色的?")

    def test_questions_empty_without_mock(self):
        resp = self.client.get("/api/v1/growth/questions")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [], "管理器存在但无数据时应返回空列表")

    def test_next_question_returns_pending(self):
        self.qqm.generate_question("下一个问题?")
        resp = self.client.get("/api/v1/growth/questions/next")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIsNotNone(data)
        self.assertEqual(data["question"], "下一个问题?")

    def test_mark_answered_persists(self):
        entry = self.qqm.generate_question("被回答的问题?")
        resp = self.client.put(
            f"/api/v1/growth/questions/{entry.id}/answer",
            params={"answer": "因为瑞利散射"},
        )
        self.assertEqual(resp.status_code, 200)
        stored = self.qqm.get_question(entry.id)
        self.assertEqual(stored.status.value, "answered")
        self.assertEqual(stored.metadata.get("answer"), "因为瑞利散射")


if __name__ == "__main__":
    unittest.main()
