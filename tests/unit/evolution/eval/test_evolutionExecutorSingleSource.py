# -*- coding: utf-8 -*-
"""生产装配路径的执行器必须来自**同一个接缝**（教义第 6 条，票面 2026-10-09 Task 1）。

为什么值得钉这一格，而不是把它当"两处写法像"的观感问题：`evolve()` 与 `ab_compare()`
过去各写一遍 `agent or SimulatedAgent(...)`。两条都自称"评测"，但接真轨迹时只会改到
其中一条，另一条静默留在旧语义上。本仓已实测过它的代价——`agent=None` 的回落会接上
**真**多模型客户端，三个用例因此真花 LLM 配额并把整目录跑测挂死
（来历见 `tests/unit/evolution/eval/conftest.py` 首段）。

判据打在"到底谁被拿去执行"上：脚本判分器按 **output** 打分，接缝给的替身返回固定标记。
绕过接缝就落到 `SimulatedAgent`，本目录的出站闸当场炸——那就是行为红，不是形似红。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore

MARK = "SENTINEL-EXECUTOR-OUTPUT"
BASELINE = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2


class _SentinelAgent:
    """接缝替身：输出恒为该标记，判分器据此认出"被执行的是谁"。"""

    async def run(self, *, skill_text, task_input):
        return MARK


def _judgeKeyedOnOutput():
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.8 if output == MARK else 0.2
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")

    return judge


def _dataset():
    items = [EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(3)]
    return EvalDataset(train=list(items), val=[], holdout=list(items))


async def _markerMutate(*, artifact_text, artifact_type, failures, **kw):
    """脚本变异体：不传 mutate 时 runner 会自建 ReflectiveMutator——那才是真 LLM。"""
    return artifact_text + "\nIMPROVED"


class _OnlineAgent:
    """在线 agent 替身：接缝 auto 语义下应被包成真轨迹执行器去跑真回合。

    `chat` 与生产 agent 同名同形（TextArmAgentExecutor.run 调的就是它），
    返回恒为标记串，判分器据此认出"被执行的是谁"。不触任何 LLM 客户端，
    本目录出站闸的语义（离线测试不发真请求）原样成立。
    """

    def __init__(self):
        self.chatCalls = 0

    async def chat(self, message, **kwargs):
        self.chatCalls += 1
        return MARK


@pytest.fixture
def onlineDefaultAgent():
    """把替身挂进生产装配位的默认 agent 槽；teardown 还原，防串味到后续用例。"""
    from neurova.api.endpoints import set_app_state

    agent = _OnlineAgent()
    set_app_state({"agents": {"default": agent}})
    yield agent
    set_app_state(None)


def test_defaultAssemblyResolvesOnlineAgentIntoRealTrajectoryExecutor(onlineDefaultAgent):
    """A1 红灯：默认装配路径拿到在线 agent 时必须产出真轨迹执行器（不再回落模拟面）。

    这格翻绿 ⇒ `probeRealTrajectoryExecutor` 结构翻真 ⇒ §8 前置 2 闭环，
    phase 1→2 晋升不再被逐字点名否决。
    """
    from neurova.evolution.eval.service import (
        EXECUTOR_KIND_REAL,
        executorKind,
        isRealAgentTrajectoryExecutor,
        resolveEvolutionExecutor,
    )

    executor = resolveEvolutionExecutor(None, skill_name="probe_skill")
    assert isRealAgentTrajectoryExecutor(executor) is True, (
        "在线 agent 在位，默认装配路径却仍回落模拟面——前置 2 永远关不上")
    assert executor.agent_ref is onlineDefaultAgent, "真臂执行器没绑到装配位那个 agent"
    assert executorKind(executor) == EXECUTOR_KIND_REAL


def test_offlineAssemblyStillFallsBackToIsolatedStub():
    """反向格（历史病）：离线/无在线 agent 的装配必须仍走隔离替身。

    `agent=None` 的回落一旦接上真多模型客户端，三个用例真花配额并把整目录跑测挂死
    （conftest 首段的实测代价）。改回落语义时这一格不许翻。
    """
    from neurova.api.endpoints import set_app_state
    from neurova.evolution.eval.service import (
        SimulatedAgent,
        isRealAgentTrajectoryExecutor,
        resolveEvolutionExecutor,
    )

    set_app_state(None)  # 显式离线态，不依赖用例顺序
    executor = resolveEvolutionExecutor(None, skill_name="probe_skill")
    assert isinstance(executor, SimulatedAgent), (
        "离线测试态必须仍走隔离替身——接真轨迹的历史病就是从这里烧配额的")
    assert isRealAgentTrajectoryExecutor(executor) is False


def test_unmentionableSkillNameFallsBackToSimulated(onlineDefaultAgent):
    """技能名组不出 $mention 时，本轮装配诚实退回模拟面（arm 读数照实记 simulated）。"""
    from neurova.evolution.eval.service import SimulatedAgent, resolveEvolutionExecutor

    executor = resolveEvolutionExecutor(None, skill_name="bad name!")
    assert isinstance(executor, SimulatedAgent)


@pytest.mark.asyncio
async def test_evolveAutoArmRunsRealAgentTurnsWithinBudget(
        tmp_path, monkeypatch, onlineDefaultAgent):
    """行为格：evolve 的 auto 臂拿到在线 agent 后要真跑 agent 回合，臂来源读 real_agent。

    预算帽 monkeypatch 成 40（默认档）——本用例数据集的计划回合 ≤40，闸放行。
    """
    from neurova.evolution.eval import service as evalService

    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    monkeypatch.setattr(evalService, "realArmMaxTurns", lambda: 40, raising=False)
    svc = evalService.SkillEvolutionService("default", base_dir=tmp_path / "evo")
    result, _ = await svc.evolve(
        skill_id="s1", skill_text=BASELINE, dataset=_dataset(),
        judge=_judgeKeyedOnOutput(), mutate=_markerMutate,
        config=EvolutionConfig(iterations=1, min_improvement=0.0),
    )

    assert result.executorKind == "real_agent", (
        "auto 臂拿到在线 agent 却仍走模拟面——台账臂来源会以模拟数字冒充线上证据")
    assert (result.agentTurnsUsed or 0) >= 1, "真臂回合计数为空——计数器没装上"
    assert result.real_arm_fallback == "", "预算内运行不该带回落标注"
    assert onlineDefaultAgent.chatCalls >= 1, "执行器包了真臂却没真跑 agent 回合"


@pytest.mark.asyncio
async def test_evolveAutoArmOverBudgetFallsBackHonestly(
        tmp_path, monkeypatch, onlineDefaultAgent):
    """预算闸：超帽的 auto 臂必须诚实回落模拟面并标注原因，不许静默烧真回合。

    这是接缝接真轨迹后的新暴露面：后台 evolve(agent=None) 在在线 agent 在位时会拿到
    真臂，没有这道闸，后台路径就绕过了 API 侧的预算门（§8 前置 2 落地票面的教训延伸）。
    """
    from neurova.evolution.eval import service as evalService

    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    monkeypatch.setattr(evalService, "realArmMaxTurns", lambda: 1, raising=False)
    # 回落臂是裸 SimulatedAgent（走 llm_router）——本目录出站闸拦真客户端，
    # 这里换成本地假客户端只喂标记串，闸的语义（不发真请求）原样成立。
    from neurova.llm import multi_model_client as mmc

    class _FakeClient:
        async def chat(self, messages, model=None):
            return {"success": True, "response": MARK}

    monkeypatch.setattr(mmc, "get_multi_model_client", lambda: _FakeClient())
    svc = evalService.SkillEvolutionService("default", base_dir=tmp_path / "evo")
    result, _ = await svc.evolve(
        skill_id="s1", skill_text=BASELINE, dataset=_dataset(),
        judge=_judgeKeyedOnOutput(), mutate=_markerMutate,
        config=EvolutionConfig(iterations=1, min_improvement=0.0),
    )

    assert result.executorKind == "simulated", "超预算运行不该跑真臂"
    assert result.real_arm_fallback == "budget_exceeded", (
        "超预算回落必须带原因出街——静默降级就是教义第 2 条的表面抹除")
    assert result.agentTurnsUsed is None, "回落成模拟臂后不该再报真臂回合数"
    assert onlineDefaultAgent.chatCalls == 0, "超预算回落不能花真回合"


def test_injectedExecutorPassesThroughUnchanged():
    from neurova.evolution.eval.service import resolveEvolutionExecutor

    injected = _SentinelAgent()
    assert resolveEvolutionExecutor(injected) is injected, "注入的执行器被换掉了"


def test_defaultExecutorFollowsTheConfigJudgeModel():
    from neurova.evolution.eval.service import resolveEvolutionExecutor

    executor = resolveEvolutionExecutor(None, config=EvolutionConfig(judge_model="m-x"))
    assert getattr(executor, "model", "") == "m-x", (
        "默认执行器没按当次配置的 judge_model 构造——接缝把配置写死了")


@pytest.mark.asyncio
async def test_evolveTakesItsExecutorFromTheSeam(tmp_path, monkeypatch):
    """`evolve(agent=None)` 的执行器必须由接缝给出。"""
    from neurova.evolution.eval import service as evalService

    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    monkeypatch.setattr(evalService, "resolveEvolutionExecutor",
                        lambda agent=None, *, config=None, skill_name="", agent_id="":
                        _SentinelAgent(), raising=False)

    svc = evalService.SkillEvolutionService("agent-seam", base_dir=tmp_path / "evo")
    result, _ = await svc.evolve(
        skill_id="s1", skill_text=BASELINE, dataset=_dataset(),
        judge=_judgeKeyedOnOutput(), mutate=_markerMutate,
        config=EvolutionConfig(iterations=1, min_improvement=0.0),
    )

    assert result.holdout_before == pytest.approx(0.8), (
        f"evolve 没走接缝给的执行器（留出基线分 {result.holdout_before}，"
        "0.2 说明落到别处的回落上了）")


@pytest.mark.asyncio
async def test_abCompareTakesItsExecutorFromTheSeam(tmp_path, monkeypatch):
    """`ab_compare(agent=None)` 同一条契约——它今天绕过接缝，正是双源的那一格。"""
    from neurova.evolution.eval import service as evalService

    monkeypatch.setattr(evalService, "resolveEvolutionExecutor",
                        lambda agent=None, *, config=None: _SentinelAgent(), raising=False)

    svc = evalService.SkillEvolutionService("agent-seam-ab", base_dir=tmp_path / "evo")
    report = await svc.ab_compare(
        baseline_text=BASELINE, candidate_text=BASELINE + "\n改一句",
        dataset=_dataset(), config=EvolutionConfig(), judge=_judgeKeyedOnOutput(),
    )

    assert report["baseline_avg"] == pytest.approx(0.8), (
        f"ab_compare 没走接缝给的执行器（基线臂均分 {report['baseline_avg']}）")


def test_offlineProxiesAreNotMistakenForRealTrajectory():
    """反误认：三种离线/单轮执行器都不算"真跑 agent 回合"。

    这一格决定 §8 前置 2 会不会被白送——替身被认成同域，自动执行档的门槛就形同虚设。
    """
    from neurova.evolution.eval.runner import _DefaultAgent
    from neurova.evolution.eval.service import (
        SimulatedAgent, isRealAgentTrajectoryExecutor, resolveEvolutionExecutor,
    )

    assert isRealAgentTrajectoryExecutor(None) is False
    assert isRealAgentTrajectoryExecutor(_DefaultAgent()) is False
    assert isRealAgentTrajectoryExecutor(SimulatedAgent()) is False
    assert isRealAgentTrajectoryExecutor(_SentinelAgent()) is False, (
        "注入接缝的替身被当成真轨迹——旗标从此可以被测试自己刷真")
    assert isRealAgentTrajectoryExecutor(resolveEvolutionExecutor(None)) is False, (
        "生产默认回落被判成真轨迹")


def test_capabilityIsDerivedFromBothHalvesNotFromAFlag():
    """反空转：两半各拆掉一次都必须回 False——只留一处声明就是可以撒谎的地方。"""
    from neurova.evolution.eval.service import isRealAgentTrajectoryExecutor

    class _Real:
        agent_ref = object()

        def declaresRealAgentTrajectory(self):
            return True

    assert isRealAgentTrajectoryExecutor(_Real()) is True

    onlyDeclaration = type("D", (), {"declaresRealAgentTrajectory": lambda self: True})()
    onlyAgentRef = type("A", (), {"agent_ref": object()})()
    assert isRealAgentTrajectoryExecutor(onlyDeclaration) is False, "没有 agent_ref 也算真轨迹"
    assert isRealAgentTrajectoryExecutor(onlyAgentRef) is False, "持有 agent_ref 就默认算真轨迹"
