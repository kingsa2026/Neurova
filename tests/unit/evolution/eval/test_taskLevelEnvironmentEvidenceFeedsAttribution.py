"""任务级环节证据 → 归因分组（ModularRSI M-E 第二刀，票面裁定**乙**）。

票面：`docs/04-plans/2026-10-16-任务级环节证据-attribution升级实施方案.md`

乙案的语义写在这里，是因为它最容易被读错：候选「声称要修的环节」**不是模型自报**，
而是**生成它的那批失败用例在运行时的环节证据取并集**——读的人要读成「生成时看到的
环节分布」，不能读成「模型自己认为改的是哪个环节」。

两族判据分开钉：
- 证据面：peek 只读不消费、每任务各取一份、并行候选互不串味、模拟臂恒空且**不报错**；
- 读数面：`claimed_environments` / `by_environment` 由证据反推、与总命中数可对账、
  有读者（提示段），但**不进 accept/reject 判据**（最后一格钉这条）。
"""

import asyncio

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.history_ledger import EvolutionLedger, attribution_hit_rate
from neurova.evolution.eval.runner import SkillEvolutionRunner

CANDIDATE_MARKER = "IMPROVED"


@pytest.fixture(autouse=True)
def _isolateGapInbox():
    """收件箱落在 ContextVar 上：前后各清一次，避免同进程相邻用例互相看见证据。"""
    from neurova.agent.capability_gap import clearCapabilityGap

    clearCapabilityGap("env-evidence")
    yield
    clearCapabilityGap("env-evidence")


def _examples(names):
    return [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]


class _EnvAgent:
    """执行器替身：在任务执行期间投环节证据（与真臂环出口投递同形）。

    真臂的证据来自 `agent/loops/base.py:evaluateLoopExit` → `_recordHarnessGapFromExit`；
    替身不带生产侧回合边界，故「相邻两条任务之间由评测面自己收口」只能由本文件的
    读数断言来钉——那正是它要证的性质。
    """

    def __init__(self, envByTask=None, failOn=()):
        self._env = {k: list(v) for k, v in (envByTask or {}).items()}
        self._fail = set(failOn)

    async def run(self, *, skill_text, task_input):
        from neurova.agent.capability_gap import recordCapabilityGap

        # 先投证据再抛错：环是在崩溃之前卡住的，替身必须与这个次序同形
        for kind in self._env.get(task_input, []):
            recordCapabilityGap(kind, {"gate": "goal", "task": task_input})
        if task_input in self._fail:
            raise RuntimeError("probe: 该用例执行失败")
        return f"out::{skill_text}"


class _ScoringJudge:
    """按 task_input 给分；候选侧（正文含标记）换第二张分表。"""

    def __init__(self, scores, candidateScores=None):
        self._scores = dict(scores)
        self._candidate = dict(candidateScores) if candidateScores is not None else None

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        table = self._candidate if (
            self._candidate is not None and CANDIDATE_MARKER in skill_text) else self._scores
        value = table.get(task_input, 0.0)
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


async def _markerMutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + f"\n{CANDIDATE_MARKER}"


def _evaluateRunner(envByTask, scores, agent=None):
    return SkillEvolutionRunner(
        EvolutionConfig(), judge=_ScoringJudge(scores),
        agent=agent if agent is not None else _EnvAgent(envByTask))


async def _runOnce(tmp_path, names, envByTask, baseScores, candScores):
    """跑一轮真实 `runner.run()`（台账注入），返回 (结果, 台账末条记录)。

    走 `run()` 而不是直接调私有装配点：环节证据要经 `_collect_failures` 建成
    `JudgeFailure`、再由 `_ledger_append` 喂给归因，这条接线整段都得在场。
    """
    ledger = EvolutionLedger(tmp_path / "history")
    items = _examples(names)
    dataset = EvalDataset(train=list(items), val=[], holdout=list(items))
    runner = SkillEvolutionRunner(
        EvolutionConfig(iterations=1, anchor_floor_enabled=False, cost_rule_enabled=False),
        judge=_ScoringJudge(baseScores, candScores),
        agent=_EnvAgent(envByTask), mutate=_markerMutate, ledger=ledger,
    )
    result = await runner.run(baseline_text="BASE", artifact_type="skill",
                              dataset=dataset, ledger_key="k")
    return result, ledger.tail("k", 1)[0]


class TestPeekIsReadOnly:
    """读数口：peek 不消费、不写指标，消费点仍只有 `detectCapabilityGap`。"""

    def testPeekReturnsKindsWithoutConsuming(self):
        from neurova.agent.capability_gap import (
            GAP_LOOP_STALLED,
            detectCapabilityGap,
            peekCapabilityGapKinds,
            recordCapabilityGap,
        )

        recordCapabilityGap(GAP_LOOP_STALLED, {"gate": "doom_loop"})
        assert peekCapabilityGapKinds() == [GAP_LOOP_STALLED]
        assert peekCapabilityGapKinds() == [GAP_LOOP_STALLED], "peek 把收件箱吃掉了"
        assert detectCapabilityGap().harnessKinds == [GAP_LOOP_STALLED]
        assert peekCapabilityGapKinds() == []

    def testPeekDoesNotBumpGapMetrics(self):
        """peek 是观察不是判定：把读次数计进缺口指标，指标就从"命中几类"变成"被读了几次"。"""
        from neurova.agent.capability_gap import (
            GAP_FALSE_COMPLETION,
            peekCapabilityGapKinds,
            recordCapabilityGap,
        )
        from neurova.agent.gap_metric_channel import readGapMetrics

        recordCapabilityGap(GAP_FALSE_COMPLETION, {"gate": "goal"})
        before = readGapMetrics()
        peekCapabilityGapKinds()
        peekCapabilityGapKinds()
        assert readGapMetrics() == before, "peek 侧写了指标"


class TestPerTaskEnvironmentEvidence:
    """明细带第六格（每任务的环节证据），且取证不污染相邻任务。"""

    @pytest.mark.asyncio
    async def testEvaluateDetailsCarryEnvironmentEvidence(self):
        from neurova.agent.capability_gap import GAP_LOOP_STALLED

        runner = _evaluateRunner({"b": [GAP_LOOP_STALLED]}, {"a": 0.9, "b": 0.9})
        _avg, details = await runner._evaluate("BASE", _examples(["a", "b", "c"]), "skill")
        assert all(len(item) == 6 for item in details), "明细没带上环节证据这一格"
        envs = {ex.task_input: env for ex, _s, _o, _f, _failed, env in details}
        # "c" 那条是关键：上一条任务的证据不许漏读成这一条的（本仓「跨轮残留」形态）
        assert envs == {"a": [], "b": [GAP_LOOP_STALLED], "c": []}

    @pytest.mark.asyncio
    async def testFailedExampleStillReportsItsEvidence(self):
        """执行抛错的单例也要带得上证据：环是在崩溃**之前**卡住的，丢掉就是假象。"""
        from neurova.agent.capability_gap import GAP_LOOP_STALLED

        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_ScoringJudge({"a": 0.9}),
            agent=_EnvAgent({"a": [GAP_LOOP_STALLED]}, failOn=("a",)))
        _avg, details = await runner._evaluate("BASE", _examples(["a"]), "skill")
        ex, score, _o, _f, failed, env = details[0]
        assert (failed, score) == (True, 0.0)
        assert env == [GAP_LOOP_STALLED]

    @pytest.mark.asyncio
    async def testSimulatedArmReportsEmptyWithoutError(self):
        """没跑环的臂：恒空、不报错、不编标签（票面 §4 里最坏的那种实现）。"""
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_ScoringJudge({"a": 0.5}), agent=_EnvAgent())
        _avg, details = await runner._evaluate("BASE", _examples(["a", "b"]), "skill")
        assert all(item[5] == [] for item in details)
        failures = await runner._collect_failures("BASE", _examples(["a"]), "skill")
        assert failures[0].environments == []

    @pytest.mark.asyncio
    async def testParallelCandidatesDoNotShareEvidence(self):
        """P1-7a 的并行评测：两个候选对同一道题各自看到自己的环节，不许串味。"""
        from neurova.agent.capability_gap import GAP_FALSE_COMPLETION, GAP_LOOP_STALLED

        examples = _examples(["a", "b"])
        runner1 = _evaluateRunner({"b": [GAP_LOOP_STALLED]}, {"a": 0.2, "b": 0.3})
        runner2 = _evaluateRunner({"b": [GAP_FALSE_COMPLETION]}, {"a": 0.2, "b": 0.3})
        first, second = await asyncio.gather(
            runner1._evaluate("BASE", examples, "skill"),
            runner2._evaluate("BASE", examples, "skill"),
        )
        env1 = {item[0].task_input: item[5] for item in first[1]}
        env2 = {item[0].task_input: item[5] for item in second[1]}
        assert env1["b"] == [GAP_LOOP_STALLED]
        assert env2["b"] == [GAP_FALSE_COMPLETION]


class TestClaimIsDerivedFromEvidence:
    """乙案本体：声明 = 喂出该候选的失败用例的环节证据并集，不是自报。"""

    def testClaimedEnvironmentsAreUnionOfFeedingEvidence(self):
        report = attribution_hit_rate(
            predicted=["t1", "t2"],
            base_scores={"t1": 0.2, "t2": 0.3},
            cand_scores={"t1": 0.8, "t2": 0.9},
            envsByTask={"t1": ["loop_stalled"], "t2": ["loop_stalled", "false_completion"]},
        )
        assert report["claimed_environments"] == ["false_completion", "loop_stalled"]
        assert report["by_environment"]["loop_stalled"] == {"predicted": 2, "hit": 2, "regressed": 0}
        assert report["by_environment"]["false_completion"] == {"predicted": 1, "hit": 1, "regressed": 0}

    def testEmptyEvidenceYieldsEmptyClaimNotAFabricatedKind(self):
        report = attribution_hit_rate(
            predicted=["t1"], base_scores={"t1": 0.2}, cand_scores={"t1": 0.8})
        assert "claimed_environments" in report, "键缺席与量出为空必须能分开"
        assert report["claimed_environments"] == []
        assert report["by_environment"] == {}

    def testBucketsReconcileWithOverallHits(self):
        """单环节任务时，分桶命中数之和必须等于总命中数——不许另起一份互不相等的口径。"""
        report = attribution_hit_rate(
            predicted=["t1", "t2", "t3"],
            base_scores={"t1": 0.2, "t2": 0.2, "t3": 0.9},
            cand_scores={"t1": 0.8, "t2": 0.9, "t3": 0.9},
            envsByTask={"t1": ["loop_stalled"], "t2": ["false_completion"], "t3": ["false_completion"]},
        )
        assert report["hits"] == ["t1", "t2"]
        assert sum(v["hit"] for v in report["by_environment"].values()) == len(report["hits"])
        # 一条任务含两个环节时它进两个桶：桶之和 ≥ 命中数是定义使然，不是重复计数故障
        multi = attribution_hit_rate(
            predicted=["t1"], base_scores={"t1": 0.2}, cand_scores={"t1": 0.8},
            envsByTask={"t1": ["loop_stalled", "false_completion"]})
        assert sum(v["hit"] for v in multi["by_environment"].values()) == 2

    def testUnpredictedRegressionsGroupedByCandidateEnvironment(self):
        report = attribution_hit_rate(
            predicted=["t1"],
            base_scores={"t1": 0.2, "t2": 0.7},
            cand_scores={"t1": 0.8, "t2": 0.3},
            envsByTask={"t1": ["loop_stalled"]},
            candidateEnvsByTask={"t2": ["false_completion"]},
        )
        assert report["unpredicted_regressions"] == ["t2"]
        assert report["unpredicted_regressions_by_environment"] == {"false_completion": ["t2"]}


class TestEvidenceReachesTheLedger:
    """整条接线：`_collect_failures` → `JudgeFailure.environments` → 台账归因回填。"""

    @pytest.mark.asyncio
    async def testRunPatchesAttributionWithEnvironmentGroups(self, tmp_path):
        from neurova.agent.capability_gap import GAP_LOOP_STALLED

        _result, record = await _runOnce(
            tmp_path, ["a", "b"], {"b": [GAP_LOOP_STALLED]},
            baseScores={"a": 0.2, "b": 0.3}, candScores={"a": 0.9, "b": 0.9})
        attr = record["attribution"]
        assert attr["claimed_environments"] == [GAP_LOOP_STALLED]
        assert attr["by_environment"][GAP_LOOP_STALLED] == {"predicted": 1, "hit": 1, "regressed": 0}
        assert attr["hit_rate"] == pytest.approx(1.0)
        assert attr["unpredicted_regressions"] == []

    @pytest.mark.asyncio
    async def testComparisonKeysAreNotTheTruncatedDisplayStrings(self, tmp_path):
        """台账展示用的 80 字截断串不能当比对键：超过 80 字的任务此前永远命中不了。"""
        from neurova.agent.capability_gap import GAP_LOOP_STALLED

        longTask = "长任务输入" * 30
        assert len(longTask) > 80
        _result, record = await _runOnce(
            tmp_path, [longTask], {longTask: [GAP_LOOP_STALLED]},
            baseScores={longTask: 0.2}, candScores={longTask: 0.9})
        assert record["predicted_tasks"] == [longTask[:80]], "展示面截断是本仓既有形状，不该被改掉"
        assert record["attribution"]["hits"] == [longTask]
        assert record["attribution"]["by_environment"][GAP_LOOP_STALLED] == {
            "predicted": 1, "hit": 1, "regressed": 0}


class TestReadoutIsConsumedButNotByJudgment:
    """读数有读者（提示段），但 accept/reject 判据不读它——要进判必须同批改判这一格。"""

    def testOldRecordsRenderByteIdentically(self):
        """改动前入账的记录（无环节字段）提示段逐字节不变——否则这次改动动了历史可读性。"""
        records = [{
            "ts": "T", "hypothesis": "H", "accepted": False, "reject_reason": "no_improvement",
            "attribution": {"hit_rate": 0.5, "hits": ["a"], "unpredicted_regressions": []},
        }]
        assert EvolutionLedger.render_for_prompt(records) == (
            "【编辑历史】以下假设已在评测中实测：\n"
            "已实测无效——**禁止重复提出**同类假设：\n"
            "- [T] H（拒绝原因: no_improvement）（命中率 1/2）")

    def testPromptNamesClaimedAndBrokenEnvironments(self):
        """新字段的读者就是这一段：写了没人读，按 AGENTS §2 属断点。"""
        records = [{
            "ts": "T", "hypothesis": "H", "accepted": False, "reject_reason": "no_improvement",
            "attribution": {
                "hit_rate": 0.0, "hits": [], "unpredicted_regressions": ["t9"],
                "claimed_environments": ["loop_stalled"],
                "by_environment": {"loop_stalled": {"predicted": 1, "hit": 0, "regressed": 1}},
                "unpredicted_regressions_by_environment": {"false_completion": ["t9"]},
            },
        }]
        rendered = EvolutionLedger.render_for_prompt(records)
        assert "声称环节 loop_stalled" in rendered
        assert "弄坏环节 false_completion×1" in rendered

    def testEmptyClaimsAddNothingToThePrompt(self):
        """模拟臂（恒空证据）不得在提示段里长出"声称环节"字样——空就是没证据，不是环节。"""
        records = [{
            "ts": "T", "hypothesis": "H", "accepted": False, "reject_reason": "no_improvement",
            "attribution": {"hit_rate": 1.0, "hits": ["a"], "unpredicted_regressions": [],
                            "claimed_environments": [], "by_environment": {},
                            "unpredicted_regressions_by_environment": {}},
        }]
        assert "环节" not in EvolutionLedger.render_for_prompt(records)

    @pytest.mark.asyncio
    async def testEnvironmentEvidenceDoesNotChangeAcceptDecision(self, tmp_path):
        """蕴涵格：同一批分数，带环节证据与不带环节证据的运行终态必须完全一致。"""
        from neurova.agent.capability_gap import GAP_LOOP_STALLED  # 证据面在场，判定面不取

        fields = ("rejected", "reject_reason", "deployed_text", "train_before",
                  "train_best", "holdout_before", "holdout_after", "iterations_run")
        withEvidence = await _runOnce(
            tmp_path / "with", ["a", "b"], {"b": [GAP_LOOP_STALLED]},
            baseScores={"a": 0.2, "b": 0.3}, candScores={"a": 0.9, "b": 0.9})
        withoutEvidence = await _runOnce(
            tmp_path / "without", ["a", "b"], {},
            baseScores={"a": 0.2, "b": 0.3}, candScores={"a": 0.9, "b": 0.9})
        assert [getattr(withEvidence[0], f) for f in fields] == \
            [getattr(withoutEvidence[0], f) for f in fields]
