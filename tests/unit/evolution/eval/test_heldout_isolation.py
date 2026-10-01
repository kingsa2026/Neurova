"""P0-2 holdout 防污染 — 真 held-out 报告集与判据隔离的红灯测试。

RRSI 对齐：接受/拒绝判据只用 selection 集（holdout/val/train），
heldout 集只做验收报告证据，永不参与判定、变异采样或早停——
杜绝搜索过程把它自适应拟合掉。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


def _ds_with_heldout() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
        heldout=[EvalExample(task_input=f"HELD{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_overfit_to_selection():
    """脚本判分器：基线恒 0.5；候选在 selection 集上 0.9、heldout 集上 0.1——
    典型的"判据集提升、干净集回退"过拟合形态。"""

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        if "IMPROVED" not in skill_text:
            c = 0.5
        elif task_input.startswith("HELD"):
            c = 0.1
        else:
            c = 0.9
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


async def _mutate_appends_improved(*, artifact_text, artifact_type, failures):
    return artifact_text + "\nIMPROVED"


class TestHeldoutIsolation:
    @pytest.mark.asyncio
    async def test_heldout_regression_does_not_reject(self):
        """selection 集提升、heldout 集大幅回退 → 不据此拒绝，但证据如实外露。"""
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_overfit_to_selection(),
            mutate=_mutate_appends_improved,
        )
        result = await runner.run(
            baseline_text=BASELINE, artifact_type="skill",
            dataset=_ds_with_heldout(), iterations=2,
        )
        assert not result.rejected  # 判据只看 selection 集
        assert result.deployed_text != result.baseline_text
        assert result.heldout_before == pytest.approx(0.5)
        assert result.heldout_after == pytest.approx(0.1)
        assert result.heldout_improvement == pytest.approx(-0.4)

    @pytest.mark.asyncio
    async def test_heldout_never_enters_tuning(self):
        """变异失败采样不含 heldout；heldout 仅在最终证据阶段各评 2 次
        （基线一次 + 部署文本一次），未进入逐轮评测循环。"""
        recorded_failures: list[str] = []
        judged: dict[str, int] = {}

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            judged[task_input] = judged.get(task_input, 0) + 1
            return FitnessScore(correctness=0.5, procedure_following=0.5,
                                conciseness=0.5, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            recorded_failures.extend(f.task_input for f in failures)
            return artifact_text + "\nIMPROVED"

        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=judge, mutate=mutate,
        )
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds_with_heldout(), iterations=2)
        assert all(not t.startswith("HELD") for t in recorded_failures)
        # 逐轮循环若碰 heldout，次数会随 iterations 增长；证据评测恰好 2 次
        assert all(v == 2 for k, v in judged.items() if k.startswith("HELD"))

    @pytest.mark.asyncio
    async def test_no_heldout_keeps_zero_fields(self):
        """无 heldout 集：三个报告字段保持 0，行为与旧版一致。"""
        ds = _ds_with_heldout()
        ds.heldout = []
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_overfit_to_selection(),
            mutate=_mutate_appends_improved,
        )
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=ds, iterations=1)
        assert result.heldout_before == 0.0
        assert result.heldout_after == 0.0
        assert result.heldout_improvement == 0.0


class TestDatasetHeldout:
    def test_all_examples_includes_heldout(self):
        ds = _ds_with_heldout()
        assert len(ds.all_examples) == 10

    def test_split_default_matches_legacy(self):
        examples = [EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(8)]
        ds = EvalDataset.split(examples)
        assert ds.heldout == []
        assert len(ds.train) == 4 and len(ds.val) == 2 and len(ds.holdout) == 2

    def test_split_carves_heldout_from_tail(self):
        examples = [EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(8)]
        ds = EvalDataset.split(examples, heldout_ratio=0.5)
        assert len(ds.train) == 4 and len(ds.val) == 2
        assert len(ds.holdout) == 1 and len(ds.heldout) == 1
        # 三集之和仍等于 n，无样本丢失
        assert len(ds.all_examples) == 8

    def test_carve_heldout_method(self):
        ds = _ds_with_heldout()
        carved = ds.carve_heldout(0.5)
        assert carved is not ds
        # 从 holdout（非既有 heldout）尾部划出：h1 进入 heldout，h0 留作判据
        assert [e.task_input for e in carved.holdout] == ["h0"]
        assert [e.task_input for e in carved.heldout] == ["h1"]
        # 原对象不被修改
        assert len(ds.holdout) == 2 and len(ds.heldout) == 2

    def test_carve_heldout_noop_guards(self):
        ds = _ds_with_heldout()
        assert ds.carve_heldout(0.0) is ds
        assert ds.carve_heldout(-0.5) is ds
        tiny = EvalDataset(holdout=[EvalExample(task_input="h", expected_behavior="r")])
        assert tiny.carve_heldout(0.5) is tiny  # holdout 不足 2 条不划

    def test_legacy_three_way_file_loads(self, tmp_path):
        """旧三键 jsonl 目录载入：heldout 为空，其余集合正确。"""
        ds = EvalDataset(
            train=[EvalExample(task_input="t", expected_behavior="r")],
            val=[EvalExample(task_input="v", expected_behavior="r")],
            holdout=[EvalExample(task_input="h", expected_behavior="r")],
        )
        ds.save(tmp_path)
        assert not (tmp_path / "heldout.jsonl").exists()  # 空 heldout 不落盘（字节兼容）
        loaded = EvalDataset.load(tmp_path)
        assert loaded.heldout == []
        assert len(loaded.train) == 1 and len(loaded.val) == 1 and len(loaded.holdout) == 1

    def test_four_way_round_trip(self, tmp_path):
        ds = _ds_with_heldout()
        ds.save(tmp_path)
        assert (tmp_path / "heldout.jsonl").exists()
        loaded = EvalDataset.load(tmp_path)
        assert [e.task_input for e in loaded.heldout] == ["HELD0", "HELD1"]

    def test_load_skips_malformed_heldout_lines(self, tmp_path):
        ds = _ds_with_heldout()
        ds.save(tmp_path)
        with open(tmp_path / "heldout.jsonl", "a", encoding="utf-8") as f:
            f.write("这行不是 JSON\n")
        loaded = EvalDataset.load(tmp_path)
        assert len(loaded.heldout) == 2


class TestServiceHeldout:
    async def _judge(self, *, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.9 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    @pytest.mark.asyncio
    async def test_proposal_carries_heldout_evidence(self, tmp_path, monkeypatch):
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")
        result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds_with_heldout(),
            agent=None, judge=self._judge, mutate=_mutate_appends_improved,
        )
        assert proposal is not None
        assert proposal.heldout_before == pytest.approx(result.heldout_before)
        assert proposal.heldout_after == pytest.approx(result.heldout_after)
        d = proposal.to_dict()
        assert "heldout_improvement" in d

    @pytest.mark.asyncio
    async def test_service_carves_heldout_when_ratio_set(self, tmp_path, monkeypatch):
        """heldout_ratio>0 且数据集无 heldout → service 从 holdout 尾部自动划出。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-y", base_dir=tmp_path / "evo")
        three_way = EvalDataset(
            train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
            val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
            holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        )
        cfg = EvolutionConfig(heldout_ratio=0.5)
        result, _ = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=three_way,
            agent=None, judge=self._judge, mutate=_mutate_appends_improved, config=cfg,
        )
        # heldout 被划出并评测（judge 基线 0.2）→ 证据字段非零
        assert result.heldout_before == pytest.approx(0.2)
        assert result.heldout_after == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_service_default_no_carve(self, tmp_path, monkeypatch):
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-z", base_dir=tmp_path / "evo")
        three_way = EvalDataset(
            train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
            holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        )
        result, _ = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=three_way,
            agent=None, judge=self._judge, mutate=_mutate_appends_improved,
        )
        assert result.heldout_before == 0.0  # 默认 heldout_ratio=0，不划不测
