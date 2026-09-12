"""RSI 参数治理测试 — setpoint 表对齐真实消费方 + 死旋钮激活收尾。

遗留项处理（2026-09-12）：
1. setpoint 表此前从 Agent 镜像属性抄写（failure_penalty 0.5/decay_rate 0.1/
   factor 1.0），与融合文档钉死的设计值冲突（docs/Neurova_OpenClaw工具技能
   专项对比 §7："success_bonus=0.1/failure_penalty=0.05/decay_rate=0.01，
   与 ToolMemoryIntegration 构造默认精确对齐零偏差"）→ 全表对齐真实消费方默认。
2. experience.pattern_min_support 死参数（定义后零消费）→ 属性桥同步
   PatternMiner.min_support（跟随 ToolMemoryIntegration 的 property 模式）。
3. sleep.merge_threshold 是 similarity_threshold 的构造期别名（独立属性后
   零消费）→ property 别名 + 从 RSI 表移除（同一真实参数不得有两个
   setpoint 互斥——0.8/0.9 各拉各的）。
4. emotion.emotional_protection_factor 死旋钮（EmotionModule 定义后零消费，
   而真正衰减的 a.temperature_engine 用默认参数构造）→ attach_temperature_engine
   桥 + property setter 转发。
"""

import unittest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
from neurova.evolution.closed_loop import EvolutionOrchestrator
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
from neurova.evolution.rsi.system_performance import SYSTEM_SETPOINTS


class SetpointTableCanonicalTest(unittest.TestCase):
    """setpoint 表 = 真实消费方的设计默认（拍板结果钉死防回归）。"""

    def test_tool_memory_aligns_fusion_doc(self):
        self.assertEqual(SYSTEM_SETPOINTS["tool_memory"]["failure_penalty"], 0.05)
        self.assertEqual(SYSTEM_SETPOINTS["tool_memory"]["decay_rate"], 0.01)
        self.assertEqual(SYSTEM_SETPOINTS["tool_memory"]["success_bonus"], 0.1)
        self.assertEqual(SYSTEM_SETPOINTS["tool_memory"]["muscle_memory_threshold"], 0.8)

    def test_emotion_aligns_real_consumer(self):
        self.assertEqual(SYSTEM_SETPOINTS["emotion"]["emotional_protection_threshold"], 0.5)
        self.assertEqual(SYSTEM_SETPOINTS["emotion"]["emotional_protection_factor"], 0.3)

    def test_sleep_aligns_class_default_and_has_no_phantom(self):
        self.assertEqual(SYSTEM_SETPOINTS["sleep"]["base_decay_rate"], 0.1)
        self.assertEqual(SYSTEM_SETPOINTS["sleep"]["similarity_threshold"], 0.7)
        self.assertNotIn(
            "merge_threshold", SYSTEM_SETPOINTS["sleep"], "别名幻影不得有独立 setpoint"
        )

    def test_experience_support_setpoint(self):
        self.assertEqual(SYSTEM_SETPOINTS["experience"]["pattern_min_support"], 2)

    def test_optimizable_table_has_no_phantom_merge(self):
        names = [p["name"] for p in RSIIntegrationManager.OPTIMIZABLE_PARAMETERS["sleep"]]
        self.assertNotIn("merge_threshold", names)


class PatternMinSupportBridgeTest(unittest.TestCase):
    def test_bridge_syncs_default_on_attach(self):
        fb = ExperienceFeedback()
        miner = _MinerStub()
        fb.attach_pattern_miner(miner)
        self.assertEqual(miner.min_support, 2, "ExperienceFeedback 默认应与 PatternMiner 默认一致")

    def test_setter_syncs_miner(self):
        fb = ExperienceFeedback()
        miner = _MinerStub()
        fb.attach_pattern_miner(miner)
        fb.pattern_min_support = 5
        self.assertEqual(miner.min_support, 5)
        self.assertEqual(fb.pattern_min_support, 5, "本地副本保留")

    def test_setter_without_miner_safe(self):
        fb = ExperienceFeedback()
        fb.pattern_min_support = 3  # 不抛
        self.assertEqual(fb.pattern_min_support, 3)

    def test_orchestrator_wires_bridge(self):
        orch = EvolutionOrchestrator()
        self.assertIs(orch.experience_feedback._pattern_miner, orch.pattern_miner)


class MergeThresholdAliasTest(unittest.TestCase):
    def test_setter_aliases_similarity(self):
        sc = SleepConsolidation()
        sc.merge_threshold = 0.9
        self.assertEqual(sc.similarity_threshold, 0.9)
        self.assertEqual(sc.merge_threshold, 0.9)

    def test_getter_tracks_similarity(self):
        sc = SleepConsolidation()
        sc.similarity_threshold = 0.6
        self.assertEqual(sc.merge_threshold, 0.6)


class EmotionEngineBridgeTest(unittest.TestCase):
    def test_attach_syncs_current_values(self):
        em = EmotionModule()
        engine = TemperatureEngine()
        em.attach_temperature_engine(engine)
        self.assertEqual(engine.emotional_protection_threshold, em.emotional_protection_threshold)
        self.assertEqual(engine.emotional_protection_factor, em.emotional_protection_factor)

    def test_setter_forwards_to_engine(self):
        em = EmotionModule()
        engine = TemperatureEngine()
        em.attach_temperature_engine(engine)
        em.emotional_protection_factor = 0.1
        em.emotional_protection_threshold = 0.7
        self.assertEqual(engine.emotional_protection_factor, 0.1)
        self.assertEqual(engine.emotional_protection_threshold, 0.7)
        self.assertEqual(em.emotional_protection_factor, 0.1, "本地副本保留（模块内 199 行仍消费）")

    def test_attach_none_safe(self):
        em = EmotionModule()
        em.attach_temperature_engine(None)
        em.emotional_protection_factor = 0.2  # 不抛
        self.assertEqual(em.emotional_protection_factor, 0.2)


class _MinerStub:
    """PatternMiner 形状桩：只验证桥同步，不跑 PrefixSpan。"""

    def __init__(self):
        self.min_support = 2


if __name__ == "__main__":
    unittest.main()
