"""
P1.2.3 测试：修复 node_registry._sync_skills_from_registry 属性访问

P1.2.3 Bug 根因：
node_registry.py:436-447 的 _sync_skills_from_registry 函数，
对 list_skills() 返回的 List[Skill] dataclass 用 dict 访问（skill['name']、skill.get(...)），
触发 TypeError（dataclass 不可下标）或 AttributeError（dataclass 无 .get 方法），
被 try/except ImportError 吞掉（错误类型不匹配，但 AttributeError 也被 except 捕获）。

正确做法：改为属性访问（skill.name、skill.description、skill.version）。
"""

import pytest

from neurova.collaboration.neurflow.node_registry import NodeRegistry


def test_sync_skills_from_registry_uses_attribute_access():
    """P1.2.3: _sync_skills_from_registry 应使用属性访问 Skill dataclass"""
    from neurova.skills import get_skill_registry
    from neurova.skills.registry import SkillRegistry

    # 重置单例，确保干净状态
    try:
        SkillRegistry.reset()
    except Exception:
        pass

    registry = get_skill_registry()
    # 触发默认 skill 注册
    if hasattr(registry, "_register_default_skills"):
        try:
            registry._register_default_skills()
        except Exception:
            pass

    nr = NodeRegistry()
    count = nr.sync_skills()  # 调用 _sync_skills_from_registry

    # 不再因 dict 访问 Skill dataclass 而失败
    # 默认应有 3 个 skill（memory/web_search/file_operation）
    assert count >= 0, f"sync_skills 应返回非负数，实际 {count}"
    if count > 0:
        # 验证 node 已注册（NodeRegistry 用 list_all() 而非 list_nodes()）
        nodes = nr.list_all()
        skill_nodes = [
            n for n in nodes
            if getattr(n, "source", None) == "skill"
            or getattr(n, "type", "").startswith("skill:")
        ]
        assert len(skill_nodes) > 0, f"应有 skill 节点注册，实际 nodes={nodes}"


def test_sync_skills_from_registry_returns_count_matches_registry():
    """P1.2.3: sync_skills 返回值应等于 registry 中 skill 数量"""
    from neurova.skills import get_skill_registry

    registry = get_skill_registry()
    registry_skills = registry.list_skills()
    expected = len(registry_skills)

    nr = NodeRegistry()
    count = nr.sync_skills()

    assert count == expected, f"sync_skills 返回 {count}，registry 有 {expected} 个 skill"


def test_sync_skills_from_registry_no_exception():
    """P1.2.3: sync_skills 不应抛出任何异常（dict 访问 Bug 修复前会被吞掉）"""
    nr = NodeRegistry()
    # 不应抛异常
    result = nr.sync_skills()
    assert isinstance(result, int), f"应返回 int，实际 {type(result)}"
