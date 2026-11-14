# -*- coding: utf-8 -*-
"""V6 部署形态成本差进提案 —— 红灯测试。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V6。
论文（arXiv 2610.01766）披露纪律：进化后 harness 的**部署形态**调用数/token
（ReXTime 0.996→1.963）必须与开发搜索成本分开计量、向采纳者明示。本仓提案面
此前只有开发侧 cost_gate（软门），没有「采纳后每任务多花多少」的读数。

本文件钉：
1. `deploymentCostDelta` 纯函数：measured（有 arms）⇒ 每任务 tokens/费用差与
   相对比例 + CoP 两列；未量到/缺臂 ⇒ state=unmeasured + 原因（不冒充 0）；
2. 提案携带该读数（EvolutionProposal.deployment_cost），随详情面出街；
3. 无 usage 事件的运行 ⇒ 提案 deployment_cost.state = unmeasured（诚实缺格）。
"""

import pytest

from neurova.evolution.eval import cost_ledger
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.cost_ledger import deploymentCostDelta
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.service import SkillEvolutionService

pytestmark = pytest.mark.timeout(120)

BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2
IMPROVED = "IMPROVED"


def _dataset(names):
    items = [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]
    return EvalDataset(train=list(items), val=[], holdout=list(items))


class _ScoringJudge:
    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.9 if IMPROVED in skill_text else 0.5
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


class _EchoAgent:
    async def run(self, *, skill_text, task_input):
        return f"out::{skill_text}"


async def _mutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + "\n" + IMPROVED


class TestDeploymentCostDeltaPure:
    """纯函数：从每任务成本账的臂汇总里算「采纳后每任务成本差」。"""

    def test_measured_arms_yield_delta(self):
        summary = {
            "state": "measured",
            "arms": {
                "baseline": {"tasks": 4, "tokens": 400, "cost_usd": 0.04,
                             "cost_per_case_tokens": 100.0, "cost_per_case_usd": 0.01,
                             "cop_tokens": 110.0, "cop_usd": 0.011},
                "candidate": {"tasks": 4, "tokens": 800, "cost_usd": 0.08,
                              "cost_per_case_tokens": 200.0, "cost_per_case_usd": 0.02,
                              "cop_tokens": 220.0, "cop_usd": 0.022},
            },
        }
        readout = deploymentCostDelta(summary)
        assert readout["state"] == "measured"
        assert readout["baseline_per_case_usd"] == pytest.approx(0.01)
        assert readout["candidate_per_case_usd"] == pytest.approx(0.02)
        assert readout["delta_per_case_usd"] == pytest.approx(0.01)
        assert readout["delta_ratio"] == pytest.approx(1.0)
        assert readout["delta_per_case_tokens"] == pytest.approx(100.0)
        assert readout["baseline_cop_usd"] == pytest.approx(0.011)
        assert readout["candidate_cop_usd"] == pytest.approx(0.022)

    def test_unmeasured_state_is_honest_not_zero(self):
        readout = deploymentCostDelta({"state": "no_usage_events", "arms": {}})
        assert readout == {"state": "unmeasured", "reason": "no_usage_events"}

    def test_missing_baseline_arm_is_unmeasured(self):
        readout = deploymentCostDelta({
            "state": "measured",
            "arms": {"candidate": {"cost_per_case_usd": 0.02}},
        })
        assert readout["state"] == "unmeasured"

    def test_none_summary_is_unmeasured(self):
        assert deploymentCostDelta(None)["state"] == "unmeasured"

    def test_zero_baseline_cost_ratio_is_none_not_infinity(self):
        readout = deploymentCostDelta({
            "state": "measured",
            "arms": {"baseline": {"cost_per_case_usd": 0.0, "cost_per_case_tokens": 0.0},
                     "candidate": {"cost_per_case_usd": 0.02, "cost_per_case_tokens": 200.0}},
        })
        assert readout["state"] == "measured"
        assert readout["delta_ratio"] is None


class TestProposalCarriesDeploymentCost:
    """提案面：验收人点开提案就看到「采纳后每任务多花多少」。"""

    @pytest.mark.asyncio
    async def test_proposal_carries_measured_delta(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        # 伪造 usage 快照：每评测一次推进一步 → 两臂都有真实花费差分
        clock = {"n": 0}

        def fake_snapshot():
            clock["n"] += 1
            return {"tokens": clock["n"] * 100, "cost_usd": clock["n"] * 0.01}

        monkeypatch.setattr(cost_ledger, "usageSnapshot", fake_snapshot)
        svc = SkillEvolutionService("cost-delta-agent", base_dir=tmp_path / "evo")
        _result, proposal = await svc.evolve(
            skill_id="s-cost", skill_text=BASELINE, dataset=_dataset(["a", "b"]),
            agent=_EchoAgent(), judge=_ScoringJudge(), mutate=_mutate,
            config=EvolutionConfig(iterations=1, min_improvement=0.0,
                                   noise_repeats=1, exec_suite_enabled=False,
                                   anchor_floor_enabled=False, heldout_ratio=0.0))

        assert proposal is not None, _result.reject_reason
        readout = proposal.deployment_cost
        assert readout["state"] == "measured"
        assert readout["candidate_per_case_usd"] >= readout["baseline_per_case_usd"]
        assert readout["delta_per_case_usd"] == pytest.approx(
            readout["candidate_per_case_usd"] - readout["baseline_per_case_usd"], abs=1e-6)
        # 详情面（提案 to_dict）也带这一格
        assert "deployment_cost" in proposal.to_dict()

    @pytest.mark.asyncio
    async def test_proposal_unmeasured_when_no_usage_events(self, monkeypatch, tmp_path):
        """无 usage 事件（离线替身）⇒ unmeasured，不冒充 0 成本差。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("cost-delta-agent", base_dir=tmp_path / "evo")
        _result, proposal = await svc.evolve(
            skill_id="s-cost", skill_text=BASELINE, dataset=_dataset(["a", "b"]),
            agent=_EchoAgent(), judge=_ScoringJudge(), mutate=_mutate,
            config=EvolutionConfig(iterations=1, min_improvement=0.0,
                                   noise_repeats=1, exec_suite_enabled=False,
                                   anchor_floor_enabled=False, heldout_ratio=0.0))

        assert proposal is not None
        assert proposal.deployment_cost["state"] == "unmeasured"
