"""
A12.1-A12.2 测试：验证 adapters.skill_to_node 接收 Skill dataclass + sync_skills 返回非 0

A7 副作用：list_skills() 返回类型从 List[Dict] 改为 List[Skill]（dataclass），
但 adapters.py 的 skill_to_node 仍用 dict 访问，导致运行时 AttributeError。
被 try/except 降级为返回 0，掩盖了根本问题。
"""

import pytest

from neurova.skills.models import Skill, SkillSource


def test_skill_to_node_accepts_skill_dataclass():
    """A12.1: skill_to_node 应接收 Skill dataclass 并返回正确节点定义"""
    from neurova.collaboration.neurflow.adapters import skill_to_node

    skill = Skill(
        id="s1",
        name="TestSkill",
        description="desc",
        version="1.0.0",
        source=SkillSource.BUILTIN,
    )
    # 不应抛 AttributeError
    node = skill_to_node(skill)
    assert node.type == "skill:TestSkill"
    assert node.label == "TestSkill"
    assert node.description == "desc"
    assert node.version == "1.0.0"
    assert node.source == "skill"
    assert node.source_id == "TestSkill"


def test_skill_to_node_with_minimal_skill():
    """A12.1 补充：Skill 仅必填字段时也应正常工作"""
    from neurova.collaboration.neurflow.adapters import skill_to_node

    skill = Skill(id="minimal", name="Min", source=SkillSource.BUILTIN)
    node = skill_to_node(skill)
    assert node.type == "skill:Min"
    assert node.label == "Min"


def test_sync_skills_returns_nonzero_when_registry_has_skills():
    """A12.2: sync_skills 应返回 registry 中 skill 的数量（非 0）。

    数量不硬编码——skill 池随内置技能演进（原 3 个默认 → 现更多）。
    """
    from neurova.collaboration.neurflow.adapters import sync_skills
    from neurova.collaboration.neurflow.node_registry import NodeRegistry
    from neurova.skills import get_skill_registry

    registry = get_skill_registry()
    expected = len(registry.list_skills())
    assert expected > 0, "skill registry should have builtin skills"
    nr = NodeRegistry()
    count = sync_skills(nr)
    assert count == expected, f"Expected {expected} skills synced, got {count}"
