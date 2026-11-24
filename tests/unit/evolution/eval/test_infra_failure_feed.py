# -*- coding: utf-8 -*-
"""进化评测失败证据链的「器械故障≠任务失败」红灯测试（reference_af P0-②）。

契约：单例执行/判分异常（failed=True）的用例**没有该技能的质量证据**——
它们不得进入变异器的失败证据feed（`_collect_failures` / `_collect_failures_sorted`）。
旧形态按分数升序取最低 N 条，而器械故障恒 0.0 必然霸榜，把"评测崩了"喂成
"去修这个任务"的定向证据——拿器械故障当质量结论（Agent-S4 教训：refusing to
turn infrastructure output into zero fitness）。

边界：`eval_errors` 计数与例级三态门（unevidenced）不变——可见性不丢；
P2-9 的集合均分口径（0 分占满分母）是既有独立决策，本批不动。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


def _examples():
    return [
        EvalExample(task_input="boom", expected_behavior="输出要点"),
        EvalExample(task_input="low", expected_behavior="输出要点"),
        EvalExample(task_input="high", expected_behavior="输出要点"),
    ]


def _runner_with_infra_on_boom():
    """执行器对 boom 任务崩溃（器械故障）；判分器给 low=0.2、high=1.0。"""

    class _Agent:
        async def run(self, *, skill_text: str, task_input: str) -> str:
            if task_input == "boom":
                raise RuntimeError("executor socket died")
            return "正常输出"

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = {"low": 0.2, "high": 1.0}.get(task_input, 0.5)
        return FitnessScore(correctness=c, procedure_following=c,
                            conciseness=c, feedback="")

    return SkillEvolutionRunner(EvolutionConfig(), judge=judge, agent=_Agent())


@pytest.mark.asyncio
async def testSortedFeedExcludesInfraFailedCases():
    runner = _runner_with_infra_on_boom()
    feed = await runner._collect_failures_sorted("技能正文", _examples(), "skill")
    names = [f.task_input for f in feed]
    assert "boom" not in names, "器械故障（执行器崩溃）混进了失败证据feed"
    assert "low" in names, "真实低分用例必须在feed里"


@pytest.mark.asyncio
async def testSingleVariantFeedExcludesInfraFailedCases():
    runner = _runner_with_infra_on_boom()
    feed = await runner._collect_failures("技能正文", _examples(), "skill")
    names = [f.task_input for f in feed]
    assert "boom" not in names, "器械故障混进了单变体失败证据feed"
    assert "low" in names


@pytest.mark.asyncio
async def testAllInfraFailuresFeedIsEmpty():
    """全部用例器械崩：feed 如实为空（无证据≠有失败证据），不喂幻影失败。"""

    class _DeadAgent:
        async def run(self, *, skill_text: str, task_input: str) -> str:
            raise TimeoutError("vm never came up")

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        return FitnessScore(correctness=1.0, procedure_following=1.0,
                            conciseness=1.0, feedback="")

    runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge, agent=_DeadAgent())
    feed = await runner._collect_failures("技能正文", _examples(), "skill")
    assert feed == []


@pytest.mark.asyncio
async def testInfraFailuresStillCountedInEvalErrors():
    """可见性不丢：被排除出feed的器械故障仍进 eval_errors 计数。"""
    runner = _runner_with_infra_on_boom()
    await runner._collect_failures_sorted("技能正文", _examples(), "skill")
    assert runner._run_eval_errors == 1
