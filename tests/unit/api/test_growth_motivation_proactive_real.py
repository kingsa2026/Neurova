"""动机/主动行为端点与接线契约测试（2026-09-15 真实化）

根因：proactive_behavior_engine 全仓从未实例化（/growth/proactive 恒空）；
/growth/motivation 依赖同一引擎 → 恒返回常量 0.5（假接口）。
真实化后：GET /motivation 返回 MotivationLedger 真实快照（envelope {code,data}，
原裸模型返回与前端 .data 解包不符）；PUT 调权重；/proactive 返回真实动作；
回答回流联动 engine.mark_response_received_by_trigger + purpose 观察。
"""

import os
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.cognitive_layers.meta_cognition_layer.proactive_behavior import ProactiveBehaviorEngine
from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionQueueManager
from neurova.core.motivation_ledger import MotivationLedger


class MotivationProactiveEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger = MotivationLedger(agent_id="t1", persistence_path=os.path.join(self.tmpdir, "motivation.json"))
        self.engine = ProactiveBehaviorEngine(agent_id="t1", persistence_path=os.path.join(self.tmpdir, "actions.json"))
        self.qqm = QuestionQueueManager(memory_manager=None, default_cooldown=0.0)
        agent = types.SimpleNamespace(
            intrinsic_motivation=self.ledger,
            proactive_behavior_engine=self.engine,
            question_queue_manager=self.qqm,
        )

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
        self._patcher = patch.object(growth_api, "_get_agent", return_value=agent)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---------- motivation ----------

    def test_motivation_returns_real_snapshot_envelope(self):
        self.ledger.observe_growth(concept="测试概念", understanding=0.9)
        expected = self.ledger.snapshot()

        resp = self.client.get("/api/v1/growth/motivation", params={"agent_id": "t1"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["agent_id"], "t1")
        self.assertAlmostEqual(data["level"], expected["level"], places=3)
        self.assertEqual({f["name"] for f in data["factors"]}, {"competence", "autonomy", "growth", "purpose"})

    def test_motivation_level_not_constant_after_events(self):
        """真实化判据：信号灌入后 level 必须偏离初始常量"""
        before = self.client.get("/api/v1/growth/motivation", params={"agent_id": "t1"}).json()["data"]["level"]
        for i in range(6):
            self.ledger.observe_competence(success=True, difficulty=0.6)
        after = self.client.get("/api/v1/growth/motivation", params={"agent_id": "t1"}).json()["data"]["level"]
        self.assertNotEqual(before, after)

    def test_motivation_envelope_when_engine_absent(self):
        """未装配诚实返回 data=null（不得回吐常量假状态）"""
        agent_bare = types.SimpleNamespace(intrinsic_motivation=None, proactive_behavior_engine=None, question_queue_manager=None)
        with patch("neurova.api.endpoints.growth._get_agent", return_value=agent_bare):
            resp = self.client.get("/api/v1/growth/motivation", params={"agent_id": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["data"])

    def test_put_motivation_updates_drive_weights(self):
        resp = self.client.put(
            "/api/v1/growth/motivation",
            params={"agent_id": "t1"},
            json={"drive_weights": {"competence": 0.4, "growth": 0.4, "autonomy": 0.1, "purpose": 0.1}},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        weights = data["drive_weights"]
        self.assertAlmostEqual(weights["competence"], 0.4, places=2)
        self.assertAlmostEqual(weights["purpose"], 0.1, places=2)

    # ---------- proactive actions ----------

    def test_proactive_actions_real_data(self):
        self.engine.record_action(action_type="communication", trigger="proactive_question:q-api-1", content="主动提问内容")
        resp = self.client.get("/api/v1/growth/proactive", params={"agent_id": "t1"})
        self.assertEqual(resp.status_code, 200)
        actions = resp.json()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_type"], "communication")
        self.assertEqual(actions[0]["content"], "主动提问内容")
        self.assertFalse(actions[0]["response_received"])

    def test_overview_carries_motivation_and_actions(self):
        self.engine.record_action(action_type="communication", trigger="t", content="c")
        self.ledger.observe_purpose(contribution="回应", impact=0.8)
        resp = self.client.get("/api/v1/growth", params={"agent_id": "t1"})
        data = resp.json()["data"]
        self.assertIsNotNone(data["motivation_level"])
        self.assertEqual(len(data["proactive_actions"]), 1)

    def test_answer_question_flows_back_to_engine_and_purpose(self):
        """用户回答主动提问 → 动作 response_received=True + purpose 驱动观察"""
        entry = self.qqm.generate_question(content="被主动提问的问题?")
        self.engine.record_action(action_type="communication", trigger=f"proactive_question:{entry.id}", content="提问")
        p_before = self.ledger.snapshot()["drives"]["purpose"]["intensity"]

        resp = self.client.put(f"/api/v1/growth/questions/{entry.id}/answer", params={"answer": "因为瑞利散射"})
        self.assertEqual(resp.status_code, 200)

        action = self.engine.get_recent_actions(limit=10)[0]
        self.assertTrue(action["response_received"])
        self.assertGreater(self.ledger.snapshot()["drives"]["purpose"]["intensity"], p_before)


class PostChatMotivationWiringTest(unittest.TestCase):
    """post_chat 真实信号接线：轮次成功→competence / 认知分→growth / 主动提问→autonomy+动作记录"""

    def _pipeline(self):
        from neurova.post_chat_pipeline import PostChatPipeline
        from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionQueueManager

        tmpdir = tempfile.mkdtemp()
        self._tmpdir = tmpdir
        ledger = MotivationLedger(agent_id="wire", persistence_path=os.path.join(tmpdir, "m.json"))
        engine = ProactiveBehaviorEngine(agent_id="wire", persistence_path=os.path.join(tmpdir, "a.json"))
        qqm = QuestionQueueManager(memory_manager=None, default_cooldown=0.0)
        agent = types.SimpleNamespace(intrinsic_motivation=ledger, proactive_behavior_engine=engine, question_queue_manager=qqm)
        pipeline = PostChatPipeline(agent)
        return pipeline, ledger, engine, qqm

    def test_step_proactive_question_records_action(self):
        pipeline, ledger, engine, qqm = self._pipeline()
        qqm.generate_question(content="主动提问X")
        import asyncio

        content = asyncio.run(pipeline._step_proactive_question("你好", "回复"))
        self.assertEqual(content, "主动提问X")
        actions = engine.get_recent_actions(limit=10)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["content"], "主动提问X")
        self.assertIn("proactive_question:", actions[0]["trigger"])

    def test_step_motivation_observations_events(self):
        pipeline, ledger, engine, qqm = self._pipeline()
        before = ledger.snapshot()
        import asyncio

        asyncio.run(pipeline._step_motivation_observations(user_input="讲讲量子计算", reply="好的", cognitive_score=0.8, proactive_question=None))
        after = ledger.snapshot()
        self.assertGreater(after["event_count"], before["event_count"])
        self.assertGreater(after["drives"]["growth"]["intensity"], before["drives"]["growth"]["intensity"])

    def test_step_motivation_skipped_without_ledger(self):
        from neurova.post_chat_pipeline import PostChatPipeline

        pipeline = PostChatPipeline(types.SimpleNamespace())
        import asyncio

        result = asyncio.run(pipeline._step_motivation_observations("输入", "回复", 0.5, None))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
