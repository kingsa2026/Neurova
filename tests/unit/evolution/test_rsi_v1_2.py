"""
P0-C1 修复：RSI v1.2 测试 — 测试真实 RecursiveRatchetPruner / EnhancedRatchetPruner

之前的问题（phantom green）：
    本文件全部测试在函数内部定义 Mock 类（MockRecursiveRatchetPruner、
    MockEnhancedRatchetPruner、MockToolEvolutionHierarchy、MockToolRatchetValidator、
    MockToolParameterEvolver、MockToolRSISafety、MockIntegratedRSI），完全不触及
    neurova/evolution/rsi/recursive_ratchet_pruner.py 的真实实现。10/10 通过是
    "幻影绿"——测试 Mock 类的方法自然返回 Mock 类的硬编码值。

修复策略（bug-hunt Phase 4 surgical fix）：
    重写为测试真实实现：
    - RecursiveRatchetPruner: rounds/candidates_per_round/max_complexity 字段 +
      recursive_prune() 真实算法（粗筛→中筛→细筛）
    - EnhancedRatchetPruner: max_candidates/use_recursive 字段 + prune_candidates()
    - Candidate: 真实数据结构（id/name/parameters/complexity/violates_hard_constraints
      /heuristic_score/quick_evaluation_score/validation_score）
    - 删除测试不存在类的 3 个测试类（TestToolLayerRSI/TestToolRSISafety/TestIntegration）
"""

import unittest
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from neurova.evolution.rsi.recursive_ratchet_pruner import (
    Candidate,
    PruneRoundResult,
    RecursiveRatchetPruner,
    EnhancedRatchetPruner,
)


def _make_candidate(
    name: str,
    complexity: float = 1.0,
    violates: bool = False,
    heuristic_score: float = 0.0,
    quick_evaluation_score: float = 0.0,
    validation_score: float = 0.0,
) -> Candidate:
    """构造测试用 Candidate"""
    return Candidate(
        id=f"c_{name}",
        name=name,
        parameters={"name": name},
        complexity=complexity,
        violates_hard_constraints=violates,
        heuristic_score=heuristic_score,
        quick_evaluation_score=quick_evaluation_score,
        validation_score=validation_score,
    )


class TestRecursiveRatchetPruner(unittest.TestCase):
    """测试真实的 RecursiveRatchetPruner（非 Mock）"""

    def test_recursive_pruner_initialization(self):
        """测试递归棘轮剪枝器初始化 — 真实字段"""
        pruner = RecursiveRatchetPruner()
        # 真实字段
        self.assertEqual(pruner.rounds, 3)
        self.assertEqual(pruner.candidates_per_round, [100, 20, 5])
        self.assertIsNotNone(pruner.max_complexity)
        # 真实精度映射
        self.assertEqual(pruner.round_precision[0], "coarse")
        self.assertEqual(pruner.round_precision[1], "medium")
        self.assertEqual(pruner.round_precision[2], "fine")
        # 历史容器
        self.assertEqual(pruner.prune_history, [])
        self.assertEqual(pruner.failed_candidates_history, [])
        self.assertEqual(pruner.best_candidates_cache, {})

    def test_recursive_pruner_initialization_custom(self):
        """自定义参数构造"""
        pruner = RecursiveRatchetPruner(
            rounds=2,
            candidates_per_round=[10, 3],
            max_complexity=5.0,
        )
        self.assertEqual(pruner.rounds, 2)
        self.assertEqual(pruner.candidates_per_round, [10, 3])
        self.assertEqual(pruner.max_complexity, 5.0)

    def test_recursive_prune_with_candidates(self):
        """recursive_prune 真实算法 — 多轮筛选返回最优 Candidate"""
        pruner = RecursiveRatchetPruner(rounds=3, candidates_per_round=[5, 3, 1])
        # 构造 10 个候选，复杂度递增（低复杂度优先）
        candidates = [
            _make_candidate(f"t{i}", complexity=float(i + 1)) for i in range(10)
        ]

        result = pruner.recursive_prune(candidates)

        # 真实返回：Candidate 或 None
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Candidate)
        # 应该是低复杂度的候选胜出（默认 heuristic = 1 - complexity/max_complexity）
        self.assertEqual(result.name, "t0")

    def test_recursive_prune_records_history(self):
        """recursive_prune 应记录每轮结果到 prune_history"""
        pruner = RecursiveRatchetPruner(rounds=3, candidates_per_round=[5, 3, 1])
        candidates = [_make_candidate(f"t{i}", complexity=float(i + 1)) for i in range(10)]

        pruner.recursive_prune(candidates)

        # 真实字段：prune_history 是 PruneRoundResult 列表
        self.assertGreaterEqual(len(pruner.prune_history), 1)
        for round_result in pruner.prune_history:
            self.assertIsInstance(round_result, PruneRoundResult)
            self.assertIn(round_result.precision, ["coarse", "medium", "fine"])

    def test_recursive_prune_empty_candidates(self):
        """空候选列表 — recursive_prune 返回 None"""
        pruner = RecursiveRatchetPruner()

        result = pruner.recursive_prune([])

        self.assertIsNone(result)

    def test_recursive_prune_excludes_high_complexity(self):
        """粗筛阶段排除复杂度过高的候选"""
        pruner = RecursiveRatchetPruner(
            rounds=3, candidates_per_round=[5, 3, 1], max_complexity=5.0
        )
        # 全部候选复杂度过高
        candidates = [
            _make_candidate("too_complex", complexity=100.0),
        ]

        result = pruner.recursive_prune(candidates)

        # 高复杂度候选被粗筛排除 → 无胜出者
        self.assertIsNone(result)

    def test_recursive_prune_excludes_constraint_violators(self):
        """粗筛阶段排除违反硬约束的候选"""
        pruner = RecursiveRatchetPruner(rounds=3, candidates_per_round=[5, 3, 1])
        candidates = [
            _make_candidate("bad", violates=True, complexity=1.0),
        ]

        result = pruner.recursive_prune(candidates)

        # 违反硬约束的候选被排除 → 无胜出者
        self.assertIsNone(result)

    def test_recursive_prune_with_validation_fn(self):
        """细筛阶段使用 validation_fn 评分"""
        pruner = RecursiveRatchetPruner(rounds=3, candidates_per_round=[5, 3, 1])

        def validation_fn(c: Candidate):
            # 真实返回：dict 包含 functional_correctness 等维度
            return {"functional_correctness": 0.9, "performance_baseline": 0.8}

        candidates = [_make_candidate(f"t{i}", complexity=float(i + 1)) for i in range(5)]
        result = pruner.recursive_prune(candidates, validation_fn=validation_fn)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, Candidate)

    def test_recursive_prune_invalid_rounds_raises(self):
        """rounds <= 0 应抛 ValueError（真实校验）"""
        with self.assertRaises(ValueError):
            RecursiveRatchetPruner(rounds=0)
        with self.assertRaises(ValueError):
            RecursiveRatchetPruner(rounds=-1)

    def test_get_prune_history_returns_dicts(self):
        """get_prune_history 返回字典列表"""
        pruner = RecursiveRatchetPruner(rounds=2, candidates_per_round=[3, 1])
        candidates = [_make_candidate(f"t{i}", complexity=float(i + 1)) for i in range(5)]
        pruner.recursive_prune(candidates)

        history = pruner.get_prune_history()
        self.assertIsInstance(history, list)
        for entry in history:
            self.assertIsInstance(entry, dict)
            # 真实字段名：round（非 round_num）
            self.assertIn("round", entry)
            self.assertIn("precision", entry)
            self.assertIn("input_count", entry)
            self.assertIn("output_count", entry)

    def test_clear_cache_resets_state(self):
        """clear_cache 清空缓存"""
        pruner = RecursiveRatchetPruner()
        candidates = [_make_candidate(f"t{i}", complexity=float(i + 1)) for i in range(5)]
        pruner.recursive_prune(candidates)

        pruner.clear_cache()

        self.assertEqual(pruner.best_candidates_cache, {})


class TestEnhancedRatchetPruner(unittest.TestCase):
    """测试真实的 EnhancedRatchetPruner（非 Mock）"""

    def test_enhanced_pruner_initialization(self):
        """测试增强型棘轮剪枝器初始化 — 真实字段"""
        pruner = EnhancedRatchetPruner(
            max_candidates_per_dimension=5,
            use_recursive=True,
            recursive_rounds=3,
        )
        # 真实字段（注意：是 max_candidates，非 max_candidates_per_dimension）
        self.assertEqual(pruner.max_candidates, 5)
        self.assertTrue(pruner.use_recursive)
        # 真实字段：recursive_pruner 是 RecursiveRatchetPruner 实例
        self.assertIsNotNone(pruner.recursive_pruner)
        self.assertIsInstance(pruner.recursive_pruner, RecursiveRatchetPruner)
        # 真实字段：dimension_winners
        self.assertEqual(pruner.dimension_winners, {})

    def test_enhanced_pruner_without_recursive(self):
        """use_recursive=False 时不创建 recursive_pruner"""
        pruner = EnhancedRatchetPruner(use_recursive=False)
        self.assertIsNone(pruner.recursive_pruner)

    def test_prune_candidates_basic(self):
        """prune_candidates — 真实方法签名"""
        pruner = EnhancedRatchetPruner(
            max_candidates_per_dimension=3, use_recursive=False  # 用基础剪枝便于控制
        )
        candidates = [
            _make_candidate(f"t{i}", complexity=1.0, validation_score=0.5 + i * 0.1)
            for i in range(5)
        ]

        result = pruner.prune_candidates("test_dim", candidates)

        # 真实返回：List[Candidate]
        self.assertIsInstance(result, list)
        self.assertLessEqual(len(result), 3)
        # 应按 validation_score 降序排列
        if len(result) >= 2:
            self.assertGreaterEqual(result[0].validation_score, result[1].validation_score)

    def test_prune_candidates_empty(self):
        """空候选列表 — 返回空列表"""
        pruner = EnhancedRatchetPruner()
        result = pruner.prune_candidates("dim", [])
        self.assertEqual(result, [])

    def test_prune_candidates_with_validation_fn(self):
        """prune_candidates 接受 validation_fn"""
        pruner = EnhancedRatchetPruner(
            max_candidates_per_dimension=2, use_recursive=False
        )
        candidates = [_make_candidate(f"t{i}", complexity=1.0) for i in range(4)]

        def validation_fn(c: Candidate):
            return {"functional_correctness": 0.8, "performance_baseline": 0.7}

        result = pruner.prune_candidates(
            "dim", candidates, validation_fn=validation_fn
        )

        self.assertLessEqual(len(result), 2)
        # 胜出者应记录到 dimension_winners
        self.assertIn("dim", pruner.dimension_winners)

    def test_get_dimension_winners(self):
        """get_dimension_winners 返回指定维度的胜出者"""
        pruner = EnhancedRatchetPruner(
            max_candidates_per_dimension=2, use_recursive=False
        )
        candidates = [_make_candidate(f"t{i}", complexity=1.0) for i in range(3)]
        pruner.prune_candidates("my_dim", candidates)

        winners = pruner.get_dimension_winners("my_dim")
        self.assertIsInstance(winners, list)
        self.assertLessEqual(len(winners), 2)

    def test_get_dimension_winners_unknown(self):
        """未知维度返回空列表"""
        pruner = EnhancedRatchetPruner()
        self.assertEqual(pruner.get_dimension_winners("nonexistent"), [])

    def test_clear_cache(self):
        """clear_cache 清空维度缓存"""
        pruner = EnhancedRatchetPruner(
            max_candidates_per_dimension=2, use_recursive=False
        )
        candidates = [_make_candidate(f"t{i}", complexity=1.0) for i in range(3)]
        pruner.prune_candidates("dim", candidates)
        self.assertIn("dim", pruner.dimension_winners)

        pruner.clear_cache()

        self.assertEqual(pruner.dimension_winners, {})


if __name__ == '__main__':
    unittest.main()
