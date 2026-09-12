"""PromptOptimizer v2 测试（QP 对齐启发 #6，2026-09-12）。

评测集驱动的提示词优化：声明式 PromptEvalCase 提供真值基准，
变体打分（加权通过率）驱动迭代——替代 v1 的关键词启发打分（无基准噪声）。
"""

import asyncio
import unittest

from neurova.skills.prompt_optimizer import (
    PromptEvalCase,
    PromptEvalSet,
    PromptOptimizer,
    generate_variants,
)


def _strict_eval_set():
    """要求角色声明 + 结构小节 + 约束 + 输出格式的评测集。"""
    return PromptEvalSet(
        [
            PromptEvalCase(
                case_id="role",
                description="必须声明角色",
                required_elements=["你是一名"],
            ),
            PromptEvalCase(
                case_id="structure",
                description="必须有执行步骤小节",
                required_elements=["## 执行步骤"],
            ),
            PromptEvalCase(
                case_id="constraints",
                description="必须有约束小节",
                required_elements=["## 约束"],
            ),
            PromptEvalCase(
                case_id="format",
                description="必须有输出格式小节",
                required_elements=["## 输出格式"],
            ),
            PromptEvalCase(
                case_id="no_placeholder",
                description="不得遗留占位符",
                forbidden_patterns=[r"\{[a-z_]+\}"],
            ),
        ]
    )


class EvalSetTest(unittest.TestCase):
    def test_score_prompt_pass_rate(self):
        eval_set = _strict_eval_set()
        score, details = eval_set.score_prompt("你是一名助手\n\n## 约束\n- 不编造\n\n## 输出格式\n- 结构化")
        # 缺结构小节 → 4/5
        self.assertAlmostEqual(score, 0.8)
        failed = [d for d in details if not d["passed"]]
        self.assertEqual(failed[0]["case_id"], "structure")

    def test_forbidden_pattern_fails_case(self):
        eval_set = PromptEvalSet(
            [PromptEvalCase(case_id="clean", description="无占位符", forbidden_patterns=[r"\{var\}"])]
        )
        score, _ = eval_set.score_prompt("包含 {var} 的提示词")
        self.assertEqual(score, 0.0)
        score2, _ = eval_set.score_prompt("干净提示词")
        self.assertEqual(score2, 1.0)

    def test_empty_eval_set_scores_zero(self):
        self.assertEqual(PromptEvalSet().score_prompt("anything")[0], 0.0)


class VariantGenerationTest(unittest.TestCase):
    def test_generate_variants_is_superset(self):
        variants = generate_variants("基础提示词")
        names = [n for n, _ in variants]
        self.assertIn("base", names)
        self.assertIn("full", names)
        self.assertTrue(all(text for _, text in variants))


class OptimizePromptTest(unittest.TestCase):
    def test_optimize_improves_pass_rate(self):
        optimizer = PromptOptimizer()
        result = asyncio.run(optimizer.optimize_prompt("处理用户请求", _strict_eval_set(), rounds=2))
        self.assertTrue(result.success)
        self.assertGreater(result.score_after, result.score_before)
        self.assertEqual(result.score_after, 1.0, "变体集含 full，两轮内应达满分")
        # 满分变体包含全部要素
        for element in ("你是一名", "## 执行步骤", "## 约束", "## 输出格式"):
            self.assertIn(element, result.optimized_prompt)

    def test_full_score_converges_early(self):
        optimizer = PromptOptimizer()
        result = asyncio.run(optimizer.optimize_prompt("原始提示词", _strict_eval_set(), rounds=5))
        rounds_used = result.metadata["rounds"]
        self.assertLessEqual(len(rounds_used), 3, "满分应提前收敛，不跑满轮数")

    def test_already_perfect_prompt_unchanged(self):
        optimizer = PromptOptimizer()
        perfect = "你是一名助手\n\n## 执行步骤\n1. 做\n\n## 约束\n- 不编造\n\n## 输出格式\n- 结构化"
        result = asyncio.run(optimizer.optimize_prompt(perfect, _strict_eval_set()))
        self.assertFalse(result.success, "已满分无需优化")
        self.assertEqual(result.optimized_prompt, perfect)

    def test_empty_eval_set_rejected(self):
        optimizer = PromptOptimizer()
        result = asyncio.run(optimizer.optimize_prompt("p", PromptEvalSet()))
        self.assertFalse(result.success)
        self.assertIn("eval_set", result.metadata.get("error", ""))


class TestPromptVariantsTest(unittest.TestCase):
    def test_variants_scored_and_ranked(self):
        optimizer = PromptOptimizer()
        variants = ["裸提示词", "你是一名助手\n\n## 约束\n- 不编造\n\n## 输出格式\n- 结构化\n\n## 执行步骤\n1. 做"]
        result = asyncio.run(optimizer.test_prompt_variants(variants, _strict_eval_set()))
        self.assertEqual(result.best_variant_index, 1)
        # 裸提示词仅过 no_placeholder 一例（1/5），完整变体满分——排序即真值
        self.assertLess(result.variant_scores[0], result.variant_scores[1])
        self.assertEqual(result.variant_scores[1], 1.0)
        self.assertEqual(result.metadata["scoring"], "eval_set_pass_rate")


class AnalyzeCompatTest(unittest.TestCase):
    def test_analyze_reports_structural_elements(self):
        optimizer = PromptOptimizer()
        analysis = asyncio.run(optimizer.analyze_prompt("裸提示词"))
        self.assertIn("role_declaration", analysis.issues)
        self.assertLess(analysis.overall_score, 1.0)


if __name__ == "__main__":
    unittest.main()
