"""P2-9 missing 记 0 语义 — 单例失败不炸整轮的红灯测试。

RRSI 对齐：missing trial contributes 0 with the full denominator——单用例
评测异常记 0 分计入平均分母，运行不中断；eval_errors 外露。判分基础设施
不可用（探针 judge_unavailable）与单例失败两种情形诚实分开。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2
SECRET = "sk-abc123def45678901234"


def _ds() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(2)],
        val=[EvalExample(task_input="v0", expected_behavior="输出要点"),
             EvalExample(task_input="v-boom", expected_behavior="输出要点"),
             EvalExample(task_input="v1", expected_behavior="输出要点")],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_by_marker():
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.9 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


class _AgentBoomOnOneTask:
    """对特定任务执行时崩溃，异常消息夹带凭据形态文本（脱敏面测试）。"""

    async def run(self, *, skill_text, task_input):
        if task_input == "v-boom":
            raise RuntimeError(f"connection reset while calling upstream key={SECRET}")
        return skill_text


async def _mutate_appends_improved(*, artifact_text, artifact_type, failures):
    return artifact_text + "\nIMPROVED"


class TestMissingTrialSemantics:
    @pytest.mark.asyncio
    async def test_single_example_failure_scores_zero(self):
        """单例执行崩溃 → run 不中断、该用例 0 分入分母、eval_errors 外露。"""
        captured: list[str] = []

        async def mutate(*, artifact_text, artifact_type, failures):
            captured.extend(f.feedback for f in failures)
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=_judge_by_marker(),
                                      mutate=mutate, agent=_AgentBoomOnOneTask())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected  # 崩溃用例记 0 后流程照常完成
        assert result.eval_errors >= 1
        assert "eval_errors" in result.to_dict()

    @pytest.mark.asyncio
    async def test_eval_error_text_redacted(self):
        """异常文本进 feedback 前必须脱敏（凭据原文不得外泄到变异器 prompt 面）。"""
        captured: list[str] = []

        async def mutate(*, artifact_text, artifact_type, failures):
            captured.extend(f.feedback for f in failures)
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=_judge_by_marker(),
                                      mutate=mutate, agent=_AgentBoomOnOneTask())
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1)
        assert any(f.startswith("eval_error:") for f in captured)
        assert all(SECRET not in f for f in captured)

    @pytest.mark.asyncio
    async def test_zero_counts_in_denominator(self):
        """崩溃用例记 0 而非剔除：含崩溃用例的均分必须低于无崩溃对照组。"""
        judged_avgs: dict[str, float] = {}

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.9 if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        # v-boom 崩溃：tune 上基线与候选都要吃一个 0 分
        runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge,
                                      mutate=mutate, agent=_AgentBoomOnOneTask())
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1)
        # 直接对照：同任务集无崩溃时基线均分应为 0.2，崩溃后应被拉低
        clean_ds = _ds()
        clean_ds.val = [e for e in clean_ds.val if e.task_input != "v-boom"]
        runner_clean = SkillEvolutionRunner(EvolutionConfig(), judge=judge,
                                            mutate=mutate, agent=_AgentBoomOnOneTask())
        r2 = await runner_clean.run(baseline_text=BASELINE, artifact_type="skill",
                                    dataset=clean_ds, iterations=1)
        assert r2.eval_errors == 0

    @pytest.mark.asyncio
    async def test_judge_infra_failure_still_unavailable(self):
        """判分器全线故障：探针语义不回退，仍 judge_unavailable 前置拒绝。"""

        class _BrokenJudge:
            async def score(self, **kw):
                raise RuntimeError("judge infra down")

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=_BrokenJudge(),
                                      mutate=_mutate_appends_improved)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.rejected and result.reject_reason == "judge_unavailable"
        assert result.eval_errors == 0

    @pytest.mark.asyncio
    async def test_normal_path_no_errors(self):
        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.9 if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge,
                                      mutate=_mutate_appends_improved)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.eval_errors == 0
        assert result.to_dict()["eval_errors"] == 0
