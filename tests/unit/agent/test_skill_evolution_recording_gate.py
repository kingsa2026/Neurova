"""技能进化采集端的注册门（工单 013）。

缺陷：`agent_core.py:1582` 的注册门是

    if self.tool_memory and self._skill_registry:
        self._skill_registry.register_event_callback(SkillEvent.POST_EXECUTE, ...)

`a.tool_memory` 在 `agent_core.py:590` 先置 None，仅 `ToolMemoryIntegration`
构造成功（`:600`，包在 try/except 里，失败只 warning）才赋值。
于是"工具记忆子系统可用性"这一件事，静默关掉了四条**与它无关**的进化记账：
`skill_improver.record_usage`、`SkillService.record_skill_usage`、
`skill_experience.record_usage`、`genetic_engine.record_reuse`。
真正需要 tool_memory 的只有 handler 末段，而那里 `:1692` 已自带
`if not self.tool_memory: return` 守卫 —— 外层这颗 AND 门是多余的。

实测（真 Agent，`enable_memory=False`）：`tool_memory is None`、
`init_router()` 正常返回、注册表里有 3 个技能，但
`_event_callbacks['after_execute']` 长度为 **0**。

本文件用真 Agent + 真 `init_router` + 真 `SkillRegistry.execute_skill` 驱动，
只在四个下游记账口放探针 —— 验的是"接线"，不是各记账器自身的行为。
"""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from neurova.agent_core import Agent
from neurova.skill_system import Skill

# `SkillResult` 有两套同名类：`neurova.skill_system` 包导出的是
# `skills/executor.SkillResult(success, output, error, metadata)`，
# 而 `Skill`/`SkillRegistry` 来自 standalone 模块，其
# `SkillResult(success, data, error, metadata, execution_time)` 字段不同
# （ADR 0011 统一了 SkillRegistry，未统一 SkillResult）。
# 探针技能必须返回与 SkillRegistry.execute_skill 同一命名空间的那个。
_SkillResult = getattr(sys.modules[Skill.__module__], "SkillResult")

PROBE_SKILL_ID = "skill_probe_alpha_0123456789abcdef"
PROBE_SKILL_NAME = "probe_alpha"


class _ProbeSkill(Skill):
    """最小可执行探针技能：只证明"这次执行发生了"，不做任何真实工作。

    显式携带与 name 不同的 skill_id —— 否则本文件会重蹈
    tests/unit/skills/test_improvement_persistence.py:47-52 的 id==name 盲区。
    """

    def __init__(self):
        super().__init__(name=PROBE_SKILL_NAME, description="闭环采集探针")
        self.skill_id = PROBE_SKILL_ID
        self.config = {"tool_sequence": ["read_file", "write_file"]}

    async def execute(self, params, context=None):
        return _SkillResult(success=True, data={"probe": True}, execution_time=0.012)


class _Recorder:
    """记账探针：记录每一次调用的入参。"""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace()


@pytest.fixture
def wired_agent(tmp_path, monkeypatch):
    """构造真 Agent（tool_memory 天然缺席）并把四个记账口换成探针。"""
    improver = _Recorder()
    service_records = _Recorder()
    experience_records = _Recorder()
    genetic = _Recorder()

    import neurova.evolution.skill_experience as skill_experience
    import neurova.evolution.skill_improver as skill_improver
    import neurova.skills.skill_service as skill_service

    monkeypatch.setattr(skill_improver, "get_skill_improver", lambda **kw: SimpleNamespace(
        record_usage=improver))
    monkeypatch.setattr(skill_service, "SkillService", lambda **kw: SimpleNamespace(
        record_skill_usage=service_records, list_skills=lambda *a, **k: []))
    monkeypatch.setattr(skill_experience, "get_skill_experience_store", lambda: SimpleNamespace(
        record_usage=experience_records))

    agent = Agent(workspace_path=str(tmp_path), enable_memory=False)
    # 前置断言：本切片的前提就是 tool_memory 缺席
    assert getattr(agent, "tool_memory", "missing") is None, (
        "用例前提失效：tool_memory 不再为 None，本用例不再能证明解耦")
    agent.evolution = SimpleNamespace(genetic_engine=SimpleNamespace(record_reuse=genetic))
    agent.init_router()

    return SimpleNamespace(
        agent=agent,
        improver=improver,
        service=service_records,
        experience=experience_records,
        genetic=genetic,
    )


def _execute_one_skill(agent):
    skill = _ProbeSkill()
    agent._skill_registry.register(skill)
    result = asyncio.run(agent._skill_registry.execute_skill(PROBE_SKILL_NAME, {}))
    assert result.success is True, f"探针技能本身执行失败，用例前提不成立：{result.error}"
    return skill


def test_skill_usage_reaches_improver_without_tool_memory(wired_agent):
    """tool_memory 缺席时，技能执行仍必须把使用数据交给改进器。

    根因位置：`agent_core.py:1582` 的 `if self.tool_memory and self._skill_registry`。
    """
    _execute_one_skill(wired_agent.agent)

    assert wired_agent.improver.calls, (
        "进化数据采集端被 tool_memory 的可用性静默关停："
        " tool_memory=None 时 POST_EXECUTE 回调从未注册，"
        " AutoSkillImprover 因此永远收不到使用记录 → 每轮 0 提案")


def test_all_four_accountings_are_reached_without_tool_memory(wired_agent):
    """四条记账各自独立，不得有任何一条再依赖 tool_memory。

    放大视角：同一颗 AND 门绑住了四个互不相关的消费方，必须一次全解。
    """
    _execute_one_skill(wired_agent.agent)

    assert wired_agent.improver.calls, "skill_improver.record_usage 未触达"
    assert wired_agent.service.calls, "SkillService.record_skill_usage 未触达"
    assert wired_agent.experience.calls, "skill_experience_store.record_usage 未触达"
    assert wired_agent.genetic.calls, "genetic_engine.record_reuse 未触达"


def test_recorded_identity_is_the_skill_id_not_the_name(wired_agent):
    """记账里落的身份必须是 skill_id（与 name 不同），与 handler 的单源解析一致。"""
    _execute_one_skill(wired_agent.agent)

    _args, kwargs = wired_agent.improver.calls[-1]
    assert kwargs.get("skill_id") == PROBE_SKILL_ID, (
        f"记账应使用 skill_id 单源身份，实际 {kwargs.get('skill_id')!r}")
    assert kwargs.get("success") is True


def test_failed_execution_is_still_recorded(wired_agent):
    """失败也要记 —— 改进提案的判据是失败率，只记成功就没有失败率。"""
    class _FailingSkill(_ProbeSkill):
        async def execute(self, params, context=None):
            return _SkillResult(success=False, error="探针故意失败")

    agent = wired_agent.agent
    skill = _FailingSkill()
    agent._skill_registry.register(skill)
    asyncio.run(agent._skill_registry.execute_skill(PROBE_SKILL_NAME, {}))

    assert wired_agent.improver.calls, "失败执行同样必须被采集"
    _args, kwargs = wired_agent.improver.calls[-1]
    assert kwargs.get("success") is False, "失败轮次不得被记成成功（会污染改进判据方向）"


def test_wiring_without_skill_registry_does_not_break_router(tmp_path):
    """注册表缺席时无处可注册，但不得抛错拖垮 init_router。"""
    agent = Agent(workspace_path=str(tmp_path), enable_memory=False)
    agent._skill_registry = None

    router = agent.init_router()

    assert router is not None, "SkillRegistry 缺席不得使 init_router 失败"


def test_wiring_reports_no_registry_as_unregistered():
    """装配函数须把"没接上"作为返回值暴露出来，供调用方判据消费。"""
    from neurova.evolution.skill_recording import wire_skill_evolution_recording

    agent = SimpleNamespace(_skill_registry=None, config=SimpleNamespace(name="probe"))

    assert wire_skill_evolution_recording(agent) is False


def test_wiring_registers_post_execute_handler_without_tool_memory():
    """注册的唯一前置是注册表；handler 身份必须原样传进去。"""
    from neurova.evolution.skill_recording import wire_skill_evolution_recording
    from neurova.skill_system import SkillEvent

    captured: dict = {}
    registry = SimpleNamespace(
        register_event_callback=lambda event_type, handler: captured.__setitem__(event_type, handler))
    handler = lambda *a, **k: None
    agent = SimpleNamespace(
        _skill_registry=registry, config=SimpleNamespace(name="probe"),
        tool_memory=None, _on_skill_post_execute=handler)

    assert wire_skill_evolution_recording(agent) is True
    assert captured.get(SkillEvent.POST_EXECUTE) is handler, (
        "POST_EXECUTE 必须绑到 Agent 的采集 handler 上")
