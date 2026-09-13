"""Wave 1 评测标尺升级 — FitnessScore 与 LLMJudge 单元测试。

对齐 Hermes `core/fitness.py` 的判分纪律:
  composite = 0.5·correctness + 0.3·procedure_following + 0.2·conciseness − length_penalty
  长度惩罚:artifact_size/max_size > 0.9 后线性爬升,上限 0.3
  解析失败退回中性 0.5(不因模型抖动崩)
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.fitness import FitnessScore, LLMJudge, parse_score


class TestComposite:
    def test_weights_match_hermes(self):
        """composite 权重必须与 Hermes 数值一致(.5/.3/.2)。"""
        s = FitnessScore(correctness=1.0, procedure_following=1.0, conciseness=1.0)
        assert s.composite == pytest.approx(1.0)

    def test_weighted_mix(self):
        # 只满 correctness → 0.5
        s = FitnessScore(correctness=1.0, procedure_following=0.0, conciseness=0.0)
        assert s.composite == pytest.approx(0.5)
        # 只满 procedure → 0.3
        s = FitnessScore(correctness=0.0, procedure_following=1.0, conciseness=0.0)
        assert s.composite == pytest.approx(0.3)
        # 只满 conciseness → 0.2
        s = FitnessScore(correctness=0.0, procedure_following=0.0, conciseness=1.0)
        assert s.composite == pytest.approx(0.2)

    def test_length_penalty_subtracted(self):
        s = FitnessScore(correctness=1.0, procedure_following=1.0, conciseness=1.0, length_penalty=0.3)
        assert s.composite == pytest.approx(0.7)

    def test_composite_never_negative(self):
        s = FitnessScore(correctness=0.0, procedure_following=0.0, conciseness=0.0, length_penalty=0.3)
        assert s.composite == 0.0


class TestParseScore:
    def test_float_passthrough(self):
        assert parse_score(0.42) == pytest.approx(0.42)

    def test_numeric_string(self):
        assert parse_score("0.8") == pytest.approx(0.8)

    def test_clamped_to_unit_range(self):
        assert parse_score(1.7) == 1.0
        assert parse_score(-0.5) == 0.0

    def test_garbage_defaults_neutral(self):
        assert parse_score("high") == pytest.approx(0.5)
        assert parse_score(None) == pytest.approx(0.5)


def _judge_payload(correctness=0.9, procedure=0.8, conciseness=0.7, feedback="更简短"):
    return (
        "```json\n"
        "{\n"
        f'  "correctness": {correctness},\n'
        f'  "procedure_following": {procedure},\n'
        f'  "conciseness": {conciseness},\n'
        f'  "feedback": "{feedback}"\n'
        "}\n"
        "```"
    )


class TestLLMJudge:
    @pytest.mark.asyncio
    async def test_scores_from_llm_json(self):
        calls = []

        async def fake_call(messages, model):
            calls.append(messages)
            return {"success": True, "response": _judge_payload()}

        judge = LLMJudge(EvolutionConfig(), llm_call=fake_call)
        score = await judge.score(
            task_input="审查这段代码",
            expected_behavior="应指出 SQL 注入",
            output="发现第 42 行 SQL 注入",
            skill_text="审查技能正文",
        )
        assert score.correctness == pytest.approx(0.9)
        assert score.procedure_following == pytest.approx(0.8)
        assert score.conciseness == pytest.approx(0.7)
        assert score.feedback == "更简短"
        assert calls, "judge 必须实际调用 LLM"

    @pytest.mark.asyncio
    async def test_length_penalty_curve(self):
        async def fake_call(messages, model):
            return {"success": True, "response": _judge_payload()}

        judge = LLMJudge(EvolutionConfig(), llm_call=fake_call)
        # 低于 90% 无惩罚
        s = await judge.score(
            task_input="t", expected_behavior="e", output="o", skill_text="s",
            artifact_size=900, max_size=1000,
        )
        assert s.length_penalty == 0.0
        # 100% → (1.0-0.9)*3 = 0.3
        s = await judge.score(
            task_input="t", expected_behavior="e", output="o", skill_text="s",
            artifact_size=1000, max_size=1000,
        )
        assert s.length_penalty == pytest.approx(0.3)
        # 150% → 上限 0.3
        s = await judge.score(
            task_input="t", expected_behavior="e", output="o", skill_text="s",
            artifact_size=1500, max_size=1000,
        )
        assert s.length_penalty == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_llm_failure_returns_neutral(self):
        async def fake_call(messages, model):
            return {"success": False, "error": "rate limited"}

        judge = LLMJudge(EvolutionConfig(), llm_call=fake_call)
        score = await judge.score(
            task_input="t", expected_behavior="e", output="o", skill_text="s",
        )
        # 失败时中性 0.5,不抛异常、不因抖动崩
        assert score.correctness == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_unparseable_output_returns_neutral(self):
        async def fake_call(messages, model):
            return {"success": True, "response": "抱歉,我无法评分。"}

        judge = LLMJudge(EvolutionConfig(), llm_call=fake_call)
        score = await judge.score(
            task_input="t", expected_behavior="e", output="o", skill_text="s",
        )
        assert score.correctness == pytest.approx(0.5)
