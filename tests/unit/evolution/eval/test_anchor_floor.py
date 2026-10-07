"""P2-4 锚定地板 — 红灯先行的契约测试(2026-10-07,SkillGLoW 对比)。

旧语义只对比**当前**基线:若现役文本早已退化(低于无技能水平),候选"赢过
退化基线"仍被接受——增益被归因于退化。锚定地板:
    A = max(历史最优留出, 无技能基线)
    接受 ⇔ holdout_after ≥ A − accept_threshold
- 无技能锚:部署文本不许低于"不带技能"的水平(第一性下限);
- 历史最优锚:台账记录各次运行的绝对 holdout_after,退化后重新爬回旧高水平
  之前的"增益"不算(锚从台账自然预热,不造第二份历史账本)。
无技能留出只在候选**过基线门后**才评——成本有界(每通过轮 +1 次留出评测)。
"""

import json

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner

_BASELINE = "基线技能正文。" + "补充说明用于满足约束闸的基线长度。" * 2


def _judge():
    """分锚判分器:无技能臂 0.5 / 现役基线 0.3 / SLIGHT 候选 0.35 / STRONG 0.9。"""

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        if "STRONG" in skill_text:
            c = 0.9
        elif "SLIGHT" in skill_text:
            c = 0.35
        elif skill_text.strip():
            c = 0.3
        else:
            c = 0.5
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


def _ds() -> EvalDataset:
    ex = lambda i: EvalExample(task_input=f"t{i}", expected_behavior="行为判据")
    return EvalDataset(train=[ex(i) for i in range(4)],
                       val=[ex(10 + i) for i in range(2)],
                       holdout=[ex(20 + i) for i in range(2)])


def _runner(candidate: str, *, anchor_best=None, config=None, ledger=None):
    async def mutate(*, artifact_text, artifact_type, failures, **kw):
        return candidate

    return SkillEvolutionRunner(
        config or EvolutionConfig(), judge=_judge(), mutate=mutate, ledger=ledger)


class TestNoSkillAnchor:
    @pytest.mark.asyncio
    async def test_beating_degraded_baseline_is_not_enough(self):
        """候选只赢退化基线(0.3→0.35)但低于无技能臂(0.5)→ 拒绝 anchor_unreached。"""
        result = await _runner(_BASELINE + "\nSLIGHT 改进").run(
            baseline_text=_BASELINE, artifact_type="skill", dataset=_ds(), iterations=1)
        assert result.rejected
        assert result.reject_reason == "anchor_unreached"
        assert result.deployed_text == _BASELINE

    @pytest.mark.asyncio
    async def test_reaching_anchor_deploys_and_records(self):
        result = await _runner(_BASELINE + "\nSTRONG 改进").run(
            baseline_text=_BASELINE, artifact_type="skill", dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.deployed_text != _BASELINE
        assert result.anchor_no_skill == pytest.approx(0.5)
        assert result.anchor_floor == pytest.approx(0.5)
        assert result.anchor_evaluated is True

    @pytest.mark.asyncio
    async def test_no_skill_eval_not_counted_as_iteration(self):
        """无技能臂是度量不是候选:不得进 iterations_run。"""
        result = await _runner(_BASELINE + "\nSTRONG 改进").run(
            baseline_text=_BASELINE, artifact_type="skill", dataset=_ds(), iterations=1)
        assert result.iterations_run == 1


class TestBestSoFarAnchor:
    @pytest.mark.asyncio
    async def test_historic_best_blocks_regain_below_it(self):
        """历史最优 0.95:候选 0.9 只赢退化基线、未回旧高 → 拒绝。"""
        result = await _runner(_BASELINE + "\nSTRONG 改进").run(
            baseline_text=_BASELINE, artifact_type="skill", dataset=_ds(),
            iterations=1, anchor_best=0.95)
        assert result.rejected and result.reject_reason == "anchor_unreached"
        assert result.anchor_best == pytest.approx(0.95)
        assert result.anchor_floor == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_reaching_historic_best_deploys(self):
        result = await _runner(_BASELINE + "\nSTRONG 改进").run(
            baseline_text=_BASELINE, artifact_type="skill", dataset=_ds(),
            iterations=1, anchor_best=0.85)
        assert not result.rejected


class TestFlagOff:
    @pytest.mark.asyncio
    async def test_disabled_keeps_old_semantics(self):
        """关 = 只对比当前基线的旧语义,且不花无技能臂的评测预算。"""
        calls = []

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            calls.append(skill_text)
            c = 0.35 if "SLIGHT" in skill_text else (0.3 if skill_text.strip() else 0.5)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures, **kw):
            return _BASELINE + "\nSLIGHT 改进"

        runner = SkillEvolutionRunner(
            config=EvolutionConfig(anchor_floor_enabled=False),
            judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=_BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected and result.anchor_evaluated is False
        assert not any(c == "" for c in calls), "关锚不得花无技能臂评测"


class TestResultSurface:
    @pytest.mark.asyncio
    async def test_anchor_fields_in_to_dict(self):
        result = await _runner(_BASELINE + "\nSTRONG 改进").run(
            baseline_text=_BASELINE, artifact_type="skill", dataset=_ds(), iterations=1)
        payload = result.to_dict()
        assert payload["anchor_no_skill"] == pytest.approx(0.5)
        assert payload["anchor_floor"] == pytest.approx(0.5)
        assert payload["anchor_evaluated"] is True


class TestLedgerAbsolute:
    @pytest.mark.asyncio
    async def test_winning_run_records_absolute_holdout(self, tmp_path):
        """台账补记绝对留出分(锚的历史来源)——旧台账只有相对 delta。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path / "history")
        result = await _runner(_BASELINE + "\nSTRONG 改进", ledger=ledger).run(
            baseline_text=_BASELINE, artifact_type="skill",
            dataset=_ds(), iterations=1, ledger_key="sk1")
        assert not result.rejected
        entries = ledger.recent("sk1")
        assert entries, "胜者必须入账"
        assert any(isinstance(e.get("holdout_after"), (int, float)) for e in entries)

    def test_best_anchor_helper(self):
        from neurova.evolution.eval.service import best_anchor_from_ledger

        assert best_anchor_from_ledger([]) is None
        assert best_anchor_from_ledger([{"delta_holdout": -0.2}]) is None
        assert best_anchor_from_ledger([
            {"holdout_after": 0.4}, {"holdout_after": 0.9},
            {"holdout_after": "bad"},
        ]) == pytest.approx(0.9)
