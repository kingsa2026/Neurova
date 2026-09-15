"""ProactiveBehaviorEngine 契约测试（2026-09-15 动机/主动行为真实化）

主动行为引擎此前全仓从未实例化（/growth/proactive 恒空、motivation 恒默认值，
属假接口）。真实化：记录实际发生的主动行为（当前唯一真实通道=主动提问），
JSON 落盘跨重启，用户回应回流 response_received。
"""

import os
import tempfile
import unittest

from neurova.cognitive_layers.meta_cognition_layer.proactive_behavior import ProactiveBehaviorEngine


class ProactiveBehaviorEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "proactive", "proactive_actions.json")
        self.engine = ProactiveBehaviorEngine(agent_id="t1", persistence_path=self.path)

    def test_record_and_list(self):
        action = self.engine.record_action(
            action_type="communication",
            trigger="proactive_question:q-1",
            content="用户对「量子计算」有困惑，主动询问具体哪里不清楚",
        )
        self.assertTrue(action["action_id"])
        self.assertEqual(action["agent_id"], "t1")
        self.assertTrue(action["success"])
        self.assertFalse(action["response_received"])
        self.assertGreater(action["timestamp"], 0)

        recent = self.engine.get_recent_actions(limit=10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["trigger"], "proactive_question:q-1")

    def test_persistence_survives_restart(self):
        self.engine.record_action(action_type="communication", trigger="proactive_question:q-2", content="提问X")
        self.assertTrue(os.path.exists(self.path))

        engine2 = ProactiveBehaviorEngine(agent_id="t1", persistence_path=self.path)
        recent = engine2.get_recent_actions(limit=10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["content"], "提问X")

    def test_mark_response_received(self):
        action = self.engine.record_action(action_type="communication", trigger="proactive_question:q-3", content="提问Y")
        self.assertTrue(self.engine.mark_response_received(action["action_id"]))
        recent = self.engine.get_recent_actions(limit=10)
        self.assertTrue(recent[0]["response_received"])
        # 重启后仍为已回应
        engine2 = ProactiveBehaviorEngine(agent_id="t1", persistence_path=self.path)
        self.assertTrue(engine2.get_recent_actions(limit=10)[0]["response_received"])

    def test_mark_response_by_trigger(self):
        """问题队列 answered 回流：按 trigger 定位动作（调用方无需持有 action_id）"""
        self.engine.record_action(action_type="communication", trigger="proactive_question:q-4", content="提问Z")
        self.assertTrue(self.engine.mark_response_received_by_trigger("proactive_question:q-4"))
        self.assertTrue(self.engine.get_recent_actions(limit=10)[0]["response_received"])
        self.assertFalse(self.engine.mark_response_received_by_trigger("proactive_question:missing"))

    def test_cap_500(self):
        for i in range(520):
            self.engine.record_action(action_type="communication", trigger=f"t{i}", content=f"c{i}")
        self.assertLessEqual(len(self.engine.get_recent_actions(limit=1000)), 500)


if __name__ == "__main__":
    unittest.main()
