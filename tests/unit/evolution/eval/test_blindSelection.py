"""N7：匿名盲选只读产物，且在近平分时作为审批读数返回。"""

from types import SimpleNamespace

import pytest

from neurova.evolution.eval.blind_selection import blind_ab
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample


def _examples():
    return [
        SimpleNamespace(task_input="t1"),
        SimpleNamespace(task_input="t2"),
    ]


class _PickContentJudge:
    """按 A/B 块内容选优：包含 CAND 的那一份胜出。"""

    def __init__(self):
        self.config = SimpleNamespace(judge_model="judge")

    async def _call_llm(self, messages, model):
        prompt = messages[-1]["content"]
        a_block = prompt.split("【A】", 1)[1].split("【B】", 1)[0]
        return {"success": True, "response": '{"choice": "A"}' if "CAND" in a_block else '{"choice": "B"}'}


@pytest.mark.asyncio
async def test_blind_ab_prefers_candidate_by_content():
    verdict = await blind_ab(
        judge=_PickContentJudge(),
        examples=_examples(),
        baseline_outputs=["BASE-1", "BASE-2"],
        candidate_outputs=["CAND-1", "CAND-2"],
    )
    assert verdict["state"] == "measured"
    assert verdict["preferred"] == "candidate"
    assert verdict["candidate_wins"] == 2
    assert verdict["baseline_wins"] == 0


@pytest.mark.asyncio
async def test_blind_ab_is_unavailable_without_selector_or_parse():
    verdict = await blind_ab(
        judge=lambda **kwargs: None,
        examples=_examples(),
        baseline_outputs=["B", "B"],
        candidate_outputs=["C", "C"],
    )
    assert verdict["state"] == "unavailable"

    class _Garbage:
        def __init__(self):
            self.config = SimpleNamespace(judge_model="judge")

        async def _call_llm(self, messages, model):
            return {"success": True, "response": "not a choice"}

    verdict = await blind_ab(
        judge=_Garbage(),
        examples=_examples(),
        baseline_outputs=["B", "B"],
        candidate_outputs=["C", "C"],
    )
    assert verdict["state"] == "unavailable"
    assert verdict["unparsed"] == 2


@pytest.mark.asyncio
async def test_ab_compare_near_tie_returns_blind_readout(tmp_path):
    from neurova.evolution.eval.service import SkillEvolutionService

    class _Agent:
        async def run(self, *, skill_text, task_input):
            return f"{skill_text}::{task_input}"

    class _Judge(_PickContentJudge):
        async def score(self, **kwargs):
            return 0.5

    items = [EvalExample(task_input=f"t{i}", expected_behavior="ok") for i in range(2)]
    dataset = EvalDataset(train=list(items), val=[], holdout=list(items), heldout=list(items))
    svc = SkillEvolutionService("blind-agent", base_dir=tmp_path / "evo")

    report = await svc.ab_compare(
        baseline_text="BASE",
        candidate_text="CAND",
        dataset=dataset,
        config=EvolutionConfig(),
        agent=_Agent(),
        judge=_Judge(),
    )

    assert report["delta"] == 0.0
    assert report["blind"]["state"] == "measured"
    assert report["blind"]["preferred"] == "candidate"
    assert report["blind"]["near_tie_band"] == 0.02
