# -*- coding: utf-8 -*-
"""双臂试评的真 agent 执行器与"执行面来源"外露（票面 2026-10-09 Task 4 / D2 落地面）。

三件事，各自对应一类会静默骗人的形态：
1. `executor_kind` 必须由**真正被拿去执行的那个对象**推导——写成常量就能在
   模拟面上报"真轨迹"，而审批人无从分辨；
2. 真臂必须真经过 `agent.chat(..., save_memory=False)`，且本轮带着**自己那一臂**的
   候选正文（覆盖槽排在注入路径最前，否则两臂拿到同一份正文，比出假 0 差）；
3. 来源标注必须两条返回路径都在，且不合并——把模拟分与真轨迹分并进一栏，
   不可逆的是解释而不是数据。
"""

import pytest

from neurova.core import turn_context
from neurova.evolution.eval.ab_library import TextArmAgentExecutor
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.service import SkillEvolutionService

SKILL_NAME = "sk-eval"
BASELINE = "基线正文：先列要点。"
CANDIDATE = "候选正文：只给代码。"


class _AgentStub:
    """真 agent 替身：把收到的参数与本轮覆盖槽读数留下，供判据回读。"""

    def __init__(self):
        self.calls = []
        self.overrideSeen = []

    async def chat(self, user_input, **kwargs):
        self.calls.append({"user_input": user_input, **kwargs})
        self.overrideSeen.append(
            turn_context.get_turn_skill_text_override(SKILL_NAME))
        return {"text": f"out::{user_input}", "audio_path": None, "audio_data": None}


def _dataset():
    items = [EvalExample(task_input=f"t{i}", expected_behavior="要点") for i in range(2)]
    return EvalDataset(train=list(items), val=[], holdout=list(items), heldout=list(items))


def _judgeKeyedByBody():
    """判分器按**正文**给分（不是按 output）：候选正文进来了才会得高分。"""
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.9 if skill_text == CANDIDATE else 0.2
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")

    return judge


def _executorFor(agent):
    return TextArmAgentExecutor(agent, skill_name=SKILL_NAME)


@pytest.mark.asyncio
async def test_realArmRunsAChatTurnWithSaveMemoryFalse(tmp_path):
    """真臂必须经 `chat`，且必须带 `save_memory=False`（Task 3 那道闸的触发端）。"""
    agent = _AgentStub()
    svc = SkillEvolutionService("ab-agent", base_dir=tmp_path / "evo")
    report = await svc.ab_compare(
        baseline_text=BASELINE, candidate_text=CANDIDATE, dataset=_dataset(),
        config=EvolutionConfig(), agent=_executorFor(agent), judge=_judgeKeyedByBody(),
    )

    assert agent.calls, "真臂根本没跑 agent 回合"
    assert len(agent.calls) == 4, f"两臂×两例应有 4 次回合，实得 {len(agent.calls)}"
    assert {c.get("save_memory") for c in agent.calls} == {False}, (
        f"评测回合没关写入：{[c.get('save_memory') for c in agent.calls]}")
    assert all(f"${SKILL_NAME}" in c["user_input"] for c in agent.calls), (
        "任务文本没带 $mention，候选正文根本进不了本轮")


@pytest.mark.asyncio
async def test_eachArmCarriesItsOwnCandidateBody(tmp_path):
    """臂内读数必须一份对一份：基线臂读基线正文，候选臂读候选正文。"""
    agent = _AgentStub()
    svc = SkillEvolutionService("ab-agent", base_dir=tmp_path / "evo")
    report = await svc.ab_compare(
        baseline_text=BASELINE, candidate_text=CANDIDATE, dataset=_dataset(),
        config=EvolutionConfig(), agent=_executorFor(agent), judge=_judgeKeyedByBody(),
    )

    assert agent.overrideSeen == [BASELINE, BASELINE, CANDIDATE, CANDIDATE], (
        f"两臂正文串行：{agent.overrideSeen}")
    assert report["executor_kind"] == "real_agent", report
    assert report["baseline_avg"] == pytest.approx(0.2)
    assert report["candidate_avg"] == pytest.approx(0.9)
    assert len(report["per_task"]) == 2


@pytest.mark.asyncio
async def test_kindIsDerivedFromTheExecutorThatActuallyRan(tmp_path, monkeypatch):
    """反谎：`executor_kind` 必须等于对**当次执行器**的能力判定，不是写死的字面量。

    判法：注入真轨迹形态的执行器，同时把能力判据桩成 False ⇒ 报告必须跟着说
    "simulated"。反过来（写死 kind 或按"有没有传 agent"猜）都会在这一格红。
    """
    from neurova.evolution.eval import service as evalService

    monkeypatch.setattr(evalService, "isRealAgentTrajectoryExecutor",
                        lambda executor: False, raising=False)
    svc = SkillEvolutionService("ab-agent", base_dir=tmp_path / "evo")
    report = await svc.ab_compare(
        baseline_text=BASELINE, candidate_text=CANDIDATE, dataset=_dataset(),
        config=EvolutionConfig(), agent=_executorFor(_AgentStub()),
        judge=_judgeKeyedByBody(),
    )
    assert report["executor_kind"] == "simulated", report


def _judgeKeyedOnOutput():
    """按**输出**给分：回显型执行器会命中，真回合不会——用来量"两个面量的不是同一件事"。"""
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.9 if output == CANDIDATE else 0.2
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")

    return judge


@pytest.mark.asyncio
async def test_simulatedArmIsLabelledAndNeverMerged(tmp_path):
    """模拟面必须自己标自己，且两面量的是不同的事——并进一栏就是解释污染。"""
    class _Offline:
        async def run(self, *, skill_text, task_input):
            return skill_text

    svc = SkillEvolutionService("ab-agent", base_dir=tmp_path / "evo")
    kwargs = dict(baseline_text=BASELINE, candidate_text=CANDIDATE, dataset=_dataset(),
                  config=EvolutionConfig(), judge=_judgeKeyedOnOutput())
    simReport = await svc.ab_compare(agent=_Offline(), **kwargs)
    realReport = await svc.ab_compare(agent=_executorFor(_AgentStub()), **kwargs)

    assert simReport["executor_kind"] == "simulated"
    assert realReport["executor_kind"] == "real_agent"
    # 同一对正文，两面给出不同的差：回显面把"正文被复读"当高分，真轨迹面不会。
    # 这正是必须分栏的理由——合并成一个数就分不清是谁的功劳。
    assert simReport["delta"] != realReport["delta"], (simReport, realReport)

    # 跑过真臂之后再来一发模拟臂，标注不得被上一次的结果带跑（无跨调用状态泄漏）
    again = await svc.ab_compare(agent=_Offline(), **kwargs)
    assert again["executor_kind"] == "simulated", again


@pytest.mark.asyncio
async def test_emptyTaskSplitStillCarriesTheLabel(tmp_path):
    """空任务集那条早退路径也必须带来源标注，否则前端拿到残缺形状会猜。"""
    empty = EvalDataset(train=[], val=[], holdout=[], heldout=[])
    svc = SkillEvolutionService("ab-agent", base_dir=tmp_path / "evo")
    report = await svc.ab_compare(
        baseline_text=BASELINE, candidate_text=CANDIDATE, dataset=empty,
        config=EvolutionConfig(), agent=_executorFor(_AgentStub()),
        judge=_judgeKeyedByBody(),
    )
    assert report["task_split"] == "none"
    assert report["executor_kind"] == "real_agent", report


def test_mentionUnsafeSkillNameIsRefusedNotSilentlySkipped():
    """名字组不出 $mention 时必须当场拒——静默空跑会给出"两臂同文"的假 0 差。"""
    for bad in ("web search", "技能 名", ""):
        with pytest.raises(ValueError):
            TextArmAgentExecutor(_AgentStub(), skill_name=bad)


def test_executorDeclaresItsOwnCapabilityShape():
    """能力由结构推导（`agent_ref` + 显式声明），缺一即不算真轨迹。"""
    from neurova.evolution.eval.service import isRealAgentTrajectoryExecutor

    executor = _executorFor(_AgentStub())
    assert getattr(executor, "agent_ref", None) is not None
    assert executor.declaresRealAgentTrajectory() is True
    assert isRealAgentTrajectoryExecutor(executor) is True
    assert isRealAgentTrajectoryExecutor(
        type("NoAgentRef", (), {"declaresRealAgentTrajectory": lambda self: True})()) is False
