"""Wave 2 — benchmark 回归门接线测试。

核心纪律:benchmark 是 GATE 不是 fitness——变体在留出集涨但 bench 回退
→ 拒绝,无论技能分多高。复用 rsi/eval_harness 作行为安全地板。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.runner import SkillEvolutionRunner


class _RegressedBench:
    """模拟 bench 回退:gain 恒为负。"""

    def evaluate(self, baseline_text, candidate_text):
        return -0.5


class _StableBench:
    def evaluate(self, baseline_text, candidate_text):
        return 0.0


class _ImprovedBench:
    def evaluate(self, baseline_text, candidate_text):
        return 0.2


class _Judge:
    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore
        c = 0.9 if "IMPROVED" in skill_text else 0.3
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")


class _Agent:
    async def run(self, *, skill_text, task_input):
        return skill_text


def _ds():
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
    )


class TestBenchmarkGate:
    @pytest.mark.asyncio
    async def test_bench_regression_rejects_even_with_skill_gain(self):
        """技能分涨但 bench 回退 → 拒绝(核心纪律)。"""
        cfg = EvolutionConfig(iterations=1, bench_tolerance=0.02)

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(
            cfg, judge=_Judge(), mutate=mutate, agent=_Agent(),
            bench_gate=_RegressedBench().evaluate,
        )
        result = await runner.run(baseline_text="BASE", artifact_type="skill", dataset=_ds())
        assert result.rejected
        assert result.reject_reason == "bench_regression"

    @pytest.mark.asyncio
    async def test_bench_stable_accepts(self):
        cfg = EvolutionConfig(iterations=1, bench_tolerance=0.02)

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(
            cfg, judge=_Judge(), mutate=mutate, agent=_Agent(),
            bench_gate=_StableBench().evaluate,
        )
        result = await runner.run(baseline_text="BASE", artifact_type="skill", dataset=_ds())
        assert not result.rejected

    @pytest.mark.asyncio
    async def test_no_bench_gate_skips_check(self):
        cfg = EvolutionConfig(iterations=1)

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(cfg, judge=_Judge(), mutate=mutate, agent=_Agent())
        result = await runner.run(baseline_text="BASE", artifact_type="skill", dataset=_ds())
        assert not result.rejected
