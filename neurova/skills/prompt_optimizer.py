"""PromptOptimizer — 评测集驱动的提示词优化（v2 重写）

对齐 agent-core 的做法（QP 对比启发 #6）：**小型评测集 + 变体打分驱动迭代**，
而非对提示词原文做关键词启发打分。

v1 的问题（自注"模拟评估逻辑，实际应该基于测试用例的预期输出"）：五个
_analyze_* 全是关键词计数启发，所谓打分没有真值基准——分数高≠提示词好。

v2 的评估语义：
- **PromptEvalCase**：声明式评测用例（required_elements 必须出现的要素 /
  forbidden_patterns 禁止出现的反模式 / max_length 长度上限）——像单元测试
  一样为"这个提示词应该长什么样"提供真值基准；
- **PromptEvalSet.score_prompt**：变体过一遍全部用例，得分 = 加权通过率（0..1）；
- **generate_variants**：确定性变体生成（补结构小节 / 角色声明 / 输出格式段 /
  约束段 / 去冗余）——生成侧保持零 LLM 规则实现；
- **optimize_prompt**：迭代循环——每轮生成变体、全量打分、保留最优，
  满分提前收敛。score_before/score_after 是真实通过率变化，不再是无基准噪声。

兼容说明：保留 OptimizationGoal/PromptAnalysis/OptimizedPrompt/
VariantTestResults 类名与 optimize_prompt/test_prompt_variants/analyze_prompt
入口形状（历史引用面 skills/auto_skill_improver.py）；PromptAnalysis 的四个
启发式分数字段废弃（恒 0，仅保留字段兼容）——真实信号在 eval set 通过率。
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


# ────── 评测集 ──────


@dataclass
class PromptEvalCase:
    """单条评测用例：为提示词声明一条可机械验证的真值。

    Attributes:
        case_id: 用例标识
        description: 人读说明（这条用例在检查什么）
        required_elements: 提示词中必须出现的子串（任一缺失即该用例失败）
        forbidden_patterns: 禁止出现的正则（任一命中即失败，如模糊指令/越权模式）
        max_length: 提示词最大长度（None 不限制）
        weight: 用例权重（默认 1）
    """

    case_id: str
    description: str
    required_elements: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    max_length: Optional[int] = None
    weight: float = 1.0


class PromptEvalSet:
    """提示词评测集：一组 PromptEvalCase + 确定性打分器。"""

    def __init__(self, cases: Optional[List[PromptEvalCase]] = None):
        self.cases = list(cases or [])

    def add_case(self, case: PromptEvalCase) -> None:
        self.cases.append(case)

    def score_prompt(self, prompt: str) -> Tuple[float, List[Dict[str, Any]]]:
        """提示词过全部用例，返回 (加权通过率 0..1, 逐用例明细)。"""
        if not self.cases:
            return 0.0, []
        total_weight = sum(c.weight for c in self.cases) or 1.0
        earned = 0.0
        details: List[Dict[str, Any]] = []
        for case in self.cases:
            passed, failures = self._check_case(prompt, case)
            if passed:
                earned += case.weight
            details.append(
                {
                    "case_id": case.case_id,
                    "description": case.description,
                    "passed": passed,
                    "failures": failures,
                }
            )
        return earned / total_weight, details

    @staticmethod
    def _check_case(prompt: str, case: PromptEvalCase) -> Tuple[bool, List[str]]:
        failures: List[str] = []
        for element in case.required_elements:
            if element not in prompt:
                failures.append(f"缺少要素: {element}")
        for pattern in case.forbidden_patterns:
            try:
                if re.search(pattern, prompt):
                    failures.append(f"命中禁止模式: {pattern}")
            except re.error:
                failures.append(f"非法正则（用例配置错误）: {pattern}")
        if case.max_length is not None and len(prompt) > case.max_length:
            failures.append(f"超长: {len(prompt)} > {case.max_length}")
        return not failures, failures


# ────── 变体生成（确定性规则；评估才是真值来源）──────

_STRUCTURE_SECTION = (
    "\n\n## 执行步骤\n"
    "1. 理解任务目标与输入。\n"
    "2. 按上述要求逐项处理。\n"
    "3. 输出前自查是否符合全部约束。"
)

_FORMAT_SECTION = (
    "\n\n## 输出格式\n"
    "以清晰的结构化文本回复：先给结论，再给依据；列表用短横线，代码用代码块。"
)

_CONSTRAINT_SECTION = (
    "\n\n## 约束\n"
    "- 不得编造事实；不确定时明确说明。\n"
    "- 不要输出与任务无关的内容。"
)

_ROLE_PREFIX = "你是一名严谨、专业的任务执行助手。\n\n"


def generate_variants(base_prompt: str) -> List[Tuple[str, str]]:
    """从基准提示词生成确定性变体，返回 [(variant_name, prompt_text), ...]。

    变体集是超集候选——哪个变体在评测集上得分最高由打分决定，
    生成器不做价值判断。
    """
    base = base_prompt.rstrip()
    return [
        ("base", base),
        ("with_role", _ROLE_PREFIX + base),
        ("with_structure", base + _STRUCTURE_SECTION),
        ("with_format", base + _FORMAT_SECTION),
        ("with_constraints", base + _CONSTRAINT_SECTION),
        ("role_structure_format", _ROLE_PREFIX + base + _STRUCTURE_SECTION + _FORMAT_SECTION),
        (
            "full",
            _ROLE_PREFIX + base + _STRUCTURE_SECTION + _FORMAT_SECTION + _CONSTRAINT_SECTION,
        ),
        ("tightened", re.sub(r"\n{3,}", "\n\n", base)),
    ]


# ────── 兼容数据类（字段保留，语义见类注释）──────


class OptimizationGoal:
    """优化目标（v2 中仅作元数据标记；方向由评测集驱动）"""

    CLARITY = "clarity"
    SPECIFICITY = "specificity"
    CONCISENESS = "conciseness"
    COMPLETENESS = "completeness"
    PERFORMANCE = "performance"
    SECURITY = "security"


@dataclass
class PromptAnalysis:
    """结构化分析结果（v2：启发式四分数已废弃恒 0，真实信号在 eval set）"""

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
    """优化结果：score_before/after 是评测集真实通过率"""

    success: bool = False
    original_prompt: str = ""
    optimized_prompt: str = ""
    improvements: List[str] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    optimization_type: str = OptimizationGoal.CLARITY
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VariantTestResults:
    """变体打分结果"""

    variants: List[str] = field(default_factory=list)
    variant_scores: List[float] = field(default_factory=list)
    best_variant_index: int = 0
    best_variant: str = ""
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    detailed_results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ────── 主类 ──────


class PromptOptimizer:
    """评测集驱动的提示词优化器。

    用法：
        eval_set = PromptEvalSet([
            PromptEvalCase(case_id="role", description="必须声明角色",
                           required_elements=["你是一名"]),
            ...
        ])
        result = await optimizer.optimize_prompt(base_prompt, eval_set)
        result.optimized_prompt  # 评测集通过率最高的变体
    """

    def __init__(self, llm_client: Optional[Any] = None):
        # llm_client 预留：接入执行回路后可加"输出质量"维度的 LLM 评审；
        # 当前评测核为确定性结构用例，不依赖 LLM。
        self.llm_client = llm_client

    async def optimize_prompt(
        self,
        prompt: str,
        eval_set: PromptEvalSet,
        rounds: int = 2,
        optimization_type: str = OptimizationGoal.CLARITY,
        **kwargs,
    ) -> OptimizedPrompt:
        """迭代优化：生成变体 → 评测集打分 → 保留最优；满分提前收敛。"""
        if not isinstance(eval_set, PromptEvalSet) or not eval_set.cases:
            return OptimizedPrompt(
                success=False,
                original_prompt=prompt,
                metadata={"error": "eval_set 为空——v2 优化必须有评测集基准"},
            )

        score_before, _ = eval_set.score_prompt(prompt)
        best_prompt, best_score = prompt, score_before
        improvements: List[str] = []
        history: List[Dict[str, Any]] = [{"round": 0, "best": best_score, "source": "base"}]

        for round_no in range(1, max(1, rounds) + 1):
            candidates = [
                (name, text)
                for name, text in generate_variants(best_prompt)
                if text != best_prompt
            ]
            if not candidates:
                break
            scored = [(name, text, eval_set.score_prompt(text)[0]) for name, text in candidates]
            round_best = max(scored, key=lambda x: x[2])
            history.append({"round": round_no, "best": round_best[2], "source": round_best[0]})
            if round_best[2] > best_score:
                improvements.append(round_best[0])
                best_prompt, best_score = round_best[1], round_best[2]
            if best_score >= 1.0:
                break  # 满分提前收敛

        return OptimizedPrompt(
            success=best_score > score_before,
            original_prompt=prompt,
            optimized_prompt=best_prompt,
            improvements=improvements,
            score_before=score_before,
            score_after=best_score,
            optimization_type=optimization_type,
            metadata={"rounds": history},
        )

    async def test_prompt_variants(
        self, variants: List[str], eval_set: PromptEvalSet
    ) -> VariantTestResults:
        """变体全量打分（评测集通过率），返回最优变体。"""
        scores: List[float] = []
        detailed: List[Dict[str, Any]] = []
        for i, variant in enumerate(variants):
            score, details = eval_set.score_prompt(variant)
            scores.append(score)
            detailed.append({"variant_index": i, "score": score, "cases": details})
        best_index = max(range(len(variants)), key=lambda i: scores[i]) if variants else 0
        return VariantTestResults(
            variants=list(variants),
            variant_scores=scores,
            best_variant_index=best_index,
            best_variant=variants[best_index] if variants else "",
            detailed_results=detailed,
            metadata={"scoring": "eval_set_pass_rate"},
        )

    async def analyze_prompt(
        self, prompt: str, skill_context: Optional[Dict[str, Any]] = None
    ) -> PromptAnalysis:
        """结构化分析：报告可评测的结构要素是否在位（诚实信号，非启发式打分）。

        历史引用兼容：PromptAnalysis 字段保留；真实质量评估请用
        optimize_prompt/test_prompt_variants + PromptEvalSet。
        """
        checks = {
            "role_declaration": "你是一名" in prompt or "你是" in prompt,
            "has_constraints": "约束" in prompt or "不得" in prompt,
            "has_output_format": "输出格式" in prompt or "格式" in prompt,
            "has_steps": "步骤" in prompt or "1." in prompt,
        }
        missing = [k for k, ok in checks.items() if not ok]
        return PromptAnalysis(
            overall_score=sum(1 for ok in checks.values() if ok) / len(checks),
            suggestions=[f"缺少结构要素: {k}" for k in missing],
            issues=missing,
            metadata={"structural_checks": checks},
        )
