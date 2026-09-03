"""SkillRegistry 注册/查询/列出/注销测试（对齐 ADR 0011 class A 实现）。

原测试面向已废弃的 class B SkillRegistry（tuple 返回、get_all_skills、
unregister_skill、__len__/__contains__）。ADR 0011 已统一到
neurova.skill_system 的 class A，此处重写为 class A 真实 API：
- register_skill(manifest, path) -> bool
- get_skill(name) -> Optional[Skill]（key 为 skill.name）
- has_skill(name) -> bool
- list_skills() -> List[SkillInfo]
- get_skill_names() -> List[str]
- unregister(name)
"""

import pytest

from neurova.skill_system import SkillRegistry
from neurova.skills.models import SkillManifest


@pytest.fixture
def registry():
    return SkillRegistry()


@pytest.fixture
def manifest():
    return SkillManifest(
        id="test-skill",
        name="Test Skill",
        version="1.0.0",
        description="a test skill",
        author="tester",
    )


def test_register_skill_returns_true(registry, manifest):
    assert registry.register_skill(manifest, None) is True


def test_get_skill_returns_skill_object_by_name(registry, manifest):
    registry.register_skill(manifest, None)
    skill = registry.get_skill("Test Skill")
    assert skill is not None
    assert skill.name == "Test Skill"


def test_get_skill_uses_name_not_id(registry, manifest):
    registry.register_skill(manifest, None)
    assert registry.get_skill("test-skill") is None


def test_has_skill_by_name(registry, manifest):
    registry.register_skill(manifest, None)
    assert registry.has_skill("Test Skill") is True
    assert registry.has_skill("test-skill") is False


def test_get_skill_names_returns_names(registry, manifest):
    registry.register_skill(manifest, None)
    assert registry.get_skill_names() == ["Test Skill"]


def test_list_skills_returns_skill_info_list(registry, manifest):
    registry.register_skill(manifest, None)
    infos = registry.list_skills()
    assert len(infos) == 1
    info = infos[0]
    assert info.name == "Test Skill"


def test_unregister_removes_skill(registry, manifest):
    registry.register_skill(manifest, None)
    registry.unregister("Test Skill")
    assert registry.has_skill("Test Skill") is False
    assert registry.get_skill_names() == []


def test_duplicate_register_does_not_raise(registry, manifest):
    assert registry.register_skill(manifest, None) is True
    assert registry.register_skill(manifest, None) is True


def test_query_missing_skill_returns_none_false(registry):
    assert registry.get_skill("nope") is None
    assert registry.has_skill("nope") is False
