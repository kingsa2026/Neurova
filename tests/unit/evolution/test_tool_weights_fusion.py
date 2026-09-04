"""A/B 版棘轮融合契约测试（融合方案见 docs/Neurova_OpenClaw工具技能专项对比_2026-09-04.md §7）。

背景：closed_loop.AdaptiveToolWeights（B 版，生产正身）吸收 evolution/tool_weights.py（A 版）
的三个科学思想——滑动窗口成功率、惰性时间衰减、参数化（RSI 可调）。

契约（红→绿）：
1. 滑动窗口：update_weight 维护 window（(timestamp, success) 队列，上限 window_size），
   get_effective_weight 的成功率取窗口内近期表现，不再用终身 success/failure 计数。
2. 惰性时间衰减：读取权重时按 last_used 距今对 adaptive_multiplier 施加
   exp(-decay_rate * hours)，长期未用的工具权重自然回落。
3. 参数化（RSI 活表）：AdaptiveToolWeights 暴露 success_bonus/failure_penalty/decay_rate/
   window_size 等真实消费属性；RSI OPTIMIZABLE_PARAMETERS 的 update 路径
   （integration_manager.apply_optimization → setattr）落到这些属性后行为可观测变化。
4. 兼容：旧持久化 JSON（无新字段）加载安全默认；现有接线测试断言（方向性）全部保持。
5. 边界：首次更新（total==0）有效权重=1.0（保持现有语义，避免未观测工具被惩罚）。
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from neurova.evolution.closed_loop import AdaptiveToolWeights


class TestWindowedSuccessRate(unittest.TestCase):
    """契约 1：窗口成功率替代终身计数。"""

    def test_recent_failures_dominate_after_long_success_history(self):
        """终身成功率 90% 但最近 5 连失败 → 窗口内成功率 0.75 → 权重应低于终身口径。
        （旧 B 版：0.9 × multiplier≈1.16 ≈ 1.045；窗口化后 0.75 × 1.16 ≈ 0.87）"""
        w = AdaptiveToolWeights(window_size=20)
        w.register_tool("t")
        for _ in range(45):
            w.update_weight("t", True)
        for _ in range(5):
            w.update_weight("t", False)
        eff = w.get_effective_weight("t")
        self.assertLess(eff, 0.95)   # 终身口径会到 1.04，窗口口径必须低于它
        self.assertGreater(eff, 0.5)

    def test_window_size_bounds_memory(self):
        """窗口有上限：window_size=5 时只保留最近 5 条。"""
        w = AdaptiveToolWeights(window_size=5)
        w.register_tool("t")
        for _ in range(100):
            w.update_weight("t", True)
        entry = w.get_weight("t")
        self.assertLessEqual(len(entry.window), 5)

    def test_unobserved_tool_full_weight(self):
        """未观测工具有效权重=1.0（保持现有语义）。"""
        w = AdaptiveToolWeights()
        self.assertEqual(w.get_effective_weight("never_seen"), 1.0)


class TestLazyTimeDecay(unittest.TestCase):
    """契约 2：读时惰性时间衰减。"""

    def test_stale_tool_decays(self):
        """2 周未用 → multiplier 按 exp(-decay_rate*336h) 衰减，有效权重下降。"""
        w = AdaptiveToolWeights(decay_rate=0.01)
        w.register_tool("t")
        w.update_weight("t", True)
        entry = w.get_weight("t")
        entry.last_used = datetime.now(UTC) - timedelta(hours=336)
        before = entry.adaptive_multiplier
        eff = w.get_effective_weight("t")
        # multiplier 本身被衰减（惰性、无写盘副作用）
        self.assertLess(w.get_weight("t").adaptive_multiplier, before)
        # exp(-0.01*336) ≈ 0.0346，几乎归底
        self.assertLess(eff, 0.9)

    def test_fresh_tool_no_decay(self):
        """刚用过的工具不衰减。"""
        w = AdaptiveToolWeights(decay_rate=0.01)
        w.register_tool("t")
        w.update_weight("t", True)
        m = w.get_weight("t").adaptive_multiplier
        w.get_effective_weight("t")
        self.assertAlmostEqual(w.get_weight("t").adaptive_multiplier, m, places=9)

    def test_decay_floor_respected(self):
        """衰减不打穿 min_multiplier 下限。"""
        w = AdaptiveToolWeights(decay_rate=10.0, min_multiplier=0.3)
        w.register_tool("t")
        w.update_weight("t", True)
        w.get_weight("t").last_used = datetime.now(UTC) - timedelta(hours=48)
        w.get_effective_weight("t")
        self.assertGreaterEqual(w.get_weight("t").adaptive_multiplier, 0.3)


class TestRsiLiveParameters(unittest.TestCase):
    """契约 3：RSI 活表——setattr 参数后行为可观测变化。"""

    def test_params_exposed_and_consumed(self):
        w = AdaptiveToolWeights(
            success_bonus=0.5, failure_penalty=0.9,
            decay_rate=0.01, window_size=10,
        )
        w.register_tool("a")
        w.register_tool("b")
        w.update_weight("a", True)
        w.update_weight("b", False)
        ma = w.get_weight("a").adaptive_multiplier
        mb = w.get_weight("b").adaptive_multiplier
        self.assertGreater(ma, 1.4)   # 1 + bonus(0.5) > 1.4，而默认 1.05 只到 1.05
        self.assertLess(mb, 0.91)     # ×0.9 < ×0.95
        self.assertEqual(w.window_size, 10)
        self.assertAlmostEqual(w.decay_rate, 0.01)
        self.assertAlmostEqual(w.success_bonus, 0.5)
        self.assertAlmostEqual(w.failure_penalty, 0.9)

    def test_rsi_setattr_changes_behavior(self):
        """模拟 RSI apply_optimization：直接 setattr 后下次 update 行为变化。"""
        w = AdaptiveToolWeights(max_multiplier=3.0)
        w.register_tool("t")
        w.update_weight("t", True)
        w.update_weight("t", True)
        m_default = w.get_weight("t").adaptive_multiplier  # 1 + 0.1 + 0.091 ≈ 1.191

        w.success_bonus = 0.5  # RSI 调参
        w.update_weight("t", True)
        delta = w.get_weight("t").adaptive_multiplier - m_default
        self.assertGreater(delta, 0.2)  # 默认 bonus(k=2)≈0.083，调参后 0.5/1.2≈0.417

    def test_integration_manager_can_setattr(self):
        """integration_manager.apply_optimization 对权重系统的 setattr 不再是死参数：
        参数名在 RSI 表中，且 ToolMemoryIntegration 属性存在、set 后读回一致。"""
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager

        names = {
            p["name"]
            for group in RSIIntegrationManager.OPTIMIZABLE_PARAMETERS.values()
            for p in group
        }
        w = AdaptiveToolWeights()
        for attr in ("success_bonus", "failure_penalty", "decay_rate"):
            self.assertIn(attr, names, f"{attr} 应在 RSI 参数表中")
            self.assertTrue(hasattr(w, attr), f"权重对象应真实消费 {attr}")


class TestPersistenceCompat(unittest.TestCase):
    """契约 4：旧 JSON 兼容 + 新字段落盘。"""

    def test_old_json_loads_with_safe_defaults(self):
        import json
        import tempfile
        from pathlib import Path

        old_payload = {
            "version": 1,
            "weights": {
                "legacy_tool": {
                    "success_count": 10,
                    "failure_count": 2,
                    "total_latency": 1.0,
                    "adaptive_multiplier": 1.2,
                    "last_used": "2026-08-01T00:00:00+00:00",
                    "lifecycle_state": "active",
                }
            },
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "w.json"
            p.write_text(json.dumps(old_payload), encoding="utf-8")
            w = AdaptiveToolWeights()
            self.assertTrue(w.load(p))
        entry = w.get_weight("legacy_tool")
        self.assertAlmostEqual(entry.adaptive_multiplier, 1.2)

    def test_save_roundtrip_keeps_window(self):
        import json
        import tempfile
        from pathlib import Path

        w = AdaptiveToolWeights()
        w.register_tool("t")
        w.update_weight("t", True)
        w.update_weight("t", False)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "w.json"
            self.assertTrue(w.save(p))
            raw = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("window", raw["weights"]["t"])
            w2 = AdaptiveToolWeights()
            self.assertTrue(w2.load(p))
            self.assertEqual(len(w2.get_weight("t").window), 2)


class TestRsiEndToEndChain(unittest.TestCase):
    """契约 3 的完整链路：RSI apply_optimization → integration property → weights.configure。"""

    def _manager_with(self):
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
            ToolMemoryIntegration,
        )

        weights = AdaptiveToolWeights()
        weights.register_tool("t")
        integration = ToolMemoryIntegration(
            memory_layer=None, muscle_memory=None, tool_weights=weights,
        )
        manager = RSIIntegrationManager(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=integration,
        )
        return manager, integration, weights

    def test_apply_optimization_reaches_weights(self):
        manager, integration, weights = self._manager_with()
        w_before = weights.success_bonus
        self.assertTrue(manager.apply_optimization("tool_memory.success_bonus", 0.5))
        self.assertAlmostEqual(weights.success_bonus, 0.5)
        self.assertAlmostEqual(integration.success_bonus, 0.5)
        self.assertNotEqual(weights.success_bonus, w_before)

    def test_stale_tool_threshold_rises(self):
        """长期未用的工具（衰减后乘数下降）→ 动态阈值回升，更难自动执行。"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
            ToolMemoryIntegration,
        )

        weights = AdaptiveToolWeights()
        weights.register_tool("t")
        weights.update_weight("t", True)
        integration = ToolMemoryIntegration(
            memory_layer=None, muscle_memory=None, tool_weights=weights,
        )
        fresh = integration._get_dynamic_threshold("t")
        weights.get_weight("t").last_used = datetime.now(UTC) - timedelta(hours=336)
        stale = integration._get_dynamic_threshold("t")
        self.assertGreater(stale, fresh)


class TestLegacyWiringUnchanged(unittest.TestCase):
    """契约 5：现有接线的方向性断言保持（防融合破坏齿轮）。"""

    def test_failure_then_threshold_gears_still_hold(self):
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
            ToolMemoryIntegration,
        )

        weights = AdaptiveToolWeights()
        weights.register_tool("tool_a", base_weight=1.0)
        integration = ToolMemoryIntegration(
            memory_layer=None, muscle_memory=None, tool_weights=weights,
        )
        before = integration._get_dynamic_threshold("tool_a")
        weights.update_weight("tool_a", False)
        after = integration._get_dynamic_threshold("tool_a")
        self.assertGreater(after, before)

    def test_multiplier_clamped_symmetric(self):
        w = AdaptiveToolWeights()
        w.register_tool("t")
        for _ in range(100):
            w.update_weight("t", True)
        self.assertLessEqual(w.get_weight("t").adaptive_multiplier, 1.5)
        for _ in range(100):
            w.update_weight("t", False)
        self.assertGreaterEqual(w.get_weight("t").adaptive_multiplier, 0.3)


if __name__ == "__main__":
    unittest.main()
