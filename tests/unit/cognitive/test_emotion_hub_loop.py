"""情感中枢闭环测试（P1-B）

覆盖 orchestrator 情感链路的三处断点:
- analyze(user_input) 未传 update_state=True → 17 情感状态机从不累积
- EmotionAnalyzer() 用默认 agent_id="default" → 多 agent 情感状态互相污染
- 注入点读 agent_emotion.get("label")，而 analyze() 返回分数字典没有 label 键
  → 每轮注入的情感恒为 "neutral"
"""

import unittest
from types import SimpleNamespace

from neurova.context.orchestrator import ContextOrchestrator


def _stub_self(agent_id):
    return SimpleNamespace(_agent=SimpleNamespace(config=SimpleNamespace(agent_id=agent_id)))


class EmotionHubLoopTest(unittest.TestCase):
    def setUp(self):
        from neurova.cognitive_layers.emotion_context_layer.emotion_conduction import (
            reset_all_emotion_conduction_managers,
        )
        from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import (
            reset_emotion_hub_engine,
        )

        reset_emotion_hub_engine()
        reset_all_emotion_conduction_managers()

    def tearDown(self):
        from neurova.cognitive_layers.emotion_context_layer.emotion_conduction import (
            reset_all_emotion_conduction_managers,
        )
        from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import (
            reset_emotion_hub_engine,
        )

        reset_emotion_hub_engine()
        reset_all_emotion_conduction_managers()

    def test_analyze_returns_label_and_updates_state(self):
        result = ContextOrchestrator._analyze_user_emotion(
            _stub_self("emo_agent_x"), "我今天非常开心，太高兴了"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["label"], "joy", "主导情感应为 joy（此前恒为 neutral）")
        self.assertGreater(result["intensity"], 0.0)

        from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import (
            get_emotion_hub_engine,
        )

        hub = get_emotion_hub_engine("emo_agent_x")
        self.assertGreater(
            hub.get_emotion_distribution().get("joy", 0.0),
            0.0,
            "update_state=True 应把情感写入长期状态机",
        )

    def test_state_isolated_per_agent(self):
        ContextOrchestrator._analyze_user_emotion(_stub_self("emo_agent_a"), "我非常开心")
        ContextOrchestrator._analyze_user_emotion(_stub_self("emo_agent_b"), "今天很平静")

        from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import (
            get_emotion_hub_engine,
        )

        self.assertGreater(get_emotion_hub_engine("emo_agent_a").get_emotion_distribution().get("joy", 0.0), 0.0)
        self.assertEqual(
            get_emotion_hub_engine("emo_agent_b").get_emotion_distribution().get("joy", 0.0),
            0.0,
            "不同 agent 的情感状态必须隔离",
        )

    def test_state_blends_across_turns(self):
        stub = _stub_self("emo_agent_c")
        first = ContextOrchestrator._analyze_user_emotion(stub, "我很开心")
        second = ContextOrchestrator._analyze_user_emotion(stub, "还是很开心")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(
            second.get("long_term_dominant"),
            "joy",
            "长期状态应跨轮次累积并给出主导情感",
        )
        self.assertIn("tone", second, "应包含风格修饰符（供回复语气调整）")

    def test_neutral_text_without_history_returns_none(self):
        """纯中性文本且无长期情感历史 → 返回 None（不注入噪音）"""
        result = ContextOrchestrator._analyze_user_emotion(_stub_self("emo_agent_d"), "这是一段普通文本")
        self.assertIsNone(result)

    def test_conduction_manager_is_live_owner_of_state_flow(self):
        """情感传导管理器必须是主流程情感状态的活路径（此前零调用）"""
        ContextOrchestrator._analyze_user_emotion(_stub_self("emo_agent_f"), "我很开心")

        from neurova.cognitive_layers.emotion_context_layer.emotion_conduction import (
            get_emotion_conduction_manager,
        )

        stats = get_emotion_conduction_manager("emo_agent_f").get_stats()
        self.assertGreaterEqual(
            stats.get("total_text_analyses", 0),
            1,
            "文本情感分析应经由传导管理器统计",
        )
        self.assertGreaterEqual(
            stats.get("total_state_updates", 0),
            1,
            "情感状态更新应经由传导管理器统计",
        )

    def test_neutral_text_with_long_term_history_still_injects(self):
        """纯中性文本但长期状态机已有倾向 → 注入长期倾向"""
        stub = _stub_self("emo_agent_e")
        ContextOrchestrator._analyze_user_emotion(stub, "我非常开心")  # 先写入长期状态

        result = ContextOrchestrator._analyze_user_emotion(stub, "这是一段普通文本")
        self.assertIsNotNone(result)
        self.assertEqual(result["label"], "neutral")
        self.assertEqual(result["long_term_dominant"], "joy")


if __name__ == "__main__":
    unittest.main()
