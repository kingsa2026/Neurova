"""运行终态与台账结局的一致性判据（§6-9 落地票面）。

台账走**真文件**：本票要证的就是"写进去的那一行"，mock 掉台账即空转。
判分/执行走脚本化注入，零 LLM 配额；测试里不写实现侧阈值数字，容忍度一律显式传参。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.history_ledger import EvolutionLedger
from neurova.evolution.eval.runner import SkillEvolutionRunner

MARKER = "IMPROVED"
BASELINE = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2


class _SplitJudge:
    """基线侧/候选侧分表：候选正文带 MARKER 时取 `candidate`。"""

    def __init__(self, base, candidate):
        self._base = dict(base)
        self._candidate = dict(candidate)

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        table = self._candidate if MARKER in skill_text else self._base
        value = table.get(task_input, 0.0)
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


class _EchoAgent:
    async def run(self, *, skill_text, task_input):
        return f"out::{skill_text}"


async def _markerMutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + f"\n{MARKER}"


def _dataset(names):
    items = [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]
    return EvalDataset(train=list(items), val=[], holdout=list(items))


def _runner(ledger, base, candidate, config):
    return SkillEvolutionRunner(
        config, judge=_SplitJudge(base, candidate), agent=_EchoAgent(),
        mutate=_markerMutate, ledger=ledger)


BASE_SCORES = {"a": 0.4, "b": 0.4, "c": 0.4}
# 均值 0.4 → 0.633 过关，但 "c" 从可用变成不可用——正是被集级均值吞掉的那一类
CANDIDATE_SCORES = {"a": 0.9, "b": 0.9, "c": 0.1}


class TestRejectedRunFlipsLedgerOutcome:
    @pytest.mark.asyncio
    async def testCaseRegressionRejectionLandsInLedger(self, tmp_path):
        ledger = EvolutionLedger(tmp_path / "history")
        runner = _runner(
            ledger, BASE_SCORES, CANDIDATE_SCORES,
            EvolutionConfig(iterations=1, min_improvement=0.0, case_regression_allowance=0),
        )
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
            artifact_type="skill", ledger_key="s1")

        assert result.reject_reason == "case_regression", result.reject_reason
        assert result.deployed_text == result.baseline_text
        rows = ledger.tail("s1", 10)
        assert rows, "本轮候选应已入账"
        assert not [r for r in rows if r.get("accepted")], (
            f"运行从未部署，台账不得留着 accepted=True: {rows}")
        gated = [r for r in rows if r.get("reject_reason") == "case_regression"]
        assert gated, "被例级门拦这一事实必须落进台账，供既有读方回读"
        assert all(r.get("round_winner") is True for r in gated), (
            "该候选在本轮 tune 上是 argmax——这个事实要留在另一格，不许与「被部署」混用")

    @pytest.mark.asyncio
    async def testAcceptedRunKeepsWinnerRowMarkedDeployed(self, tmp_path):
        """对照组：容忍度内的退化照常出胜者，台账该行仍须是 accepted=True。"""
        ledger = EvolutionLedger(tmp_path / "history")
        runner = _runner(
            ledger, BASE_SCORES, CANDIDATE_SCORES,
            EvolutionConfig(iterations=1, min_improvement=0.0, case_regression_allowance=1),
        )
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
            artifact_type="skill", ledger_key="s2")

        assert result.reject_reason != "case_regression", result.reject_reason
        accepted = [r for r in ledger.tail("s2", 10) if r.get("accepted")]
        assert len(accepted) == 1, "确有部署发生时，台账必须有且只有一条被部署记录"
