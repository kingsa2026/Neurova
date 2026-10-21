"""judge 不可用时的确定性回退门：只认可用性，不伪造质量分。

回退产出的提案必须带人工复核标记，自动审批路径不得消费它。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


class _UnavailableJudge:
    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        return FitnessScore(
            correctness=0.5,
            procedure_following=0.5,
            conciseness=0.5,
            feedback="judge down",
            judge_available=False,
        )


class _UsabilityAgent:
    """基线输出为空；候选含 IMPROVED 时输出可用文本。"""

    async def run(self, *, skill_text, task_input):
        return "usable output" if "IMPROVED" in skill_text else ""


async def _mutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + " IMPROVED"


def _dataset() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input="t1", expected_behavior="r")],
        holdout=[EvalExample(task_input="h1", expected_behavior="r")],
    )


@pytest.mark.asyncio
async def test_judge_unavailable_falls_back_to_deterministic_gate():
    cfg = EvolutionConfig(
        iterations=1,
        judge_fallback="deterministic",
        anchor_floor_enabled=False,
        cost_rule_enabled=False,
    )
    runner = SkillEvolutionRunner(
        cfg, judge=_UnavailableJudge(), mutate=_mutate, agent=_UsabilityAgent()
    )

    result = await runner.run(
        baseline_text="BASE", artifact_type="skill", dataset=_dataset()
    )

    assert result.judge_available is False
    assert result.judge_fallback == "deterministic"
    assert not result.rejected, result.reject_reason
    assert "IMPROVED" in result.deployed_text
    assert result.holdout_after > result.holdout_before
    assert result.to_dict()["judge_fallback"] == "deterministic"


@pytest.mark.asyncio
async def test_fallback_off_preserves_judge_unavailable_rejection():
    cfg = EvolutionConfig(
        iterations=1,
        judge_fallback="off",
        anchor_floor_enabled=False,
        cost_rule_enabled=False,
    )
    runner = SkillEvolutionRunner(
        cfg, judge=_UnavailableJudge(), mutate=_mutate, agent=_UsabilityAgent()
    )

    result = await runner.run(
        baseline_text="BASE", artifact_type="skill", dataset=_dataset()
    )

    assert result.rejected
    assert result.reject_reason == "judge_unavailable"
    assert result.judge_fallback == ""


@pytest.mark.asyncio
async def test_fallback_proposal_requires_manual_review(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    from neurova.evolution.eval.service import SkillEvolutionService

    svc = SkillEvolutionService("agent", base_dir=tmp_path / "evo")
    baseline = "BASE SKILL TEXT " * 20
    result, proposal = await svc.evolve(
        skill_id="s1",
        skill_text=baseline,
        dataset=_dataset(),
        iterations=1,
        agent=_UsabilityAgent(),
        judge=_UnavailableJudge(),
        mutate=_mutate,
        config=EvolutionConfig(
            iterations=1,
            judge_fallback="deterministic",
            anchor_floor_enabled=False,
            cost_rule_enabled=False,
        ),
    )

    assert proposal is not None
    assert result.judge_fallback == "deterministic"
    assert proposal.judge_fallback == "deterministic"
    assert proposal.requires_manual_review is True

    # 自动审批通道不得消费回退提案；状态必须留在 pending。
    assert svc.decide(
        proposal.proposal_id, True, registry=None, approver="auto:evolution"
    ) is False
    pending = svc.list_proposals("pending")
    assert any(p["proposal_id"] == proposal.proposal_id for p in pending)
