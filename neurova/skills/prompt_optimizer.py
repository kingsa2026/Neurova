"""
提示优化器 (Prompt Optimizer)

优化技能提示词以提高性能和准确性。
实现 Meta-skill 的 prompt-optimizer 能力。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OptimizationGoal(Enum):
    """优化目标"""

    CLARITY = "clarity"
    SPECIFICITY = "specificity"
    CONCISENESS = "conciseness"
    COMPLETENESS = "completeness"
    PERFORMANCE = "performance"
    SECURITY = "security"


@dataclass
class PromptAnalysis:
    """提示词分析结果"""

    clarity_score: float = 0.0
    specificity_score: float = 0.0
    completeness_score: float = 0.0
    conciseness_score: float = 0.0
    overall_score: float = 0.0
    suggestions: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizedPrompt:
    """优化后的提示词"""

    success: bool = False
    original_prompt: str = ""
    optimized_prompt: str = ""
    improvements: List[str] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    optimization_type: OptimizationGoal = OptimizationGoal.CLARITY
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VariantTestResults:
    """变体测试结果"""

    variants: List[str] = field(default_factory=list)
    variant_scores: List[float] = field(default_factory=list)
    best_variant_index: int = 0
    best_variant: str = ""
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    detailed_results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PromptOptimizer:
    """
    提示优化器

    优化技能提示词以提高性能和准确性。
    实现 Meta-skill 的 prompt-optimizer 能力。
    """

    def __init__(self, llm_client=None):
        """
        初始化提示优化器

        Args:
            llm_client: LLM 客户端，用于提示词分析和生成
        """
        self.llm_client = llm_client
        self._optimization_history: Dict[str, OptimizedPrompt] = {}

        logger.info("PromptOptimizer 初始化完成")

    async def analyze_prompt(self, prompt: str, skill_context: Optional[Dict[str, Any]] = None) -> PromptAnalysis:
        """
        分析提示词

        Args:
            prompt: 提示词
            skill_context: 技能上下文

        Returns:
            PromptAnalysis: 分析结果
        """
        try:
            # 基础分析
            clarity_score = await self._analyze_clarity(prompt)
            specificity_score = await self._analyze_specificity(prompt, skill_context)
            completeness_score = await self._analyze_completeness(prompt, skill_context)
            conciseness_score = await self._analyze_conciseness(prompt)

            # 计算总体分数
            overall_score = (
                clarity_score * 0.3 + specificity_score * 0.25 + completeness_score * 0.25 + conciseness_score * 0.2
            )

            # 生成建议
            suggestions = await self._generate_suggestions(
                prompt, clarity_score, specificity_score, completeness_score, conciseness_score
            )

            # 识别问题
            issues = await self._identify_issues(prompt)

            return PromptAnalysis(
                clarity_score=clarity_score,
                specificity_score=specificity_score,
                completeness_score=completeness_score,
                conciseness_score=conciseness_score,
                overall_score=overall_score,
                suggestions=suggestions,
                issues=issues,
                metadata={
                    "prompt_length": len(prompt),
                    "word_count": len(prompt.split()),
                    "skill_context": skill_context,
                },
            )

        except Exception as e:
            logger.error("提示词分析失败: %s", e)
            return PromptAnalysis(metadata={"error": str(e)})

    async def optimize_prompt(
        self, prompt: str, optimization_goal: OptimizationGoal = OptimizationGoal.CLARITY
    ) -> OptimizedPrompt:
        """
        优化提示词

        Args:
            prompt: 原始提示词
            optimization_goal: 优化目标

        Returns:
            OptimizedPrompt: 优化结果
        """
        try:
            # 分析原始提示词
            analysis = await self.analyze_prompt(prompt)

            # 根据优化目标选择优化策略
            if optimization_goal == OptimizationGoal.CLARITY:
                optimized = await self._optimize_for_clarity(prompt, analysis)
            elif optimization_goal == OptimizationGoal.SPECIFICITY:
                optimized = await self._optimize_for_specificity(prompt, analysis)
            elif optimization_goal == OptimizationGoal.CONCISENESS:
                optimized = await self._optimize_for_conciseness(prompt, analysis)
            elif optimization_goal == OptimizationGoal.COMPLETENESS:
                optimized = await self._optimize_for_completeness(prompt, analysis)
            elif optimization_goal == OptimizationGoal.PERFORMANCE:
                optimized = await self._optimize_for_performance(prompt, analysis)
            elif optimization_goal == OptimizationGoal.SECURITY:
                optimized = await self._optimize_for_security(prompt, analysis)
            else:
                optimized = await self._optimize_for_clarity(prompt, analysis)

            # 分析优化后的提示词
            optimized_analysis = await self.analyze_prompt(optimized)

            # 记录改进点
            improvements = await self._identify_improvements(prompt, optimized, analysis, optimized_analysis)

            result = OptimizedPrompt(
                success=True,
                original_prompt=prompt,
                optimized_prompt=optimized,
                improvements=improvements,
                score_before=analysis.overall_score,
                score_after=optimized_analysis.overall_score,
                optimization_type=optimization_goal,
                metadata={
                    "improvement_count": len(improvements),
                    "score_improvement": optimized_analysis.overall_score - analysis.overall_score,
                },
            )

            # 记录优化历史
            history_key = f"{prompt[:50]}_{optimization_goal.value}"
            self._optimization_history[history_key] = result

            logger.info(
                f"提示词优化成功，分数提升: {analysis.overall_score:.2f} -> {optimized_analysis.overall_score:.2f}"
            )
            return result

        except Exception as e:
            logger.error("提示词优化失败: %s", e)
            return OptimizedPrompt(success=False, original_prompt=prompt, optimized_prompt=prompt, error=str(e))

    async def test_prompt_variants(self, variants: List[str], test_cases: List[Dict[str, Any]]) -> VariantTestResults:
        """
        测试提示词变体

        Args:
            variants: 提示词变体列表
            test_cases: 测试用例列表

        Returns:
            VariantTestResults: 测试结果
        """
        try:
            variant_scores = []
            detailed_results = []

            # 测试每个变体
            for i, variant in enumerate(variants):
                variant_result = await self._test_single_variant(variant, test_cases)
                variant_scores.append(variant_result["score"])
                detailed_results.append(variant_result)

                logger.debug("变体 %s 分数: %.2f", i+1, variant_result['score'])

            # 找出最佳变体
            best_index = variant_scores.index(max(variant_scores))
            best_variant = variants[best_index]

            result = VariantTestResults(
                variants=variants,
                variant_scores=variant_scores,
                best_variant_index=best_index,
                best_variant=best_variant,
                test_cases=test_cases,
                detailed_results=detailed_results,
                metadata={
                    "variant_count": len(variants),
                    "test_case_count": len(test_cases),
                    "score_range": {
                        "min": min(variant_scores),
                        "max": max(variant_scores),
                        "avg": sum(variant_scores) / len(variant_scores),
                    },
                },
            )

            logger.info("提示词变体测试完成，最佳变体索引: %s", best_index)
            return result

        except Exception as e:
            logger.error("提示词变体测试失败: %s", e)
            return VariantTestResults(variants=variants, metadata={"error": str(e)})

    async def _analyze_clarity(self, prompt: str) -> float:
        """分析清晰度"""
        score = 0.0

        # 检查句子结构
        sentences = prompt.split(".")
        if len(sentences) > 1:
            score += 0.2

        # 检查是否有明确指令
        instruction_keywords = ["请", "帮我", "执行", "运行", "生成", "创建", "搜索", "查找"]
        for keyword in instruction_keywords:
            if keyword in prompt:
                score += 0.1
                break

        # 检查是否有明确对象
        object_keywords = ["文件", "数据", "信息", "内容", "结果", "代码"]
        for keyword in object_keywords:
            if keyword in prompt:
                score += 0.1
                break

        # 检查长度适中
        if 10 <= len(prompt) <= 200:
            score += 0.2

        # 检查是否有歧义词
        ambiguous_words = ["东西", "什么", "一些", "某些", "可能"]
        for word in ambiguous_words:
            if word in prompt:
                score -= 0.1

        return max(0.0, min(1.0, score + 0.4))  # 基础分 0.4

    async def _analyze_specificity(self, prompt: str, skill_context: Optional[Dict[str, Any]] = None) -> float:
        """分析具体性"""
        score = 0.0

        # 检查是否有具体参数
        if skill_context:
            score += 0.2

        # 检查是否有数字
        import re

        numbers = re.findall(r"\d+", prompt)
        if numbers:
            score += 0.2

        # 检查是否有特定名词
        specific_terms = ["Python", "JavaScript", "JSON", "API", "HTTP", "数据库"]
        for term in specific_terms:
            if term.lower() in prompt.lower():
                score += 0.1
                break

        # 检查是否有格式要求
        format_terms = ["格式", "样式", "模板", "结构"]
        for term in format_terms:
            if term in prompt:
                score += 0.1
                break

        return max(0.0, min(1.0, score + 0.3))  # 基础分 0.3

    async def _analyze_completeness(self, prompt: str, skill_context: Optional[Dict[str, Any]] = None) -> float:
        """分析完整性"""
        score = 0.0

        # 检查是否有输入描述
        input_keywords = ["输入", "提供", "给定", "已知"]
        for keyword in input_keywords:
            if keyword in prompt:
                score += 0.2
                break

        # 检查是否有输出描述
        output_keywords = ["输出", "返回", "得到", "生成"]
        for keyword in output_keywords:
            if keyword in prompt:
                score += 0.2
                break

        # 检查是否有约束条件
        constraint_keywords = ["必须", "需要", "要求", "限制", "约束"]
        for keyword in constraint_keywords:
            if keyword in prompt:
                score += 0.2
                break

        # 检查是否有示例
        example_keywords = ["例如", "比如", "示例", "例子"]
        for keyword in example_keywords:
            if keyword in prompt:
                score += 0.2
                break

        return max(0.0, min(1.0, score + 0.2))  # 基础分 0.2

    async def _analyze_conciseness(self, prompt: str) -> float:
        """分析简洁性"""
        score = 0.0

        # 检查长度
        length = len(prompt)
        if length < 50:
            score += 0.4
        elif length < 100:
            score += 0.3
        elif length < 200:
            score += 0.2
        else:
            score += 0.1

        # 检查是否有冗余词
        redundant_words = ["的", "了", "在", "是", "有", "和", "与"]
        redundant_count = sum(1 for word in redundant_words if word in prompt)
        if redundant_count <= 3:
            score += 0.3
        elif redundant_count <= 5:
            score += 0.2
        else:
            score += 0.1

        # 检查句子数量
        sentences = [s.strip() for s in prompt.split(".") if s.strip()]
        if len(sentences) <= 3:
            score += 0.3
        elif len(sentences) <= 5:
            score += 0.2
        else:
            score += 0.1

        return max(0.0, min(1.0, score))

    async def _generate_suggestions(
        self, prompt: str, clarity: float, specificity: float, completeness: float, conciseness: float
    ) -> List[str]:
        """生成改进建议"""
        suggestions = []

        if clarity < 0.6:
            suggestions.append("建议使用更清晰的指令，避免歧义")

        if specificity < 0.6:
            suggestions.append("建议添加具体参数或约束条件")

        if completeness < 0.6:
            suggestions.append("建议明确输入输出要求和约束条件")

        if conciseness < 0.6:
            suggestions.append("建议精简语言，去除冗余表达")

        # 通用建议
        if len(prompt) > 300:
            suggestions.append("提示词过长，建议控制在200字以内")

        if not any(char in prompt for char in ["?", "？", "!", "！"]):
            suggestions.append("建议添加明确的指令或问题")

        return suggestions

    async def _identify_issues(self, prompt: str) -> List[str]:
        """识别问题"""
        issues = []

        # 检查常见问题
        if len(prompt.strip()) == 0:
            issues.append("提示词为空")

        if len(prompt) > 1000:
            issues.append("提示词过长，可能影响性能")

        # 检查敏感词
        sensitive_words = ["密码", "password", "secret", "key", "token"]
        for word in sensitive_words:
            if word.lower() in prompt.lower():
                issues.append(f"提示词包含敏感词: {word}")

        return issues

    async def _optimize_for_clarity(self, prompt: str, analysis: PromptAnalysis) -> str:
        """为清晰度优化"""
        optimized = prompt

        # 添加明确指令
        if not any(keyword in prompt for keyword in ["请", "帮我", "执行"]):
            optimized = f"请{optimized}"

        # 添加句号
        if not optimized.endswith(("。", "！", "？", ".", "!", "?")):
            optimized += "。"

        return optimized

    async def _optimize_for_specificity(self, prompt: str, analysis: PromptAnalysis) -> str:
        """为具体性优化"""
        optimized = prompt

        # 添加具体参数提示
        if "文件" in prompt and "路径" not in prompt:
            optimized += "，请指定文件路径"

        if "数据" in prompt and "格式" not in prompt:
            optimized += "，请指定数据格式"

        return optimized

    async def _optimize_for_conciseness(self, prompt: str, analysis: PromptAnalysis) -> str:
        """为简洁性优化"""
        # 移除冗余词
        redundant_patterns = [
            ("的的", "的"),
            ("了了", "了"),
            ("在在", "在"),
            ("是是", "是"),
        ]

        optimized = prompt
        for pattern, replacement in redundant_patterns:
            optimized = optimized.replace(pattern, replacement)

        return optimized

    async def _optimize_for_completeness(self, prompt: str, analysis: PromptAnalysis) -> str:
        """为完整性优化"""
        optimized = prompt

        # 添加输入输出描述
        if "输入" not in prompt and "输出" not in prompt:
            optimized += "。输入数据格式为字典，输出结果也为字典"

        return optimized

    async def _optimize_for_performance(self, prompt: str, analysis: PromptAnalysis) -> str:
        """为性能优化"""
        # 性能优化通常涉及代码层面，这里只是提示词优化
        return prompt

    async def _optimize_for_security(self, prompt: str, analysis: PromptAnalysis) -> str:
        """为安全性优化"""
        optimized = prompt

        # 添加安全约束
        if "安全" not in prompt:
            optimized += "。请确保操作安全，避免执行危险命令"

        return optimized

    async def _identify_improvements(
        self, original: str, optimized: str, original_analysis: PromptAnalysis, optimized_analysis: PromptAnalysis
    ) -> List[str]:
        """识别改进点"""
        improvements = []

        if optimized_analysis.clarity_score > original_analysis.clarity_score:
            improvements.append("提高了指令清晰度")

        if optimized_analysis.specificity_score > original_analysis.specificity_score:
            improvements.append("增加了具体性")

        if optimized_analysis.completeness_score > original_analysis.completeness_score:
            improvements.append("补充了完整性")

        if optimized_analysis.conciseness_score > original_analysis.conciseness_score:
            improvements.append("优化了简洁性")

        if len(optimized) > len(original):
            improvements.append("添加了必要信息")
        elif len(optimized) < len(original):
            improvements.append("精简了表达")

        return improvements

    async def _test_single_variant(self, variant: str, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """测试单个变体"""
        scores = []

        for test_case in test_cases:
            # 模拟测试执行
            # 实际应该调用技能执行
            score = await self._evaluate_variant(variant, test_case)
            scores.append(score)

        avg_score = sum(scores) / len(scores) if scores else 0.0

        return {"variant": variant, "score": avg_score, "test_scores": scores, "test_case_count": len(test_cases)}

    async def _evaluate_variant(self, variant: str, test_case: Dict[str, Any]) -> float:
        """评估变体"""
        # 模拟评估逻辑
        # 实际应该基于测试用例的预期输出

        score = 0.0

        # 检查是否包含关键词
        input_text = test_case.get("input", "")
        expected_output = test_case.get("expected_output", "")

        if input_text in variant:
            score += 0.3

        if expected_output in variant:
            score += 0.3

        # 基于长度评分
        if 10 <= len(variant) <= 200:
            score += 0.2

        # 基于结构评分
        if "。" in variant or "！" in variant or "？" in variant:
            score += 0.2

        return min(1.0, score)
