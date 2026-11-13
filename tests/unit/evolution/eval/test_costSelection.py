"""R1 成本升选择键 —— 红灯测试。

§10.2 R1：成本从「复核闸」升「选择键」。两件事：

1. **近平分成本 tiebreak**：多变体轮里，增益达线且彼此近平分的候选集中，
   选文本长度（文本臂成本代理，P1-5 同源）最小者——「同增益下选省的」。
   盲选（judge 偏好）优先级仍高于本 tiebreak；等长保持先到（既有钉子不破）。
2. **可配置成本硬门**：cost_hard_gate_enabled=True 时，候选臂执行成本相对
   基线臂涨幅超 cost_hard_gate_ratio ⇒ 直接拒绝（cost_gate_failed）；
   默认 False（软门形态不变：只强制人工复核）。
"""

import pytest

from neurova.evolution.eval import cost_ledger
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 4


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


def _patch_usage(monkeypatch, *, accelerate: float = 0.0):
    calls = {"n": 0}

    def fake_snapshot():
        calls["n"] += 1
        n = calls["n"]
        return {"tokens": int(10 * (n ** (1.0 + accelerate))),
                "cost_usd": 0.001 * (n ** (1.0 + accelerate))}

    monkeypatch.setattr(cost_ledger, "usageSnapshot", fake_snapshot)


class TestNearTieCostTiebreak:
    @pytest.mark.asyncio
    async def test_cheaper_near_tie_candidate_wins(self):
        """两个候选增益相同（近平分）、长度不同 ⇒ 选短的（成本代理）。
        长候选先到（argmax 先到序会选它）——tiebreak 翻转成短者才算生效。"""
        produced = iter(["IMPROVED 候选甲" + "长尾填充内容。" * 20, "IMPROVED 候选乙"])

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=2, noise_repeats=1),
            judge=_judge_with_gain(0.02), mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.deployed_text == "IMPROVED 候选乙"
        assert result.cost_tiebreak["state"] == "applied"
        assert result.cost_tiebreak["near_tie_count"] == 2

    @pytest.mark.asyncio
    async def test_clear_winner_not_overridden(self):
        """分数有实质差距 ⇒ 仍取最高分者，tiebreak 不适用。"""
        produced = iter(["IMPROVED 候选甲", "IMPROVED 候选乙" + "长尾填充内容。" * 20])

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + (0.09 if "乙" in skill_text else 0.02) if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=2, noise_repeats=1),
            judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.deployed_text.startswith("IMPROVED 候选乙")
        assert result.cost_tiebreak["state"] == "not_applicable"

    @pytest.mark.asyncio
    async def test_equal_length_keeps_first_arrival(self):
        """等长近平分 ⇒ 保持先到（既有确定性钉子的等价形态）。"""
        produced = iter(["IMPROVED 候选甲尾。", "IMPROVED 候选乙尾。"])

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=2, noise_repeats=1),
            judge=_judge_with_gain(0.02), mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.deployed_text == "IMPROVED 候选甲尾。"
        assert result.cost_tiebreak["state"] == "not_applicable"

    @pytest.mark.asyncio
    async def test_disabled_keeps_pure_argmax(self):
        """cost_tiebreak_enabled=False ⇒ 近平分回到先到 argmax。"""
        produced = iter(["IMPROVED 候选甲", "IMPROVED 候选乙" + "长尾填充内容。" * 20])

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=2, noise_repeats=1,
                            cost_tiebreak_enabled=False),
            judge=_judge_with_gain(0.02), mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.deployed_text == "IMPROVED 候选甲"  # 先到（恰好也是短的——按 argmax 先到序）
        assert result.cost_tiebreak["state"] == "disabled"


class TestCostHardGate:
    @pytest.mark.asyncio
    async def test_hard_gate_rejects_cost_surge(self, monkeypatch):
        """硬门开＋候选臂成本暴涨 ⇒ cost_gate_failed 拒绝（不再是仅人工复核）。"""
        _patch_usage(monkeypatch, accelerate=0.9)
        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1, exec_suite_enabled=False,
                            cost_hard_gate_enabled=True, cost_hard_gate_ratio=0.2),
            judge=_judge_with_gain(0.02), mutate=_echo_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.rejected
        assert result.reject_reason == "cost_gate_failed"
        assert result.deployed_text == BASELINE

    @pytest.mark.asyncio
    async def test_hard_gate_off_by_default(self, monkeypatch):
        """默认关：同样的成本暴涨只走软门（人工复核），不拒绝。"""
        _patch_usage(monkeypatch, accelerate=0.9)
        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1, exec_suite_enabled=False),
            judge=_judge_with_gain(0.02), mutate=_echo_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.cost_summary["state"] == "measured"

    @pytest.mark.asyncio
    async def test_hard_gate_tolerates_linear_cost(self, monkeypatch):
        """硬门开但成本线性（候选臂与基线臂同量级）⇒ 不误杀。"""
        _patch_usage(monkeypatch)
        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1, exec_suite_enabled=False,
                            cost_hard_gate_enabled=True, cost_hard_gate_ratio=0.2),
            judge=_judge_with_gain(0.02), mutate=_echo_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected


def _echo_mutate():
    async def mutate(*, artifact_text, artifact_type, failures):
        return artifact_text + " IMPROVED"
    return mutate
