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
                        lambda agent=None, *, config=None: _SentinelAgent(), raising=False)

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
