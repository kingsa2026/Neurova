"""RSI 端到端评测集测试（Auto Harness 思想，QP 对比启发 #7）。

现状：RSI 棘轮的 gain 是"信号估算"（setpoint 梯度的启发式），不是
"整个 agent 是否变好"的行为实测——参数贴近度满分不代表行为正确。

设计：确定性评测集（零 LLM、纯内存、毫秒级），8 个用例覆盖四族可优化
参数的实际子系统行为。真值契约 = 参数处于 setpoint 时的行为：
- 参数在 setpoint → 全部用例满分（基准契约）；
- 参数棘轮漂移进有害区间 → 对应用例失分 → gain<0 → 棘轮自动回滚。

用例矩阵：
  tool_memory: tm_multiplier_differentiation（奖惩分化）
               tm_decay_forgetting_band（遗忘带宽：不衰减/过衰减都扣分）
               tm_threshold_band（肌肉记忆阈值语义域）
  sleep:       sl_dedup_band（相似合并：欠合并/过合并都扣分）
               sl_decay_band（睡眠衰减带宽）
  emotion:     em_protection_direction（情感记忆不得比中性记忆衰减更快）
               em_threshold_band（保护阈值语义域）
  experience:  ex_crystallization_band（结晶门槛：欠结晶/过结晶都扣分）
               ex_pattern_support_band（模式支持度：欠挖掘/过挖掘都扣分）
"""

import copy
import datetime
import unittest
from unittest.mock import Mock, patch

from neurova.evolution.rsi.eval_harness import RSIEvalHarness
from neurova.evolution.rsi.system_performance import SYSTEM_SETPOINTS


def _setpoint_params():
    """全部参数置于 setpoint（评测真值基准）。"""
    return {
        system: dict(params) for system, params in SYSTEM_SETPOINTS.items()
    }


class HarnessContractTest(unittest.TestCase):
    def setUp(self):
        self.harness = RSIEvalHarness()

    def test_setpoint_params_score_full(self):
        """核心契约：参数全在 setpoint → 全部用例满分。"""
        outcome = self.harness.run(_setpoint_params())
        self.assertAlmostEqual(outcome["score"], 1.0, places=6, msg=str(outcome["cases"]))
        self.assertEqual(len(outcome["cases"]), 9)

    def test_deterministic_across_runs(self):
        first = self.harness.run(_setpoint_params())
        second = self.harness.run(_setpoint_params())
        self.assertEqual(first["score"], second["score"])

    def test_score_in_unit_range(self):
        outcome = self.harness.run(_setpoint_params())
        self.assertGreaterEqual(outcome["score"], 0.0)
        self.assertLessEqual(outcome["score"], 1.0)

    def test_all_four_families_covered(self):
        outcome = self.harness.run(_setpoint_params())
        families = {c["family"] for c in outcome["cases"]}
        self.assertEqual(families, {"tool_memory", "sleep", "emotion", "experience"})


class SensitivityTest(unittest.TestCase):
    """有害漂移必须被对应用例捕获（评测集不是橡皮图章）。"""

    def setUp(self):
        self.harness = RSIEvalHarness()
        self.baseline = self.harness.run(_setpoint_params())["score"]

    def _score_with(self, system, param, value):
        params = _setpoint_params()
        params[system][param] = value
        outcome = self.harness.run(params)
        case = next(c for c in outcome["cases"] if c["id"].startswith(_CASE_OF[(system, param)]))
        return case["score"]

    def test_bonus_penalty_zero_kills_differentiation(self):
        params = _setpoint_params()
        params["tool_memory"]["success_bonus"] = 0.0
        params["tool_memory"]["failure_penalty"] = 0.0
        outcome = self.harness.run(params)
        case = next(c for c in outcome["cases"] if c["id"] == "tm_multiplier_differentiation")
        self.assertLess(case["score"], 1.0, "奖惩全零 → 好坏工具无分化 → 必须扣分")

    def test_decay_rate_runaway_kills_forgetting_band(self):
        self.assertEqual(self._score_with("tool_memory", "decay_rate", 1.0), 0.0)
        self.assertEqual(self._score_with("tool_memory", "decay_rate", 0.0), 0.0)

    def test_similarity_threshold_extremes_break_dedup(self):
        # 欠合并（阈值 1.0：完全相同的记忆对也不再合并）
        self.assertEqual(self._score_with("sleep", "similarity_threshold", 1.0), 0.0)
        # 过合并（阈值 0.05：不相关记忆也被吞并）
        self.assertEqual(self._score_with("sleep", "similarity_threshold", 0.05), 0.0)

    def test_sleep_decay_rate_extremes_break_band(self):
        self.assertEqual(self._score_with("sleep", "base_decay_rate", 0.0), 0.0)
        self.assertEqual(self._score_with("sleep", "base_decay_rate", 1.0), 0.0)

    def test_emotion_factor_above_one_breaks_protection(self):
        """保护因子 >1 = 情感记忆衰减更快——方向性违反必被抓。"""
        self.assertEqual(self._score_with("emotion", "emotional_protection_factor", 1.5), 0.0)

    def test_emotion_threshold_runaway_breaks_band(self):
        self.assertEqual(
            self._score_with("emotion", "emotional_protection_threshold", 5.0), 0.0
        )

    def test_crystallization_extremes_break_band(self):
        """三分 graded 用例：漂移至少破一个子断言（<1.0）。"""
        # 门槛过严：4 观察 75% 的模式不再结晶
        self.assertLess(self._score_with("experience", "crystallize_min_observations", 10), 1.0)
        # 门槛过松：2 观察 90% 的模式也结晶
        self.assertLess(self._score_with("experience", "crystallize_min_observations", 1), 1.0)
        self.assertLess(self._score_with("experience", "crystallize_min_success_rate", 0.95), 1.0)
        self.assertLess(self._score_with("experience", "crystallize_min_success_rate", 0.1), 1.0)

    def test_pattern_support_extremes_break_band(self):
        """模式支持度带宽：过严（3 次模式不再被挖掘）/过松（1 次模式也被挖掘）。"""
        self.assertLess(self._score_with("experience", "pattern_min_support", 10), 1.0)
        self.assertLess(self._score_with("experience", "pattern_min_support", 1), 1.0)

    def test_overall_score_drops_on_harmful_drift(self):
        params = _setpoint_params()
        params["sleep"]["similarity_threshold"] = 1.0
        outcome = self.harness.run(params)
        self.assertLess(outcome["score"], self.baseline)


# (system, param) → 关联用例 id 前缀（敏感性断言用）
_CASE_OF = {
    ("tool_memory", "decay_rate"): "tm_decay",
    ("sleep", "similarity_threshold"): "sl_dedup",
    ("sleep", "base_decay_rate"): "sl_decay",
    ("emotion", "emotional_protection_factor"): "em_protection",
    ("emotion", "emotional_protection_threshold"): "em_threshold",
    ("experience", "crystallize_min_observations"): "ex_crystallization",
    ("experience", "crystallize_min_success_rate"): "ex_crystallization",
    ("experience", "pattern_min_support"): "ex_pattern",
}


class HarnessRobustnessTest(unittest.TestCase):
    def setUp(self):
        self.harness = RSIEvalHarness()

    def test_missing_param_falls_back_to_setpoint(self):
        params = _setpoint_params()
        del params["tool_memory"]["success_bonus"]
        outcome = self.harness.run(params)
        self.assertAlmostEqual(outcome["score"], 1.0, places=6)

    def test_case_exception_scores_zero_not_raises(self):
        """坏参数导致子系统抛异常 → 该用例 0 分，评测整体不炸。"""
        params = _setpoint_params()
        params["tool_memory"]["muscle_memory_threshold"] = "not-a-number"
        outcome = self.harness.run(params)  # 不抛
        self.assertLess(outcome["score"], 1.0)


class OrchestratorWiringTest(unittest.TestCase):
    """_measure_performance 以评测集为主标尺；gain<0 棘轮回滚复用。"""

    def _make_orchestrator(self):
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        from neurova.evolution.experience_feedback import ExperienceFeedback
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        sleep_system = SleepConsolidation()
        emotion_system = Mock(spec=["emotional_protection_threshold", "emotional_protection_factor", "get_feedback"])
        emotion_system.emotional_protection_threshold = 0.5
        emotion_system.emotional_protection_factor = 1.0
        emotion_system.get_feedback = Mock(return_value={})
        experience_system = ExperienceFeedback()
        tool_memory_system = AdaptiveToolWeights()

        orchestrator = RSIOrchestrator(
            sleep_system=sleep_system,
            emotion_system=emotion_system,
            experience_system=experience_system,
            tool_memory_system=tool_memory_system,
        )
        orchestrator.deployment_controller = Mock()
        orchestrator.deployment_controller.can_auto_execute = Mock(return_value=True)
        return orchestrator

    def test_measure_performance_uses_eval_score(self):
        orchestrator = self._make_orchestrator()
        harness = Mock()
        harness.run.return_value = {"score": 0.83, "cases": []}
        orchestrator._eval_harness = harness

        score = orchestrator._measure_performance()
        self.assertAlmostEqual(score, 0.83)
        self.assertEqual(orchestrator._last_eval_outcome["score"], 0.83)

    def test_measure_performance_falls_back_on_harness_failure(self):
        orchestrator = self._make_orchestrator()
        harness = Mock()
        harness.run.side_effect = RuntimeError("boom")
        orchestrator._eval_harness = harness

        score = orchestrator._measure_performance()  # 不抛，回退信号估算
        self.assertIsInstance(score, float)
        self.assertIsNone(orchestrator._last_eval_outcome)

    def test_harmful_change_triggers_ratchet_rollback(self):
        """评测分下降 → gain<0 → 参数回滚（端到端标尺驱动棘轮）。"""
        orchestrator = self._make_orchestrator()
        tool_memory = orchestrator.integration_manager._systems["tool_memory"]

        harness = Mock()
        # 第一次评测（应用前）0.9 → 应用后 0.5 → gain<0 → 回滚
        harness.run.side_effect = [
            {"score": 0.9, "cases": []},
            {"score": 0.5, "cases": []},
        ]
        orchestrator._eval_harness = harness

        fake_optimization = {
            "system": "tool_memory",
            "parameter": "tool_memory.failure_penalty",
            "current_value": tool_memory.failure_penalty,
            "new_value": 0.05,  # 有害：惩罚几乎清零
            "performance": 0.5,
            "setpoint": 0.5,
            "reason": "test",
        }
        with patch.object(orchestrator, "generate_optimizations", return_value=[fake_optimization]):
            with patch.object(orchestrator, "collect_feedback_signals", return_value={}):
                result = orchestrator.run_iteration()

        self.assertEqual(result["applied_count"], 0, "评测分下降 → 有害调整必须回滚")
        self.assertEqual(result["gain"], 0.0)
        self.assertAlmostEqual(tool_memory.failure_penalty, fake_optimization["current_value"])
        self.assertEqual(result["eval"]["before"]["score"], 0.9)
        self.assertEqual(result["eval"]["after"]["score"], 0.5)

    def test_benign_change_kept_with_positive_or_zero_gain(self):
        orchestrator = self._make_orchestrator()
        tool_memory = orchestrator.integration_manager._systems["tool_memory"]

        harness = Mock()
        harness.run.side_effect = [
            {"score": 0.8, "cases": []},
            {"score": 0.85, "cases": []},
        ]
        orchestrator._eval_harness = harness

        fake_optimization = {
            "system": "tool_memory",
            "parameter": "tool_memory.failure_penalty",
            "current_value": tool_memory.failure_penalty,
            "new_value": 0.45,
            "performance": 0.5,
            "setpoint": 0.5,
            "reason": "test",
        }
        with patch.object(orchestrator, "generate_optimizations", return_value=[fake_optimization]):
            with patch.object(orchestrator, "collect_feedback_signals", return_value={}):
                result = orchestrator.run_iteration()

        self.assertEqual(result["applied_count"], 1)
        self.assertAlmostEqual(result["gain"], 0.05)
        self.assertAlmostEqual(tool_memory.failure_penalty, 0.45)


if __name__ == "__main__":
    unittest.main()
