"""洞察编译器（SelfModelEngine）五算子契约测试（V3 — 红灯先行）

确定性反思引擎：全 LLM-free，五个算子都是台账上的纯函数。
- ① 漂移检测：近期窗口成功率 vs 基线，Wilson 区间不重叠才确认
- ② 对比检验：上下文分片（has_code_block 等）成功率 vs 其余
- ③ 序列挖掘：连续失败/调用模式
- ④ 校准更新：分片折扣系数（窗口成功率/基线），低折扣触发 avoid_tool 建议
- ⑤ 预算回归：耗时趋势 vs 基线

产出物 = 结构化教训（lesson）：condition/finding/recommendation/text/evidence/source。
"""

import unittest

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    SelfModelEngine,
    get_self_model_engine,
    reset_self_model_engine,
)

AGENT = "engine_agent"


def _feed_tool_events(ledger, tool, successes, failures, context=None):
    meta = dict(context or {})
    for _ in range(successes):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=True, metadata=meta)
    for _ in range(failures):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=False, metadata=meta)


class TestDriftOperator(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        self.engine = get_self_model_engine(AGENT)

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_drift_confirmed_produces_avoid_lesson(self):
        """基线 90% 成功率，近期窗口崩到 0% → 漂移确认 → avoid_tool 教训。"""
        ledger = get_meta_ledger(AGENT)
        _feed_tool_events(ledger, "web_search", 45, 5)          # 基线期：90%
        _feed_tool_events(ledger, "web_search", 0, 10)          # 近期窗口：全败（区间确凿分离）
        report = self.engine.reflect(trigger="test")
        lessons = [l for l in report["lessons"] if l["subject"] == "web_search"]
        self.assertTrue(lessons, "显著漂移必须产出教训")
        self.assertEqual(lessons[0]["operator"], "drift")
        self.assertEqual(lessons[0]["recommendation"], "avoid_tool")
        self.assertEqual(lessons[0]["source"], "template")
        self.assertIn("success_rate", lessons[0]["evidence"])

    def test_no_lesson_under_min_samples(self):
        """样本不足（< min_samples）不得产教训（防噪声误报）。"""
        ledger = get_meta_ledger(AGENT)
        _feed_tool_events(ledger, "web_search", 9, 1)
        report = self.engine.reflect(trigger="test")
        lessons = [l for l in report["lessons"] if l["subject"] == "web_search"]
        self.assertEqual(lessons, [])


class TestContrastOperator(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        self.engine = get_self_model_engine(AGENT)

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_context_slice_contrast(self):
        """工具在含代码块分片上显著差 → 条件性 avoid 教训（condition 带分片）。"""
        ledger = get_meta_ledger(AGENT)
        _feed_tool_events(ledger, "web_search", 9, 1, context={"has_code_block": False})   # 90%
        _feed_tool_events(ledger, "web_search", 8, 2, context={"has_code_block": True})    # 基线期切片
        _feed_tool_events(ledger, "web_search", 2, 8, context={"has_code_block": True})    # 近期切片恶化
        report = self.engine.reflect(trigger="test")
        lessons = [l for l in report["lessons"] if l["subject"] == "web_search" and l["operator"] == "contrast"]
        self.assertTrue(lessons, "分片对比应产出教训")
        self.assertIn("has_code_block", lessons[0]["condition"])


class TestCalibrationAndBudget(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        self.engine = get_self_model_engine(AGENT)

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_calibration_discount_produces_warning(self):
        """窗口成功率/基线折扣 < 0.6 → 校准告警教训（基线 0.6，窗口 0.3，折扣 0.5）。"""
        ledger = get_meta_ledger(AGENT)
        _feed_tool_events(ledger, "flaky_tool", 12, 8)   # 基线 0.6
        _feed_tool_events(ledger, "flaky_tool", 3, 7)    # 窗口 0.3 → 折扣 0.5
        report = self.engine.reflect(trigger="test")
        cal = [l for l in report["lessons"] if l["operator"] == "calibration" and l["subject"] == "flaky_tool"]
        self.assertTrue(cal)
        self.assertLess(cal[0]["evidence"]["discount"], 0.6)

    def test_budget_regression_on_slowdown(self):
        """近期平均耗时 > 基线 2 倍且样本足够 → 预算回归教训。"""
        ledger = get_meta_ledger(AGENT)
        for _ in range(25):
            ledger.write_event(agent_id=AGENT, process_type="tool", description="slow_tool",
                               duration_ms=500.0, success=True)
        for _ in range(25):
            ledger.write_event(agent_id=AGENT, process_type="tool", description="slow_tool",
                               duration_ms=1500.0, success=True)
        report = self.engine.reflect(trigger="test")
        budget = [l for l in report["lessons"] if l["operator"] == "budget" and l["subject"] == "slow_tool"]
        self.assertTrue(budget, "3 倍耗时劣化应触发预算教训")


class TestReflectLifecycle(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        self.engine = get_self_model_engine(AGENT)

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_reflect_writes_record_and_gates_interval(self):
        """reflect 产出反思记录落台账；should_reflect 门控间隔生效。"""
        ledger = get_meta_ledger(AGENT)
        ledger.create_record(agent_id=AGENT, kind="thought", type="planning", content="seed")
        report = self.engine.reflect(trigger="test")
        self.assertIn("confidence", report)
        history = ledger.reflection_history(AGENT)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["trigger"], "test")
        self.assertFalse(self.engine.should_reflect(), "刚反思过不应再触发")
        # 时间倒流模拟间隔到期
        self.engine._last_reflect_at -= self.engine._reflect_interval + 1
        self.assertTrue(self.engine.should_reflect())

    def test_empty_ledger_reflect_is_safe(self):
        """空台账 reflect 必须安全产出空报告（零事件不崩）。"""
        report = self.engine.reflect(trigger="test")
        self.assertEqual(report["lessons"], [])
        self.assertIsInstance(report["observations"], list)

    def test_check_tool_advisory_reads_active_lesson(self):
        """调控门数据源：活跃 avoid_tool 教训 → 拦截建议；无教训 → None。"""
        ledger = get_meta_ledger(AGENT)
        _feed_tool_events(ledger, "bad_tool", 5, 45)   # 10% 成功率
        self.engine.reflect(trigger="test")
        advisory = self.engine.check_tool_advisory("bad_tool")
        self.assertIsNotNone(advisory)
        self.assertEqual(advisory["recommendation"], "avoid_tool")
        self.assertIsNone(self.engine.check_tool_advisory("unknown_tool"))


if __name__ == "__main__":
    unittest.main()
