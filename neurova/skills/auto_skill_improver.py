"""
自动技能改进器 - Auto Skill Improver

功能:
1. 分析技能使用模式
2. 识别改进机会
3. 自动优化技能配置
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = get_logger(__name__)


@dataclass
class SkillImprovement:
    """技能改进建议"""

    skill_id: str
    improvement_type: str  # "performance", "accuracy", "coverage"
    description: str
    confidence: float = 0.0
    suggested_changes: Dict[str, Any] = field(default_factory=dict)


class AutoSkillImprover:
    """自动技能改进器"""

    def __init__(self):
        self.improvement_history: List[SkillImprovement] = []
        self.analysis_cache: Dict[str, Any] = {}
        logger.info("AutoSkillImprover initialized")

    def analyze_skill_performance(self, skill_id: str, metrics: Dict[str, Any]) -> List[SkillImprovement]:
        """分析技能性能并生成改进建议"""
        improvements = []

        # 分析成功率
        success_rate = metrics.get("success_rate", 0.0)
        if success_rate < 0.8:
            improvements.append(
                SkillImprovement(
                    skill_id=skill_id,
                    improvement_type="accuracy",
                    description=f"技能成功率较低 ({success_rate * 100:.1f}%%)，建议优化输入验证",
                    confidence=0.7,
                )
            )

        # 分析响应时间
        avg_response_time = metrics.get("avg_response_time", 0.0)
        if avg_response_time > 5.0:
            improvements.append(
                SkillImprovement(
                    skill_id=skill_id,
                    improvement_type="performance",
                    description=f"平均响应时间较长 ({avg_response_time:.1f}s)，建议优化执行逻辑",
                    confidence=0.6,
                )
            )

        self.improvement_history.extend(improvements)
        return improvements

    def get_improvement_suggestions(self, skill_id: str) -> List[SkillImprovement]:
        """获取技能的改进建议"""
        return [imp for imp in self.improvement_history if imp.skill_id == skill_id]

    def apply_improvement(self, improvement: SkillImprovement) -> bool:
        """应用改进建议"""
        # TODO: 实现自动应用改进的逻辑
        logger.info("Applying improvement for %s: %s", improvement.skill_id, improvement.description)
        return True

    def clear_history(self):
        """清除改进历史"""
        self.improvement_history.clear()
        self.analysis_cache.clear()

    async def optimize_skill_prompt(self, skill_id: str, current_prompt: str) -> "OptimizedPrompt":
        """
        优化技能提示词

        Args:
            skill_id: 技能 ID
            current_prompt: 当前提示词

        Returns:
            OptimizedPrompt: 优化结果
        """
        from .prompt_optimizer import OptimizationGoal, PromptOptimizer

        # 创建提示优化器
        optimizer = PromptOptimizer()

        # 分析当前提示词
        await optimizer.analyze_prompt(current_prompt)

        # 根据技能类型选择优化目标
        improvement_suggestions = self.get_improvement_suggestions(skill_id)

        # 确定优化目标
        optimization_goal = OptimizationGoal.CLARITY
        if improvement_suggestions:
            # 根据改进建议选择优化目标
            for suggestion in improvement_suggestions:
                if suggestion.improvement_type == "accuracy":
                    optimization_goal = OptimizationGoal.SPECIFICITY
                    break
                elif suggestion.improvement_type == "performance":
                    optimization_goal = OptimizationGoal.CONCISENESS
                    break

        # 优化提示词
        result = await optimizer.optimize_prompt(current_prompt, optimization_goal)

        # 记录优化历史
        if result.success:
            improvement = SkillImprovement(
                skill_id=skill_id,
                improvement_type="prompt_optimization",
                description=f"提示词优化完成，分数提升: {result.score_before:.2f} -> {result.score_after:.2f}",
                confidence=0.8,
                suggested_changes={
                    "original_prompt": current_prompt,
                    "optimized_prompt": result.optimized_prompt,
                    "improvements": result.improvements,
                },
            )
            self.improvement_history.append(improvement)

        return result

    async def generate_prompt_variants(self, base_prompt: str, num_variants: int = 5) -> List[str]:
        """
        生成提示词变体

        Args:
            base_prompt: 基础提示词
            num_variants: 变体数量

        Returns:
            List[str]: 提示词变体列表
        """
        variants = []

        # 变体生成策略
        strategies = [
            self._variant_add_specificity,
            self._variant_add_clarity,
            self._variant_add_examples,
            self._variant_simplify,
            self._variant_add_constraints,
        ]

        # 应用策略生成变体
        for i in range(num_variants):
            strategy = strategies[i % len(strategies)]
            variant = strategy(base_prompt)
            variants.append(variant)

        # 去重
        unique_variants = list(set(variants))

        # 确保数量
        while len(unique_variants) < num_variants:
            # 生成额外变体
            import hashlib

            # 基于哈希生成变体
            hash_suffix = hashlib.md5(f"{base_prompt}_{len(unique_variants)}".encode()).hexdigest()[:4]
            variant = f"{base_prompt} (变体 {hash_suffix})"
            unique_variants.append(variant)

        return unique_variants[:num_variants]

    async def run_prompt_ab_test(
        self, prompt_a: str, prompt_b: str, test_cases: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        运行 A/B 测试

        Args:
            prompt_a: 提示词 A
            prompt_b: 提示词 B
            test_cases: 测试用例列表

        Returns:
            Dict[str, Any]: 测试结果
        """
        from .prompt_optimizer import PromptOptimizer

        PromptOptimizer()

        # 测试提示词 A
        results_a = []
        for test_case in test_cases:
            # 模拟执行
            score_a = await self._evaluate_prompt_performance(prompt_a, test_case)
            results_a.append(score_a)

        # 测试提示词 B
        results_b = []
        for test_case in test_cases:
            score_b = await self._evaluate_prompt_performance(prompt_b, test_case)
            results_b.append(score_b)

        # 计算平均分数
        avg_a = sum(results_a) / len(results_a) if results_a else 0.0
        avg_b = sum(results_b) / len(results_b) if results_b else 0.0

        # 确定获胜者
        if avg_a > avg_b * 1.1:  # A 明显更好
            winner = "A"
            confidence = min(0.95, (avg_a - avg_b) / avg_b if avg_b > 0 else 0.8)
        elif avg_b > avg_a * 1.1:  # B 明显更好
            winner = "B"
            confidence = min(0.95, (avg_b - avg_a) / avg_a if avg_a > 0 else 0.8)
        else:
            winner = "tie"
            confidence = 0.5

        return {
            "winner": winner,
            "confidence": confidence,
            "score_a": avg_a,
            "score_b": avg_b,
            "test_case_count": len(test_cases),
            "results_a": results_a,
            "results_b": results_b,
            "improvement": abs(avg_a - avg_b) / max(avg_a, avg_b) if max(avg_a, avg_b) > 0 else 0.0,
        }

    def _variant_add_specificity(self, prompt: str) -> str:
        """添加具体性"""
        if "具体" not in prompt and "详细" not in prompt:
            return f"请详细描述：{prompt}"
        return prompt

    def _variant_add_clarity(self, prompt: str) -> str:
        """添加清晰度"""
        if not prompt.endswith(("。", "！", "？", ".", "!", "?")):
            return f"{prompt}。请明确执行步骤。"
        return prompt

    def _variant_add_examples(self, prompt: str) -> str:
        """添加示例"""
        if "例如" not in prompt and "比如" not in prompt:
            return f"{prompt}，例如：输入示例数据，输出处理结果。"
        return prompt

    def _variant_simplify(self, prompt: str) -> str:
        """简化表达"""
        # 移除冗余词
        redundant_words = ["请", "帮我", "能够", "可以"]
        simplified = prompt
        for word in redundant_words:
            if word in simplified and len(simplified) > 50:
                simplified = simplified.replace(word, "", 1)
                break
        return simplified

    def _variant_add_constraints(self, prompt: str) -> str:
        """添加约束"""
        if "必须" not in prompt and "需要" not in prompt:
            return f"{prompt}，必须确保结果准确。"
        return prompt

    async def _evaluate_prompt_performance(self, prompt: str, test_case: Dict[str, Any]) -> float:
        """评估提示词性能"""
        # 模拟评估逻辑
        # 实际应该调用技能执行并评估结果

        score = 0.0

        # 检查是否包含关键词
        input_text = test_case.get("input", "")
        expected_output = test_case.get("expected_output", "")

        if input_text in prompt:
            score += 0.3

        if expected_output in prompt:
            score += 0.3

        # 基于长度评分
        if 10 <= len(prompt) <= 200:
            score += 0.2

        # 基于结构评分
        if "。" in prompt or "！" in prompt or "？" in prompt:
            score += 0.2

        return min(1.0, score)
