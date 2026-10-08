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
from neurova.evolution.eval.runner import SkillEvolutionRunner


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

