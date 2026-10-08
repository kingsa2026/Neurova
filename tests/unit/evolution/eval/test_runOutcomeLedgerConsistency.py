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
        # feedback 非空：台账的 `hypothesis` 由失败反馈拼成，Task 4 要拿它去核提示词
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback=f"缺执行步骤:{task_input}")


class _EchoAgent:
    """回显执行器；`candidateFailOn` 让候选侧某例执行抛错——模拟「这一例没量出来」。"""

    def __init__(self, failOn=(), candidateFailOn=()):
        self._fail = set(failOn)
        self._candidateFail = set(candidateFailOn)

    async def run(self, *, skill_text, task_input):
        if task_input in self._fail:
            raise RuntimeError("probe: 该用例执行失败")
        if task_input in self._candidateFail and MARKER in skill_text:
            raise RuntimeError("probe: 候选侧该用例执行失败")
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


class TestNoFabricatedLedgerOutcome:
    """Task 3：终态回写不许凭空造行，也不许把「没量出来」写成质量结论。"""

    @pytest.mark.asyncio
    async def testEarlyRejectionsWriteNoLedgerRow(self, tmp_path):
        """候选前的两处早退（空数据集 / 判分不可用）没有胜者行——造一行即伪造结局。"""
        ledger = EvolutionLedger(tmp_path / "history")
        runner = _runner(ledger, BASE_SCORES, CANDIDATE_SCORES, EvolutionConfig())

        empty = await runner.run(
            baseline_text=BASELINE, dataset=EvalDataset(train=[], val=[], holdout=[]),
            artifact_type="skill", ledger_key="s-empty")
        assert empty.reject_reason == "empty_dataset", empty.reject_reason
        assert ledger.tail("s-empty", 5) == [], "空数据集不该有结局行"

        class _BrokenJudge:
            """判分基础设施不可用：探针自身故障按既有口径保守判不可用。"""

            async def score(self, **kw):
                raise RuntimeError("probe: 判分器不可用")

        broken = SkillEvolutionRunner(
            EvolutionConfig(), judge=_BrokenJudge(), agent=_EchoAgent(),
            mutate=_markerMutate, ledger=ledger)
        result = await broken.run(
            baseline_text=BASELINE, dataset=_dataset(["a"]),
            artifact_type="skill", ledger_key="s-judge")
        assert result.reject_reason == "judge_unavailable", result.reject_reason
        assert ledger.tail("s-judge", 5) == [], "判分没跑起来就没有结局可记"

    @pytest.mark.asyncio
    async def testUnevidencedOnlyRejectionIsNotRecordedAsCaseRegression(self, tmp_path):
        """只有「未量出」而没有实测退化时门不主张：台账不得出现 case_regression 那一行。"""
        ledger = EvolutionLedger(tmp_path / "history")
        runner = SkillEvolutionRunner(
            EvolutionConfig(iterations=1, min_improvement=0.0, case_regression_allowance=0),
            judge=_SplitJudge({"a": 0.4, "b": 0.4}, {"a": 0.9, "b": 0.9}),
            agent=_EchoAgent(candidateFailOn=("b",)),
            mutate=_markerMutate, ledger=ledger)
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b"]),
            artifact_type="skill", ledger_key="s-unev")

        assert result.unevidencedCases == ["b"], result.unevidencedCases
        assert result.caseRegressions == []
        assert result.reject_reason != "case_regression", result.reject_reason
        rows = ledger.tail("s-unev", 10)
        assert not [r for r in rows if r.get("reject_reason") == "case_regression"], (
            f"器械故障被写成了质量结论: {rows}")
