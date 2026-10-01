"""P1-7a 多变体并行 + argmax — 单线试错升级并行搜索的红灯测试。

RRSI 对齐：每轮生成 m 个变异候选（不同失败子集采样），过闸后并行评测，
取 tune 分最高者为该轮 lineage（平分保持先到，确定性）。
variants_per_round=1（默认）时行为与旧版逐字节一致。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


def _ds(n_val: int = 6) -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(n_val)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_with_gain(gain: float):
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + gain if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


class TestMultiVariant:
    @pytest.mark.asyncio
    async def test_m_variants_evaluated_argmax_wins(self):
        """m=3 三个候选都被评测，胜者是指定最高分者。"""
        judged: dict[str, int] = {}

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            if skill_text in GAINS:
                judged[skill_text] = judged.get(skill_text, 0) + 1
            c = 0.2 + GAINS.get(skill_text, 0.0)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        GAINS = {"候选甲": 0.10, "候选乙": 0.30, "候选丙": 0.20}  # 乙最高
        produced = iter(["候选甲", "候选乙", "候选丙"])

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        cfg = EvolutionConfig(variants_per_round=3)
        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert set(judged) == {"候选甲", "候选乙", "候选丙"}
        assert result.deployed_text == "候选乙"
        assert not result.rejected
        assert result.candidates_evaluated == 3
        assert result.variants_per_round == 3

    @pytest.mark.asyncio
    async def test_variants_get_distinct_failure_shards(self):
        """各变异调用拿到不同的失败子集（轮转分片，不重复喂同一批）。"""
        captured: list[tuple] = []

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            # 基线在 val 上按任务序号衰减：6 条失败，严重度各不相同
            c = 0.9 if skill_text != BASELINE else max(0.05, 0.05 + 0.1 * int(task_input[1:]) % 7)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            captured.append(tuple(f.task_input for f in failures))
            return f"{artifact_text[:6]}-变体{len(captured)}"

        cfg = EvolutionConfig(variants_per_round=3)
        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate)
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1)
        assert len(captured) == 3
        all_inputs = [t for cap in captured for t in cap]
        assert len(set(all_inputs)) == len(all_inputs), "分片不得重叠"

    @pytest.mark.asyncio
    async def test_tie_keeps_first(self):
        """平分时保持先到者（确定性 argmax）。"""
        GAINS = {"候选甲": 0.10, "候选乙": 0.10}
        produced = iter(["候选甲", "候选乙"])

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + GAINS.get(skill_text, 0.0)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        cfg = EvolutionConfig(variants_per_round=2)
        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.deployed_text == "候选甲"

    @pytest.mark.asyncio
    async def test_all_gated_round_keeps_baseline(self):
        """m 个候选全被约束闸拒绝 → 无候选评测，基线保持。"""
        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.9
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\n超长尾巴" * 4000

        from neurova.evolution.eval.constraints import ConstraintValidator

        cfg = EvolutionConfig(variants_per_round=3)
        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate,
                                      constraints=ConstraintValidator(cfg))
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.deployed_text == BASELINE
        assert result.candidates_evaluated == 0
        assert result.iterations_run == 0

    @pytest.mark.asyncio
    async def test_default_single_variant_unchanged(self):
        """variants_per_round=1：每轮单变异、整批 top-3 失败——与旧版同形。"""
        captured: list[list] = []

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + 0.05 if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            captured.append([f.task_input for f in failures])
            return artifact_text + "\nIMPROVED"

        cfg = EvolutionConfig()
        assert cfg.variants_per_round == 1
        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=2)
        assert len(captured) == 2  # 每轮一次变异
        assert result.candidates_evaluated == 2
        assert result.variants_per_round == 1
        for failures in captured:
            assert len(failures) == 3  # 整批 top-3（旧 _MAX_FAILURES 契约）

    @pytest.mark.asyncio
    async def test_multi_variant_ledger_records_all(self, tmp_path):
        """并行路径的每个候选也入账；胜者 accepted=True。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        GAINS = {"候选甲": 0.10, "候选乙": 0.30, "候选丙": 0.20}
        produced = iter(["候选甲", "候选乙", "候选丙"])

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + GAINS.get(skill_text, 0.0)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        ledger = EvolutionLedger(tmp_path / "history")
        cfg = EvolutionConfig(variants_per_round=3)
        runner = SkillEvolutionRunner(cfg, judge=judge, mutate=mutate, ledger=ledger)
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1, ledger_key="s1")
        records = {r["hypothesis"]: r for r in ledger.tail("s1", 5)
                   if "hypothesis" in r and r["hypothesis"] in GAINS}
        # 台账 hypothesis 是失败反馈摘要……并行路径同 P1-4 契约：
        # 3 条记录、胜者 accepted=True
        records = ledger.tail("s1", 5)
        accepted = [r for r in records if r.get("accepted")]
        assert len(records) == 3
        assert len(accepted) == 1
