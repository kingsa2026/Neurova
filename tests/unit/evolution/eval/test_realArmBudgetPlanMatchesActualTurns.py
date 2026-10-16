"""真臂预算闸：计划数必须罩得住真实 `agent.run` 调度（P1-C 线·进化主路径切真臂）。

票面出处：`docs/08-research/designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md` §4 P1-C
与 `docs/04-plans/2026-10-16-任务级环节证据-attribution升级实施方案.md` §7-⑥。

为什么"计划数罩得住真实数"是本批的硬判据：预算闸是**花配额之前**的 422 依据，
计划函数若与 runner 的真实调度漂移，闸判的就是另一个数——放行时超支、拒绝时白拒，
两种坏都不出声。这里不按"看起来合理的算式"断言，而是**用一个计数执行器真跑一遍**，
再拿跑出来的数与计划逐格对齐（分支：单候选 / 多候选并行、锚定地板开关、heldout 有无、
空数据集）。计划是上界：装配体里的约束闸与泄漏闸会跳过候选，真实数只许 ≤ 计划数。
"""

import pytest

import neurova.evolution.eval.service as service
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner

MARKER = "IMPROVED"
BASELINE = "基础技能正文。" + "补充说明文字用于满足长度要求。" * 3


class _CountingAgent:
    """执行器替身：只数 `run` 被调了几次——预算计划的对照组。

    不带 `agent_ref`，因此 `isRealAgentTrajectoryExecutor` 判 False（本档量的是
    **调度形状**，臂真不真由端点档量）；计数即真实回合数，与真臂的 `turnsUsed` 同义。
    """

    def __init__(self):
        self.turns = 0

    async def run(self, *, skill_text, task_input):
        self.turns += 1
        return f"out::{task_input}"


class _ScriptedJudge:
    """基线侧一律 0.3、候选侧（正文含标记）一律 0.9：每一轮都有真增益，候选才会被评测。"""

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.9 if MARKER in skill_text else 0.3
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


async def _markerMutate(*, artifact_text, artifact_type, failures, **kw):
    """候选正文必须**每片各不同**：多变体轮按正文去重，产出相同文本会让 survivors
    缩水成 1，于是"计划罩得住真实"这格量的就不是并行轮的调度了。"""
    head = failures[0].task_input if failures else "-"
    return f"{artifact_text}\n{MARKER}#{len(failures)}:{head}"


def _examples(names):
    return [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]


def _dataset(train=4, val=2, holdout=3, heldout=0):
    return EvalDataset(
        train=_examples([f"tr{i}" for i in range(train)]),
        val=_examples([f"va{i}" for i in range(val)]),
        holdout=_examples([f"ho{i}" for i in range(holdout)]),
        heldout=_examples([f"hd{i}" for i in range(heldout)]),
    )


def _runner(config, agent):
    return SkillEvolutionRunner(config, judge=_ScriptedJudge(), agent=agent,
                                mutate=_markerMutate)


class TestPlanCoversCountedSchedule:
    """计划数罩得住真实调度，且每一项都能点名——漂移的闸比没有闸更坏。"""

    @pytest.mark.asyncio
    async def testSingleVariantRoundWithAnchor(self):
        config = EvolutionConfig(iterations=2, variants_per_round=1,
                                 anchor_floor_enabled=True, cost_rule_enabled=False)
        ds = _dataset()
        agent = _CountingAgent()
        await _runner(config, agent).run(
            baseline_text=BASELINE, artifact_type="skill", dataset=ds, iterations=2)
        plan = service.planRealArmTurns(ds, config, iterations=2)
        assert agent.turns <= plan["planned"], (agent.turns, plan)
        # 逐项相加就是总数：任何一项漏计（比如锚定那一遍），这里立刻对不上
        assert sum(plan["breakdown"].values()) == plan["planned"], plan
        assert agent.turns == plan["planned"], (agent.turns, plan)

    @pytest.mark.asyncio
    async def testAnchorDisabledCostsExactlyTheAnchorAway(self):
        configOn = EvolutionConfig(iterations=1, anchor_floor_enabled=True,
                                   cost_rule_enabled=False)
        configOff = EvolutionConfig(iterations=1, anchor_floor_enabled=False,
                                    cost_rule_enabled=False)
        ds = _dataset()
        onAgent, offAgent = _CountingAgent(), _CountingAgent()
        for cfg, agent in ((configOn, onAgent), (configOff, offAgent)):
            await _runner(cfg, agent).run(baseline_text=BASELINE, artifact_type="skill",
                                          dataset=ds, iterations=1)
            assert agent.turns == service.planRealArmTurns(ds, cfg, iterations=1)["planned"], (
                cfg.anchor_floor_enabled, agent.turns)
        # 锚定地板的代价正好是"留出集再跑一遍无技能臂"
        assert onAgent.turns - offAgent.turns == len(ds.holdout)

    @pytest.mark.asyncio
    async def testHeldoutEvidenceIsCharged(self):
        config = EvolutionConfig(iterations=1, anchor_floor_enabled=False,
                                 cost_rule_enabled=False)
        ds = _dataset(heldout=2)
        agent = _CountingAgent()
        await _runner(config, agent).run(baseline_text=BASELINE, artifact_type="skill",
                                         dataset=ds, iterations=1)
        plan = service.planRealArmTurns(ds, config, iterations=1)
        assert agent.turns == plan["planned"], (agent.turns, plan)
        assert plan["breakdown"]["heldoutEvidence"] == 4, plan

    @pytest.mark.asyncio
    async def testMultiVariantRoundChargesEverySurvivor(self):
        config = EvolutionConfig(iterations=2, variants_per_round=3,
                                 anchor_floor_enabled=False, cost_rule_enabled=False)
        ds = _dataset()
        agent = _CountingAgent()
        await _runner(config, agent).run(baseline_text=BASELINE, artifact_type="skill",
                                         dataset=ds, iterations=2)
        plan = service.planRealArmTurns(ds, config, iterations=2)
        assert agent.turns == plan["planned"], (agent.turns, plan)
        assert plan["breakdown"]["candidateEvaluations"] == 3 * len(ds.train + ds.val) * 2, plan

    @pytest.mark.asyncio
    async def testEmptyDatasetPlansNothing(self):
        config = EvolutionConfig()
        plan = service.planRealArmTurns(EvalDataset(), config, iterations=None)
        assert plan["planned"] == 0, plan
        agent = _CountingAgent()
        result = await _runner(config, agent).run(baseline_text=BASELINE,
                                                  artifact_type="skill",
                                                  dataset=EvalDataset())
        assert agent.turns == 0 and result.reject_reason == "empty_dataset"

    def testNoiseCalibrationIsChargedAsAnUpperBound(self):
        """校准是 service 侧的额外评测：默认不跑（noise_repeats=0）；跑就按
        repeats×判据集计上。命中指纹缓存时真实花费更少——所以计划是**上界**，
        这个语义要能被读出来，不能让人把"用了 8 / 计划 20"读成漏账。"""
        from neurova.evolution.eval.dataset import evaluation_split

        ds = _dataset()
        withCal = service.planRealArmTurns(
            ds, EvolutionConfig(iterations=1, noise_repeats=3, anchor_floor_enabled=False),
            iterations=1)
        assert withCal["breakdown"]["noiseCalibration"] == 3 * len(evaluation_split(ds)), withCal
        without = service.planRealArmTurns(
            ds, EvolutionConfig(iterations=1, anchor_floor_enabled=False), iterations=1)
        assert without["breakdown"]["noiseCalibration"] == 0, without


class TestBudgetGate:
    """闸只量"要不要花这笔配额"，不改判定、不降级执行面。"""

    def testDefaultBudgetRefusesTheDefaultFullRound(self):
        """默认配置一次整轮进化 ≈ 231 个回合，而默认预算远小于它——这是**有意的**：
        开真臂必须先自己把 iterations / 用例数收小，或显式把键调高。"""
        from neurova.evolution.evolution_settings import EvolutionSettings

        ds = EvalDataset(
            train=_examples([f"tr{i}" for i in range(10)]),
            val=_examples([f"va{i}" for i in range(5)]),
            holdout=_examples([f"ho{i}" for i in range(5)]),
        )
        config = EvolutionConfig()
        plan = service.planRealArmTurns(ds, config, iterations=None)
        assert plan["planned"] == 231, plan
        verdict = service.checkRealArmBudget(plan, EvolutionSettings().real_arm_max_agent_turns)
        assert verdict.allowed is False, verdict
        assert str(plan["planned"]) in verdict.reason, verdict.reason

    def testRaisedBudgetAllowsTheSamePlan(self):
        ds = _dataset()
        config = EvolutionConfig(iterations=1, anchor_floor_enabled=False)
        plan = service.planRealArmTurns(ds, config, iterations=1)
        verdict = service.checkRealArmBudget(plan, plan["planned"])
        assert verdict.allowed is True, verdict
        assert service.checkRealArmBudget(plan, plan["planned"] - 1).allowed is False

    def testVerdictNamesTheBreakdownNotJustATotal(self):
        """422 的理由要能指导怎么收：点名是哪一项吃掉的（迭代数×候选评测是大头）。"""
        ds = _dataset(train=6, val=3, holdout=2)
        config = EvolutionConfig(iterations=4, anchor_floor_enabled=False)
        plan = service.planRealArmTurns(ds, config, iterations=4)
        verdict = service.checkRealArmBudget(plan, 10)
        assert "candidateEvaluations" in verdict.breakdown, verdict
        assert verdict.planned > verdict.budget


class TestArmKindIsSingleSourced:
    """臂来源只有一处推导：`executorKind`，ab 报告与进化台账读数都取它。"""

    def testExecutorKindFollowsTheStructureNotAFlag(self):
        assert service.executorKind(_CountingAgent()) == "simulated"
        assert service.executorKind(None) == "simulated"

        class _RealArm:
            agent_ref = object()

            def declaresRealAgentTrajectory(self):
                return True

        assert service.executorKind(_RealArm()) == "real_agent"

    def testSimulatedExecutorReportsNoTurnCount(self):
        """没计数的臂：读数缺席（None），不是 0——0 会被读成"跑了 0 个回合"。"""
        assert service.realArmTurnsUsed(_CountingAgent(), kind="simulated") is None

    def testRealArmExecutorDeclaresItsCounter(self):
        from neurova.evolution.eval.ab_library import TextArmAgentExecutor

        assert callable(getattr(TextArmAgentExecutor, "turnsUsed", None)), (
            "真臂必须自带回合计数：预算闸的计划数要有对照组")


class TestBudgetKeyIsLiveConfig:
    """新键必须被读、被 clamp、被 PUT 收得到——挂个没人读的死旋钮是本禁令的反面。"""

    def testKeyExistsWithConservativeDefault(self):
        """默认档位就是裁定本身（不是实现细节）：默认只够一次小规模核验。"""
        from neurova.evolution.evolution_settings import EvolutionSettings

        assert EvolutionSettings().real_arm_max_agent_turns == 40

    def testBadValuesFallBackOrClampUp(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "s.json"))
        from neurova.evolution.evolution_settings import load_settings, update_settings

        for bad in ("abc", None, -7, 0):
            settings = update_settings(real_arm_max_agent_turns=bad)
            assert settings.real_arm_max_agent_turns >= 1, (bad, settings)
        assert update_settings(real_arm_max_agent_turns=500).real_arm_max_agent_turns == 500
        assert load_settings().real_arm_max_agent_turns == 500
