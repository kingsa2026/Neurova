"""技能执行证据（N2）：后置事件必须携带入参与产物，采集端落库非空摘要。

红测锚点：
- `SkillRegistry.execute_skill` 的 POST_EXECUTE 目前只发 result，handler 拿不到 params；
- 旧的两参回调 `lambda skill, result` 必须继续可用（不能为了带证据破坏契约）。
"""

from types import SimpleNamespace

import pytest

from neurova.skill_system.core import Skill, SkillEvent, SkillRegistry, SkillResult


class _EchoSkill(Skill):
    def __init__(self) -> None:
        super().__init__(name="echo", description="echo input")

    async def execute(self, params, context=None):
        return SkillResult(success=True, data={"echo": (params or {}).get("q", "")})


@pytest.mark.asyncio
async def test_afterExecuteCarriesParamsAndContextToKwargsHandler():
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    seen = {}

    def handler(skill, result, **kwargs):
        seen["skill"] = skill
        seen["result"] = result
        seen["params"] = kwargs.get("params")
        seen["context"] = kwargs.get("context")

    registry.register_event_callback(SkillEvent.POST_EXECUTE, handler)

    result = await registry.execute_skill("echo", {"q": "北京"}, {"session": "s1"})

    assert result.success is True
    assert seen["skill"].name == "echo"
    assert seen["params"] == {"q": "北京"}
    assert seen["context"] == {"session": "s1"}


@pytest.mark.asyncio
async def test_afterExecuteKeepsTwoArgumentHandlerWorking():
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    seen = []
    registry.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: seen.append(r))

    result = await registry.execute_skill("echo", {"q": "x"})

    assert seen == [result]


def test_summarizeSkillIoSerializesBoundsAndRedacts():
    from neurova.evolution.skill_recording import summarizeSkillIO

    text = summarizeSkillIO({"password": "supersecret", "q": "北京"})
    assert "supersecret" not in text
    assert "北京" in text

    long_text = summarizeSkillIO("x" * 5000)
    assert len(long_text) <= 2000
    assert long_text.endswith("[truncated]")


def test_postExecuteRecordsInputAndOutputSummaries(monkeypatch):
    import neurova.agent_core as ac

    captured = {}

    def record_usage(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver",
        lambda: SimpleNamespace(record_usage=record_usage),
    )
    monkeypatch.setattr(
        "neurova.skills.library_service.agentLibrary",
        lambda *a, **k: SimpleNamespace(record_skill_usage=lambda *a, **k: None),
    )
    monkeypatch.setattr(
        "neurova.evolution.skill_experience.get_skill_experience_store",
        lambda: SimpleNamespace(record_usage=lambda *a, **k: None),
    )

    agent = object.__new__(ac.Agent)
    agent.config = SimpleNamespace(agent_id="default")
    agent.tool_memory = None
    agent.evolution = None
    agent._current_user_input = "帮我查北京天气"

    skill = SimpleNamespace(name="weather", config={})
    result = SimpleNamespace(
        success=True,
        execution_time=0.1,
        error="",
        metadata={},
        data={"temperature": 20},
    )

    agent._on_skill_post_execute(
        skill, result, params={"city": "北京"}, context={"session": "s1"}
    )

    assert "北京" in captured.get("input_summary", "")
    assert "20" in captured.get("output_summary", "")
