"""P1-5 文本臂成本规则 — 涨的成本必须由增益买单的红灯测试。

RRSI 对齐：ΔC ≤ β0 + β1·ΔS；文本臂成本代理 = 候选文本相对基线的
长度变化率（零 LLM、诚实、可复现）。增益越大容忍的成本预算越大；
"微增益 + 大膨胀"的候选被拒。cost_rule_enabled=False 完全跳过（逃生门）。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2
# 膨胀 ~70% 的填充段（远超微增益下的成本预算）
BLOAT = "这是用于拉高文本长度的填充说明内容。" * 18  # ≈ 540 字


def _ds() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_with_gain(gain: float):
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + gain if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


def _runner(gain: float, config: EvolutionConfig):
    async def mutate(*, artifact_text, artifact_type, failures):
        return artifact_text + "\nIMPROVED " + BLOAT

    return SkillEvolutionRunner(config, judge=_judge_with_gain(gain), mutate=mutate)


class TestCostRule:
    @pytest.mark.asyncio
    async def test_cost_overrun_rejected(self):
        """增益 0.011（预算 ≈0.59）配 70% 膨胀 → cost_rule_failed，回退基线。"""
        runner = _runner(0.011, EvolutionConfig())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert result.rejected
        assert result.reject_reason == "cost_rule_failed"
        assert result.deployed_text == BASELINE
        assert result.cost_change > 0.5  # 膨胀确实量出来了
        assert result.cost_baseline == len(BASELINE)
        assert result.cost_candidate == len(BASELINE) + len("\nIMPROVED " + BLOAT)

    @pytest.mark.asyncio
    async def test_justified_cost_passes(self):
        """增益 0.02（预算 ≈0.99）配预算内膨胀 → 通过，成本字段如实。"""
        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + 0.02 if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        padding = "补充说明。" * 5  # 增长 ≈51% < 预算 0.99
        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED " + padding

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert not result.rejected
        assert result.cost_change > 0.3
        assert result.cost_change <= EvolutionConfig().cost_beta0 + (
            EvolutionConfig().cost_beta1 * result.improvement) + 1e-9

    @pytest.mark.asyncio
    async def test_tiny_growth_passes_even_with_small_gain(self):
        """小文本变化配微增益：预算内，不误杀。"""
        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + 0.011 if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert not result.rejected

    @pytest.mark.asyncio
    async def test_disabled_keeps_legacy(self):
        """cost_rule_enabled=False：越界膨胀候选照旧放行（逃生门）。"""
        runner = _runner(0.011, EvolutionConfig(cost_rule_enabled=False))
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert not result.rejected
        assert result.cost_change == 0.0  # 关闭时不量不判

    def test_config_defaults(self):
        cfg = EvolutionConfig()
        assert cfg.cost_rule_enabled is True
        assert cfg.cost_beta0 == pytest.approx(0.10)
        assert cfg.cost_beta1 == pytest.approx(44.5)
