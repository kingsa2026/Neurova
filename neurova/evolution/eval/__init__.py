"""文本级进化闭环 — 包入口。

可回滚、不破坏
现状"的工程闭环。Neurova 已有结构级进化(工具序列遗传 / RSI 参数棘轮);
本包补的是**文本级 + 有标尺**的闭环——技能正文 / 提示词 / 工具描述的变异与
留出集度量。

设计约束():
  - 不引入 DSPy:GEPA 的精华是"读失败 trace 做定向变异",用 llm_router 自研;
  - 默认关闭(NEUROVA_TEXT_EVOLUTION),对齐 C10 评审闸"进化产物默认待审";
  - 变体必须过约束闸 + benchmark 回归门 + 留出集对比,才产出提案。
"""

from neurova.evolution.eval.config import EvolutionConfig, text_evolution_enabled
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore, LLMJudge
from neurova.evolution.eval.mutator import JudgeFailure, ReflectiveMutator
from neurova.evolution.eval.runner import EvolutionRunResult, SkillEvolutionRunner

__all__ = [
    "EvolutionConfig",
    "text_evolution_enabled",
    "EvalDataset",
    "EvalExample",
    "FitnessScore",
    "LLMJudge",
    "JudgeFailure",
    "ReflectiveMutator",
    "EvolutionRunResult",
    "SkillEvolutionRunner",
]
