"""HN1/HC1 每任务成本账 + CoP 读数 + 进化成本软门 —— 红灯测试。

HarnessPro 对照（2026-11-13）断点 HN1：成本只记账不进目标——
`eval/runner.py` 的 `cost_*` 字段是文本长度代理（P1-5），执行/判分的真实
token/费用没有按任务落账，也没有 Cost-of-Pass 读数；提案面没有成本软门
（候选成本相对基线涨幅超阈值 → 强制人工复核）。

本文件钉三件事：
1. `EvalCostLedger` 的聚合口径（per-arm 汇总 + CoP；零通过 ⇒ CoP=None 不是 0；
   无 usage 事件 ⇒ state="no_usage_events"，0 不冒充"免费"）；
2. runner 在每次单例评测前后取 usage 快照差分，按臂（baseline/candidate/
   probe/anchor/heldout）落账，结果面 `cost_summary` 外露；
3. `service.evolve` 的成本软门：候选臂成本相对基线臂涨幅超阈值 ⇒ 提案
   `requires_manual_review=True` 且 `cost_gate.state="manual_review"`。
"""

import pytest

from neurova.evolution.eval import cost_ledger
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner
from neurova.evolution.eval.service import SkillEvolutionService


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 4


def _ds() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_with_gain(gain: float):
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + gain if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


class _EchoAgent:
    async def run(self, *, skill_text: str, task_input: str) -> str:
        return f"echo:{task_input}"


def _patch_usage(monkeypatch, *, tokens_per_call: float = 10.0, cost_per_call: float = 0.001,
                 accelerate: float = 0.0):
    """把 cost_ledger.usageSnapshot 换成可控假快照。

    每次调用 tokens/cost 线性（或加速）递增；差分即两次调用之间"发生"的消耗。
    accelerate>0 时第 n 次调用按 n^(1+accelerate) 增长——后段（候选臂）单例
    消耗天然高于前段（基线臂），用来构造"成本暴涨"形态。
    """
    calls = {"n": 0}

    def fake_snapshot() -> dict:
        calls["n"] += 1
        n = calls["n"]
        tokens = int(tokens_per_call * (n ** (1.0 + accelerate)))
        cost = cost_per_call * (n ** (1.0 + accelerate))
        return {"tokens": tokens, "cost_usd": cost}

    monkeypatch.setattr(cost_ledger, "usageSnapshot", fake_snapshot)
    return calls


# ── 1. 账本聚合口径 ──────────────────────────────────────────────

class TestEvalCostLedger:
    def test_summarize_per_arm_and_cop(self):
        ledger = cost_ledger.EvalCostLedger(pass_score=0.5)
        ledger.add(task_input="a", arm="baseline", tokens=100, cost_usd=0.01, score=0.9, failed=False)
        ledger.add(task_input="b", arm="baseline", tokens=300, cost_usd=0.03, score=0.2, failed=False)
        summary = ledger.summarize()
        assert summary["state"] == "measured"
        base = summary["arms"]["baseline"]
        assert base["tasks"] == 2
        assert base["tokens"] == 400
        assert base["cost_usd"] == pytest.approx(0.04)
        assert base["passed"] == 1
        # CoP = 总成本 / 通过数；分母是"通过"不是"评测数"
        assert base["cop_usd"] == pytest.approx(0.04)
        assert base["cop_tokens"] == pytest.approx(400.0)
        assert base["cost_per_case_usd"] == pytest.approx(0.02)

    def test_zero_passes_cop_is_none_not_zero(self):
        """全不通过 ⇒ CoP 无定义（None），0 会被读成'免费通过'。"""
        ledger = cost_ledger.EvalCostLedger(pass_score=0.5)
        ledger.add(task_input="a", arm="candidate", tokens=100, cost_usd=0.01, score=0.1, failed=False)
        summary = ledger.summarize()
        cand = summary["arms"]["candidate"]
        assert cand["passed"] == 0
        assert cand["cop_usd"] is None
        assert cand["cop_tokens"] is None

    def test_failed_cases_excluded_from_pass_denominator(self):
        ledger = cost_ledger.EvalCostLedger(pass_score=0.5)
        ledger.add(task_input="a", arm="candidate", tokens=100, cost_usd=0.01, score=0.0, failed=True)
        ledger.add(task_input="b", arm="candidate", tokens=100, cost_usd=0.01, score=0.9, failed=False)
        cand = ledger.summarize()["arms"]["candidate"]
        assert cand["passed"] == 1
        assert cand["cop_usd"] == pytest.approx(0.02)

    def test_no_usage_events_state(self):
        """零 token 差分 ⇒ state=no_usage_events：0 不是'免费'是'没量到'。"""
        ledger = cost_ledger.EvalCostLedger(pass_score=0.5)
        ledger.add(task_input="a", arm="baseline", tokens=0, cost_usd=0.0, score=0.9, failed=False)
        summary = ledger.summarize()
        assert summary["state"] == "no_usage_events"
        assert summary["arms"]["baseline"]["tokens"] == 0

    def test_soft_gate_verdict_states(self):
        summary = {
            "state": "measured",
            "arms": {"baseline": {"cost_usd": 0.10}, "candidate": {"cost_usd": 0.11}},
        }
        assert cost_ledger.costSoftGateVerdict(
            summary, ratio_threshold=0.2, enabled=True)["state"] == "within_budget"
        summary["arms"]["candidate"]["cost_usd"] = 0.30
        verdict = cost_ledger.costSoftGateVerdict(summary, ratio_threshold=0.2, enabled=True)
        assert verdict["state"] == "manual_review"
        assert verdict["ratio"] == pytest.approx(2.0)
        # 未量到 / 关闭 / 基线零成本：诚实不判
        assert cost_ledger.costSoftGateVerdict(
            {"state": "no_usage_events", "arms": {}}, ratio_threshold=0.2, enabled=True
        )["state"] == "unmeasured"
        assert cost_ledger.costSoftGateVerdict(
            summary, ratio_threshold=0.2, enabled=False)["state"] == "disabled"
        assert cost_ledger.costSoftGateVerdict(
            {"state": "measured", "arms": {"baseline": {"cost_usd": 0}, "candidate": {}}},
            ratio_threshold=0.2, enabled=True)["state"] == "unmeasured"


# ── 2. runner 集成：单例评测前后取差分按臂落账 ────────────────────

class TestRunnerCostCapture:
    @pytest.mark.asyncio
    async def test_run_attaches_cost_summary(self, monkeypatch):
        """runner.run 后 cost_summary 按臂落账：基线/候选两臂 tokens>0，
        state=measured，且明细含任务级记录。"""
        _patch_usage(monkeypatch)
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.02),
            mutate=_echo_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert not result.rejected
        summary = result.cost_summary
        assert summary["state"] == "measured"
        assert summary["arms"]["baseline"]["tokens"] > 0
        assert summary["arms"]["candidate"]["tokens"] > 0
        assert summary["arms"]["baseline"]["tasks"] >= 6  # holdout(2)+tune(6)... 至少判据集
        assert summary["tasks_total"] > 0
        assert summary["tasks"][0]["arm"] in {"baseline", "candidate", "probe", "anchor", "heldout"}
        assert "cop_usd" in summary["arms"]["candidate"]

    @pytest.mark.asyncio
    async def test_no_usage_events_when_accounting_silent(self, monkeypatch):
        """真实单例无 usage 记录（离线假执行器）⇒ state=no_usage_events，
        全零不冒充'免费'。"""
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.02), mutate=_echo_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert result.cost_summary["state"] == "no_usage_events"
        assert result.cost_summary["arms"]["baseline"]["tokens"] == 0

    @pytest.mark.asyncio
    async def test_cost_summary_attached_on_reject_path(self, monkeypatch):
        """拒绝路径（rejectRun）同样落 cost_summary——账目不因拒绝而消失。"""
        _patch_usage(monkeypatch)
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.0),  # 零增益 → no_improvement
            mutate=_echo_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds())
        assert result.rejected
        assert result.cost_summary["state"] == "measured"


def _echo_mutate():
    async def mutate(*, artifact_text, artifact_type, failures):
        # 增长必须 < max_prompt_growth(0.2)：service 路径装配了约束闸，
        # 膨胀候选会在评测前被拒（无提案可断言）。
        return artifact_text + " IMPROVED"
    return mutate


# ── 3. service 成本软门 ─────────────────────────────────────────

class TestCostSoftGate:
    @pytest.mark.asyncio
    async def test_manual_review_when_candidate_cost_surges(self, monkeypatch, tmp_path):
        """候选臂成本涨幅超阈值 ⇒ 提案强制人工复核，cost_gate 出街。"""
        _patch_usage(monkeypatch, accelerate=0.9)  # 后段（候选臂）消耗加速
        svc = SkillEvolutionService("cost-gate-agent", base_dir=tmp_path)
        result, proposal = await svc.evolve(
            skill_id="sk-cost", skill_text=BASELINE, dataset=_ds(),
            iterations=1, agent=_EchoAgent(), judge=_judge_with_gain(0.02),
            mutate=_echo_mutate(),
            config=EvolutionConfig(noise_repeats=1),
        )
        assert not result.rejected
        assert proposal is not None
        assert proposal.cost_gate["state"] == "manual_review"
        assert proposal.cost_gate["ratio"] > 0.2
        assert proposal.requires_manual_review is True

    @pytest.mark.asyncio
    async def test_within_budget_keeps_normal_path(self, monkeypatch, tmp_path):
        """成本线性（候选臂与基线臂同量级）⇒ within_budget，不强人工复核。"""
        _patch_usage(monkeypatch)  # 线性增长：各臂单例消耗相同
        svc = SkillEvolutionService("cost-gate-agent", base_dir=tmp_path)
        result, proposal = await svc.evolve(
            skill_id="sk-cost", skill_text=BASELINE, dataset=_ds(),
            iterations=1, agent=_EchoAgent(), judge=_judge_with_gain(0.02),
            mutate=_echo_mutate(),
            config=EvolutionConfig(noise_repeats=1),
        )
        assert not result.rejected
        assert proposal is not None
        assert proposal.cost_gate["state"] == "within_budget"
        assert proposal.requires_manual_review is False

    @pytest.mark.asyncio
    async def test_unmeasured_when_no_usage(self, tmp_path):
        """无 usage 事件 ⇒ cost_gate.state=unmeasured，不冒充通过也不误杀。"""
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        svc = SkillEvolutionService("cost-gate-agent", base_dir=tmp_path)
        result, proposal = await svc.evolve(
            skill_id="sk-cost", skill_text=BASELINE, dataset=_ds(),
            iterations=1, agent=_EchoAgent(), judge=_judge_with_gain(0.02),
            mutate=_echo_mutate(),
            config=EvolutionConfig(noise_repeats=1),
        )
        assert proposal is not None
        assert proposal.cost_gate["state"] == "unmeasured"
        assert proposal.requires_manual_review is False
