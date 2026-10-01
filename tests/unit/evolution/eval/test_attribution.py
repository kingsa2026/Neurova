"""P2-10 predicted_affected 归因 — 假设质量元闭环的红灯测试。

候选的预测面 = 喂给变异器的失败任务集；评测后算 hit_rate（这些任务的
tune 分是否真上升）与未预测回归，patch 进台账并在历史提示段展示。
归因只进证据面，不改 accept/reject 判据。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.history_ledger import EvolutionLedger, attribution_hit_rate
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


def _ds() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(2)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(4)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


class TestHitRatePure:
    def test_full_hit(self):
        report = attribution_hit_rate(
            predicted=["v0", "v1"],
            base_scores={"v0": 0.2, "v1": 0.2, "v2": 0.2},
            cand_scores={"v0": 0.5, "v1": 0.4, "v2": 0.2},
        )
        assert report["hit_rate"] == pytest.approx(1.0)
        assert set(report["hits"]) == {"v0", "v1"}
        assert report["unpredicted_regressions"] == []

    def test_partial_hit_with_unpredicted_regression(self):
        report = attribution_hit_rate(
            predicted=["v0"],
            base_scores={"v0": 0.5, "v1": 0.5, "v2": 0.5},
            cand_scores={"v0": 0.5, "v1": 0.1, "v2": 0.2},
        )
        assert report["hit_rate"] == pytest.approx(0.0)
        assert report["hits"] == []
        assert set(report["unpredicted_regressions"]) == {"v1", "v2"}

    def test_empty_prediction_is_honest(self):
        report = attribution_hit_rate(predicted=[], base_scores={}, cand_scores={})
        assert report["hit_rate"] is None


class TestRunnerAttribution:
    async def _judge_by_gain(self, gain_map):
        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + gain_map.get(skill_text, 0.0)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        return judge

    @pytest.mark.asyncio
    async def test_runner_records_prediction_and_hit_rate(self, tmp_path):
        """单线路径：台账记录含 predicted_tasks，胜者被 patch attribution。"""
        ledger = EvolutionLedger(tmp_path / "history")
        candidates = iter(["第一版改进"])
        gain_map = {"第一版改进": 0.30}

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(candidates)

        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=await self._judge_by_gain(gain_map),
            mutate=mutate, ledger=ledger,
        )
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1, ledger_key="s1")
        assert not result.rejected
        records = ledger.tail("s1", 5)
        assert len(records) == 1
        rec = records[0]
        assert rec["predicted_tasks"], "失败任务集必须作为预测面入账"
        assert all(t.startswith("v") for t in rec["predicted_tasks"])  # val 失败任务
        assert rec["attribution"]["hit_rate"] == pytest.approx(1.0)
        assert rec["attribution"]["hits"], "候选在预测任务上全面上升"

    @pytest.mark.asyncio
    async def test_parallel_path_attribution(self, tmp_path):
        from neurova.evolution.eval.history_ledger import EvolutionLedger as L

        ledger = L(tmp_path / "history")
        produced = iter(["候选甲", "候选乙"])
        gain_map = {"候选甲": 0.10, "候选乙": 0.20}

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + gain_map.get(skill_text, 0.0)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=2), judge=judge, mutate=mutate,
            ledger=ledger,
        )
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1, ledger_key="s1")
        records = [r for r in ledger.tail("s1", 5) if r.get("predicted_tasks")]
        assert len(records) == 2  # 两个幸存候选各有归因
        assert all("attribution" in r for r in records)

    @pytest.mark.asyncio
    async def test_prompt_shows_hit_rate(self, tmp_path, monkeypatch):
        """历史含归因时，变异 prompt 展示命中率。"""
        captured: dict[str, str] = {}

        async def fake_call(self, messages, model):
            captured["user"] = messages[-1]["content"]
            return {"success": True, "response": "改进正文"}

        from neurova.evolution.eval import mutator as mutator_mod

        monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", fake_call)
        from neurova.evolution.eval.mutator import JudgeFailure, ReflectiveMutator

        ledger = EvolutionLedger(tmp_path)
        ledger.append("s1", {"hypothesis": "加重试逻辑", "accepted": False,
                             "reject_reason": "no_improvement",
                             "attribution": {"hit_rate": 1 / 3, "hits": ["v0"],
                                             "unpredicted_regressions": []}})
        history = ledger.recent("s1")
        mutator = ReflectiveMutator(EvolutionConfig())
        failures = [JudgeFailure(task_input="t", output="o", feedback="fb", score=0.1)]
        await mutator.mutate(artifact_text="正文", artifact_type="skill",
                             failures=failures, history=history)
        assert "命中率" in captured["user"]
