"""例级不退化门判据（对照报告 §8 前置 1 落地票面）。

票面：docs/04-plans/2026-10-08-前置1-例级不退化门实施方案.md

测试里**不写实现侧默认阈值**（容忍度一律显式传参）——把默认值写进断言
等于把实现细节钉成契约，日后调默认值会红在不该红的地方。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.history_ledger import GATE_REASON_PREFIXES
from neurova.evolution.eval.runner import SkillEvolutionRunner, _caseRegressionReadout


# 基线要够长：service 装配路径带约束闸（growth_limit / semantic_similarity），
# 正文太短则"任何追加"都超增长上限，候选压根走不到评测（先例
# tests/unit/evolution/eval/test_service_closed_loop.py 同此形态）。
BASELINE = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2
# 变异器在本文件里固定追加这条标记；判分器据此区分基线侧与候选侧读数。
# 两侧分数是**测试自己的约定**，不来自实现侧默认值。
CANDIDATE_MARKER = "IMPROVED"


def _examples(names):
    return [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]


def _dataset(names):
    """train/val 与 holdout 同源，便于把评测面控制在这一组用例上。"""
    items = _examples(names)
    return EvalDataset(train=list(items), val=[], holdout=list(items))


class _ScoringJudge:
    """按 task_input 给分的脚本化判分器；未列出的任务记 0 分（已量出）。

    `candidateScores` 只在候选正文（带 CANDIDATE_MARKER）上生效——留出侧两侧
    读数要能不同，才谈得上"某一条被改坏了"。
    """

    def __init__(self, scores, candidateScores=None):
        self._scores = dict(scores)
        self._candidate = dict(candidateScores) if candidateScores is not None else None
        self.calls = 0

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        self.calls += 1
        table = self._scores
        if self._candidate is not None and CANDIDATE_MARKER in skill_text:
            table = self._candidate
        value = table.get(task_input, 0.0)
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


class _EchoAgent:
    """回显执行器；failOn 列出的任务让执行直接抛错——模拟"这一例没量出来"。

    `candidateFailOn` 只在候选侧抛错，用于钉"仅一侧没量出来"同样是未量出。
    """

    def __init__(self, failOn=(), candidateFailOn=()):
        self._fail = set(failOn)
        self._candidateFail = set(candidateFailOn)

    async def run(self, *, skill_text, task_input):
        if task_input in self._fail:
            raise RuntimeError("probe: 该用例执行失败")
        if task_input in self._candidateFail and CANDIDATE_MARKER in skill_text:
            raise RuntimeError("probe: 候选侧该用例执行失败")
        return f"out::{skill_text}"


def _runner(scores, config, agent=None, mutate=None, candidateScores=None):
    return SkillEvolutionRunner(
        config, judge=_ScoringJudge(scores, candidateScores), agent=agent or _EchoAgent(),
        mutate=mutate or _markerMutate,
    )


async def _markerMutate(*, artifact_text, artifact_type, failures, **kw):
    """变异器替身：产出带 CANDIDATE_MARKER 的正文（判分器据此换候选侧分表）。

    只追加标记本身——追加得越多，service 装配路径的增长闸越容易先把它拦掉，
    那样候选根本到不了例级门。
    """
    return artifact_text + f"\n{CANDIDATE_MARKER}"


class TestEvaluateDetailsCarryFailedFlag:
    """Task 1：明细必须带得上单例失败标记。

    均分里 0.0 与"这一例压根没量出来"同值。集合层判据可以忍，
    **例级**判据不行——拿它判"谁退化了"会把器械故障写成质量结论。
    """

    @pytest.mark.asyncio
    async def testFailedCaseIsDistinguishableFromRealZero(self):
        runner = _runner(
            {"a": 0.9, "b": 0.9},
            EvolutionConfig(),
            agent=_EchoAgent(failOn=("b",)),
        )
        avg, details = await runner._evaluate(BASELINE, _examples(["a", "b"]), "skill")
        flags = {ex.task_input: failed for ex, _s, _o, _f, failed in details}
        assert flags == {"a": False, "b": True}
        # 失败例仍按 0 分占满分母（P2-9 既有口径，本票不改）
        assert avg == pytest.approx(0.9 / 2)

    @pytest.mark.asyncio
    async def testExistingUnpackSitesStillWork(self):
        """`_collect_failures_sorted` 是明细的消费方之一：改形状不得让它漏判失败例。"""
        runner = _runner(
            {"a": 0.2, "b": 0.9},
            EvolutionConfig(),
            agent=_EchoAgent(failOn=("b",)),
        )
        failures = await runner._collect_failures_sorted(
            BASELINE, _examples(["a", "b"]), "skill")
        assert [f.task_input for f in failures] == ["b", "a"]


class TestHoldoutSideYieldsPerCaseReadouts:
    """Task 2：留出侧拿到两侧例级读数，均值语义零漂移。

    留出两次评测由 `_evaluate_avg` 改走同一条 `_evaluate`——评测次数不变，
    只是明细不再被当场丢掉。判据要读的是**例级**，均值照旧对外。
    """

    @pytest.mark.asyncio
    async def testHoldoutCarriesBothSidesPerCase(self):
        runner = _runner({"a": 0.4, "b": 0.8}, EvolutionConfig(iterations=1))
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b"]),
            artifact_type="skill", iterations=1)

        assert sorted(result.holdout_case_scores) == ["a", "b"]
        assert result.holdout_case_scores["a"] == {
            "baseline": 0.4, "candidate": 0.4,
            "baseline_failed": False, "candidate_failed": False}
        # 明细与均分同源：均值仍是这两条例级读数的算术平均（零行为漂移）
        assert result.holdout_before == pytest.approx(0.6)
        assert result.holdout_after == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def testFailedHoldoutCaseRidesAlongAsFlagNotSilentZero(self):
        """留出侧「这一例没量出来」必须带得出来，不得只留 0.0 让下游猜。"""
        runner = _runner({"a": 0.4, "b": 0.8}, EvolutionConfig(iterations=1),
                         agent=_EchoAgent(failOn=("b",)))
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b"]),
            artifact_type="skill", iterations=1)

        readout = result.holdout_case_scores["b"]
        assert readout["baseline_failed"] is True and readout["candidate_failed"] is True
        assert readout["baseline"] == 0.0


class TestCaseRegressionGate:
    """Task 3：留出集均值涨了不算过关——撞坏的既有用例数过容忍度即拒。

    容忍度一律**测试显式传参**，不依赖 `EvolutionConfig` 默认值（那等于把
    默认值钉成契约）。
    """

    @pytest.mark.asyncio
    async def testGateRejectsWhenCaseCountOverAllowance(self):
        runner = _runner(
            {"a": 0.4, "b": 0.4, "c": 0.4},
            EvolutionConfig(case_regression_allowance=0, min_improvement=0.0),
            candidateScores={"a": 0.9, "b": 0.9, "c": 0.1},
        )
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
            artifact_type="skill", iterations=1)

        assert result.rejected is True
        assert result.reject_reason == "case_regression"
        assert result.caseRegressions == ["c"]
        assert result.unevidencedCases == []
        assert result.caseAllowance == 0
        assert result.deployed_text == result.baseline_text, "拒绝必须复位基线"
        # 集级均值确实是涨的——这道门拦的正是被均值吞掉的那一类候选
        assert result.holdout_after > result.holdout_before

    @pytest.mark.asyncio
    async def testAllowancePermitsBoundedRegression(self):
        runner = _runner(
            {"a": 0.4, "b": 0.4, "c": 0.4},
            EvolutionConfig(case_regression_allowance=1, min_improvement=0.0),
            candidateScores={"a": 1.0, "b": 0.9, "c": 0.1},
        )
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
            artifact_type="skill", iterations=1)

        assert result.reject_reason != "case_regression", result.reject_reason
        assert result.caseRegressions == ["c"]
        assert result.caseAllowance == 1

    @pytest.mark.asyncio
    async def testUnevidencedCaseIsNotCountedAsRegression(self):
        """单例判分崩了（任一侧 failed）落"未量出"：既不判退化，也不判没退化。"""
        runner = _runner(
            {"a": 0.4, "b": 0.4},
            EvolutionConfig(case_regression_allowance=0, min_improvement=0.0),
            agent=_EchoAgent(candidateFailOn=("b",)),
            candidateScores={"a": 0.9, "b": 0.9},
        )
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b"]),
            artifact_type="skill", iterations=1)

        assert result.unevidencedCases == ["b"]
        assert result.caseRegressions == []
        assert result.reject_reason != "case_regression", result.reject_reason

    def testReadoutIsSilentWhenNothingMeasured(self):
        """一条都没量到 → 门不主张，交由既有均值/失明判据处置。"""
        assert _caseRegressionReadout({}) == ([], [])

    def testReadoutSeparatesUnevidencedFromRegression(self):
        """纯函数级反证：仅一侧没量出也算未量出，不得凭另一侧的读数判退化。"""
        caseScores = {
            "regressed": {"baseline": 0.6, "candidate": 0.1,
                          "baseline_failed": False, "candidate_failed": False},
            "halfMeasured": {"baseline": 0.6, "candidate": 0.0,
                             "baseline_failed": False, "candidate_failed": True},
            "held": {"baseline": 0.3, "candidate": 0.9,
                     "baseline_failed": False, "candidate_failed": False},
        }
        assert _caseRegressionReadout(caseScores) == (["regressed"], ["halfMeasured"])

    def testCaseRegressionIsNotCompressedIntoGateWall(self):
        """`case_regression` 不属约束/泄漏前缀：它是一次**实测否决**，
        不是"提案质量问题"——被压进拒绝墙会让变异器误读成该换方向。"""
        assert not "case_regression".startswith(GATE_REASON_PREFIXES)


class TestCaseGateReadoutSurface:
    """Task 4：§2 断点条款——门拦没拦必须看得见，不许只写在内存里。

    两个现役读点：判定链拒绝走 `run` 审计落盘面（`to_dict`），门放行但撞坏了
    用例走提案详情面（`EvolutionProposal` → 既有 `GET .../proposals/{id}` 读口）。
    """

    @pytest.mark.asyncio
    async def testRejectedRunReadoutCarriesCaseGate(self):
        runner = _runner(
            {"a": 0.4, "b": 0.4, "c": 0.4},
            EvolutionConfig(case_regression_allowance=0, min_improvement=0.0,
                            iterations=1),
            candidateScores={"a": 0.9, "b": 0.9, "c": 0.1},
        )
        result = await runner.run(
            baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
            artifact_type="skill", iterations=1)
        readout = result.to_dict()

        assert readout["case_gate"] == {
            "allowance": 0, "regressions": ["c"], "unevidenced": []}
        # 读的人要一眼看出"均值过关、例级没过关"是两件事
        assert readout["reject_reason"] == "case_regression"
        assert readout["holdout_after"] > readout["holdout_before"]

    @pytest.mark.asyncio
    async def testProposalDetailCarriesCaseGate(self, tmp_path, monkeypatch):
        """容忍度内的退化照样出提案——但审批人必须看见撞坏了哪一条。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
        svc = SkillEvolutionService("gate-agent", base_dir=tmp_path / "evo")

        _result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
            agent=_EchoAgent(),
            config=EvolutionConfig(iterations=1, min_improvement=0.0,
                                   case_regression_allowance=1),
            judge=_ScoringJudge({"a": 0.4, "b": 0.4, "c": 0.4},
                                {"a": 1.0, "b": 0.9, "c": 0.1}),
            mutate=_markerMutate,
        )
        assert proposal is not None, _result.reject_reason

        stored = svc.list_proposals()
        assert stored[0]["case_gate"] == {
            "allowance": 1, "regressions": ["c"], "unevidenced": []}
