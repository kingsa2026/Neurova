"""SkillRegistry 执行/事件/枚举能力测试（对齐 ADR 0011 class A 实现）。

原测试面向被否决的"套2" SkillRegistry（register_executor、list_skills_as_dict、
list_skills 返回带 id/status/keywords 的 Skill、事件名 skill_executing、未注册抛
ValueError）。这些在 class A 中均无对应物。此处重写为 class A 的真实能力：
- execute_skill 为 async 函数
- 事件通过 register_event_callback(event_type, handler) 注册，handler 收到 (skill, data)
- 检索 key 为 skill.name
"""

import inspect

import pytest

from neurova.skill_system import SkillEvent, SkillRegistry
from neurova.skills.models import SkillManifest


@pytest.fixture
def registry():
    return SkillRegistry()


@pytest.fixture
def manifest():
    return SkillManifest(id="echo", name="echo", version="1.0.0", description="echo tool")


def test_execute_skill_is_coroutine_function():
    assert inspect.iscoroutinefunction(SkillRegistry.execute_skill)


def test_register_then_get(registry, manifest):
    registry.register_skill(manifest, None)
    assert registry.get_skill("echo") is not None
    assert registry.has_skill("echo") is True


def test_get_skill_names_uses_name(registry, manifest):
    registry.register_skill(manifest, None)
    assert registry.get_skill_names() == ["echo"]


def test_has_skill_missing_returns_false(registry):
    assert registry.has_skill("does-not-exist") is False


def test_clear_removes_all(registry, manifest):
    registry.register_skill(manifest, None)
    registry.clear()
    assert registry.get_skill_names() == []


def test_register_event_callback_fires_with_skill_and_data(registry):
    skill = SkillManifest(id="cb", name="cb", version="1.0.0", description="cb")
    # register_skill 绕过 add_event_handler 限制，成功注册
    registry.register_skill(skill, None)
    received = []

    registry.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: received.append((s, r)))
    registry._emit_event(SkillEvent.POST_EXECUTE, "cb", {"ok": True})

    assert len(received) == 1
    assert received[0][0].name == "cb"
    assert received[0][1] == {"ok": True}


def test_multiple_callbacks_for_same_event_all_fire(registry):
    seen = []
    registry.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: seen.append(1))
    registry.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: seen.append(2))
    registry._emit_event(SkillEvent.POST_EXECUTE, "x", {})
    assert sorted(seen) == [1, 2]
