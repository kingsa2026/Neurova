"""Wave 1 核心断言 — 留出集防过拟合。

本波的核心纪律:变体必须在**留出集**上对比基线,而不是在原集上选最优。
构造一个"原集涨、留出集跌"的过拟合变体,runner 必须拒绝它。

这条测试先红后绿即证明闭环真的在度量,而非自欺(对齐 rsi/eval_harness
已确立的"行为安全地板"哲学)。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.runner import SkillEvolutionRunner


def _ds():
    """训练集里全是 A 类任务,留出集里全是 B 类任务。"""
    return EvalDataset(
        train=[EvalExample(task_input=f"A-{i}", expected_behavior="rubric A") for i in range(6)],
        val=[EvalExample(task_input=f"A-val-{i}", expected_behavior="rubric A") for i in range(3)],
        holdout=[EvalExample(task_input=f"B-{i}", expected_behavior="rubric B") for i in range(3)],
    )


class _ScriptedJudge:
    """判分器:变体文本里含 'OVERFIT' 则 A 类满分、B 类零分;否则反之。"""

    def __init__(self):
        self.seen = []

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        self.seen.append((task_input, skill_text))
        is_overfit = "OVERFIT" in (output or "")
        is_a = task_input.startswith("A")
        if is_overfit:
            c = 1.0 if is_a else 0.0
        else:
            c = 0.0 if is_a else 1.0
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")


class _GenerationJudge:
    """把某个变体(A 类过拟合)判为原集最优,B 类留出集最差。"""

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        # 任务输出 = skill_text(agent 按技能执行)→ 由技能文本决定符合哪类
        is_a = task_input.startswith("A")
        if "OVERFIT" in skill_text:
            c = 1.0 if is_a else 0.0
        else:
            c = 0.5 if is_a else 0.5
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")


class _Agent:
    """模拟执行:agent 的输出直接把技能文本回显(便于脚本化判分)。"""

    async def run(self, *, skill_text, task_input):
        return skill_text


class TestRunnerHoldout:
    @pytest.mark.asyncio
    async def test_overfit_variant_rejected(self):
        """原集涨、留出集跌的变体必须被拒绝。"""
        cfg = EvolutionConfig(iterations=2, min_improvement=0.0)

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nOVERFIT"

        runner = SkillEvolutionRunner(
            cfg, judge=_GenerationJudge(), mutate=mutate, agent=_Agent(),
        )
        result = await runner.run(
            baseline_text="BASE", artifact_type="skill", dataset=_ds(),
        )
        assert result.rejected, "过拟合变体必须被拒绝"
        assert result.reject_reason == "holdout_regression"
        assert result.deployed_text == "BASE", "拒绝后必须保留基线"

    @pytest.mark.asyncio
    async def test_genuine_improvement_accepted(self):
        """在留出集也变好的变体必须被接受。"""
        cfg = EvolutionConfig(iterations=2, min_improvement=0.0)

        async def mutate(*, artifact_text, artifact_type, failures):
            # 这个变体对 A、B 两类都更好(不区分任务类型)
            return artifact_text + "\nIMPROVED"

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            from neurova.evolution.eval.fitness import FitnessScore
            c = 0.9 if "IMPROVED" in skill_text else 0.3
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate, agent=_Agent())
        result = await runner.run(
            baseline_text="BASE", artifact_type="skill", dataset=_ds(),
        )
        assert not result.rejected
        assert result.deployed_text != "BASE"
        assert result.holdout_after > result.holdout_before

    @pytest.mark.asyncio
    async def test_no_improvement_keeps_baseline(self):
        cfg = EvolutionConfig(iterations=2, min_improvement=0.0)

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text  # 无变化

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            from neurova.evolution.eval.fitness import FitnessScore
            return FitnessScore(correctness=0.5, procedure_following=0.5, conciseness=0.5, feedback="")

        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate, agent=_Agent())
        result = await runner.run(
            baseline_text="BASE", artifact_type="skill", dataset=_ds(),
        )
        assert result.deployed_text == "BASE"

    @pytest.mark.asyncio
    async def test_result_reports_before_after_scores(self):
        cfg = EvolutionConfig(iterations=1, min_improvement=0.0)

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            from neurova.evolution.eval.fitness import FitnessScore
            c = 0.9 if "IMPROVED" in skill_text else 0.3
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate, agent=_Agent())
        result = await runner.run(
            baseline_text="BASE", artifact_type="skill", dataset=_ds(),
        )
        assert 0.0 <= result.holdout_before <= 1.0
        assert 0.0 <= result.holdout_after <= 1.0
        assert result.iterations_run >= 1

    @pytest.mark.asyncio
    async def test_empty_dataset_returns_error(self):
        cfg = EvolutionConfig(iterations=1)
        runner = SkillEvolutionRunner(
            cfg, judge=_GenerationJudge(), mutate=lambda **k: None, agent=_Agent(),
        )
        result = await runner.run(
            baseline_text="BASE", artifact_type="skill", dataset=EvalDataset(),
        )
        assert result.rejected
        assert result.reject_reason == "empty_dataset"
