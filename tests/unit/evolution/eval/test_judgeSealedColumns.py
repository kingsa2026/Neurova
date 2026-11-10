# -*- coding: utf-8 -*-
"""B4 judge 独立校验并列（survey §10.2）——审批人同时看"评审说好"与"结局好不好"。

判据三件事：judge 高分×密封不涨 → suspect 触发（背离现形）；两列缺一显式
点名缺哪列；与 D4 监测同机器（接线不并造，教义第 6 条）。
"""

import pytest

from neurova.evolution.eval import service as eval_service
from neurova.evolution.eval.adaptation_monitor import AdaptationMonitor


class _Result:
    def __init__(self, holdout_before, holdout_after, heldout_before, heldout_after):
        self.holdout_before = holdout_before
        self.holdout_after = holdout_after
        self.heldout_before = heldout_before
        self.heldout_after = heldout_after


def test_judge_high_sealed_flat_flags_suspect():
    """红灯判据本体：judge 高分（0.2→0.9）×密封不涨（0.5→0.5）→ suspect。"""
    monitor = AdaptationMonitor()
    monitor.record(selection_gain=0.7, sealed_gain=0.0)
    readout = monitor.readout()
    assert readout["suspect_rounds"], "背离形态没触发 suspect——评审说好当真"

    columns = eval_service._judgeSealedColumns(_Result(0.2, 0.9, 0.5, 0.5))
    assert columns["judge_gain"] == pytest.approx(0.7)
    assert columns["sealed_gain"] == pytest.approx(0.0)
    assert columns["missing"] == []


def test_missing_sealed_column_is_named():
    """两列缺一显式点名：heldout 缺席 → missing=['sealed']，不冒充都在。"""
    columns = eval_service._judgeSealedColumns(_Result(0.2, 0.9, 0.0, 0.0))
    assert columns["missing"] == ["sealed"]
    assert columns["sealed_gain"] is None


@pytest.mark.asyncio
async def test_service_wires_monitor_into_proposal(tmp_path, monkeypatch, offlineAgent):
    """服务链：evolve 产出提案时 judge_vs_sealed 随行（审批面可读）。"""
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample
    from neurova.evolution.eval.service import SkillEvolutionService

    svc = eval_service.SkillEvolutionService("agent-b4", base_dir=tmp_path / "evo")
    items = [EvalExample(task_input=f"t{i}", expected_behavior="要点") for i in range(3)]
    ds = EvalDataset(train=list(items), val=[], holdout=list(items),
                     heldout=[EvalExample(task_input=f"h{i}", expected_behavior="要点")
                              for i in range(2)])
    result, proposal = await await_svc_evolve(svc, ds, offlineAgent, tmp_path)
    # 无提案形态（判据门拒）同样要带两列读数——审批面读的是 result 侧
    judge_columns = eval_service._judgeSealedColumns(result)
    assert "judge_gain" in judge_columns
    if proposal is None:
        # 判据门拒的提案不出街——但 result 侧两列已可读（诚实形态：拒因面上也点名）
        assert judge_columns["missing"] in ([], ["sealed"])
    else:
        assert "judge_gain" in (proposal.judge_vs_sealed or {}), (
            f"提案没带 judge_vs_sealed：{proposal.judge_vs_sealed}")


async def await_svc_evolve(svc, ds, offlineAgent, tmp_path):
    from neurova.evolution.eval.config import EvolutionConfig

    async def _judge(*, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        value = 0.9 if "IMPROVED" in skill_text else 0.3
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")

    async def _mutate(*, artifact_text, artifact_type, failures, **kw):
        return artifact_text + "\nIMPROVED"

    return await svc.evolve(
        skill_id="s1", skill_text="基础正文。" + "补充。" * 8, dataset=ds,
        agent=offlineAgent, judge=_judge, mutate=_mutate,
        config=EvolutionConfig(iterations=1, min_improvement=0.0,
                               heldout_ratio=0.0, anchor_floor_enabled=False,
                               cost_rule_enabled=False, noise_repeats=0),
    )
