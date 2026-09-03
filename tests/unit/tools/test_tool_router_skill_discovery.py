"""
P1.1.1 测试：修复 tool_router._discover_skill_tools 类型混淆

P1.1 Bug 根因：
1. line 190 `skills = getattr(self._skill_manager, "skills", None)` 访问 `.skills` 属性，
   返回 `Dict[str, Tuple[Skill, Path]]`（元组）
2. line 201 `for skill_name, skill in skills.items():` 把 `skill` 解包成 `(Skill, Path)` 元组
3. line 203 `getattr(skill, "description", "")` 对元组返回空字符串（静默失败）
4. 若回退到 `list_skills()` 返回 `List[Skill]`（list 不是 dict），`isinstance(skills, dict)` 为 False，
   整个 for 循环被跳过 — 同步结果被静默丢弃

正确做法：使用 `list_skills()` 正典方法（返回 `List[Skill]`），迭代 List 而非 dict。
"""

import pytest
from unittest.mock import MagicMock

from neurova.tool_layers.tool_router import ToolRouter, _SkillToolProxy


def test_discover_skill_tools_returns_skills_from_registry():
    """P1.1.1: _discover_skill_tools 应从 SkillRegistry 发现 skill 工具，不再静默失败"""
    from neurova.skills import get_skill_registry
    from neurova.skills.registry import SkillRegistry

    # 重置单例，确保干净状态
    try:
        SkillRegistry.reset()
    except Exception:
        pass

    registry = get_skill_registry()
    # 触发默认 skill 注册（如果有）
    if hasattr(registry, "_register_default_skills"):
        try:
            registry._register_default_skills()
        except Exception:
            pass

    router = ToolRouter()
    router._skill_manager = registry

    tools = router._discover_skill_tools()

    # 不再静默失败：应返回 dict（可能为空，但如果 registry 有 skill 应非空）
    assert isinstance(tools, dict), f"应返回 dict，实际返回 {type(tools)}"

    # 如果 registry 有 skill，验证每个 _SkillToolProxy 的 description 非空
    if len(tools) > 0:
        for tool_name, proxy in tools.items():
            assert isinstance(proxy, _SkillToolProxy), f"{tool_name} 应是 _SkillToolProxy"
            # 关键断言：description 不应为空（修复前对元组 getattr 返回空字符串）
            assert proxy.description, f"Skill {tool_name} 描述不应为空（P1.1 Bug 修复前静默失败）"


def test_discover_skill_tools_uses_list_skills_not_skills_attribute():
    """P1.1.1: 应优先使用 list_skills() 正典方法，而非 .skills 属性（返回 Tuple 元组）"""
    from neurova.skills.models import Skill, SkillSource

    # 创建 mock skill_manager，模拟 list_skills() 返回 List[Skill]
    mock_manager = MagicMock()
    test_skill = Skill(
        id="test_skill_1",
        name="TestSkill",
        description="测试技能描述",
        version="1.0.0",
        source=SkillSource.BUILTIN,
        enabled=True,
    )
    mock_manager.list_skills.return_value = [test_skill]
    # .skills 属性返回 Dict[str, Tuple[Skill, Path]]（错误路径）
    mock_manager.skills = {"TestSkill": (test_skill, "/fake/path")}

    router = ToolRouter()
    router._skill_manager = mock_manager

    tools = router._discover_skill_tools()

    # 应发现 TestSkill
    assert "TestSkill" in tools, f"应发现 TestSkill，实际 keys={list(tools.keys())}"
    proxy = tools["TestSkill"]
    assert isinstance(proxy, _SkillToolProxy)
    # 关键：description 应来自 Skill dataclass，非空
    assert proxy.description == "测试技能描述", f"description 应为 '测试技能描述'，实际 '{proxy.description}'"


def test_discover_skill_tools_empty_when_no_skills():
    """P1.1.1: 无 skill 时应返回空 dict，不抛异常"""
    mock_manager = MagicMock()
    mock_manager.list_skills.return_value = []
    mock_manager.skills = {}

    router = ToolRouter()
    router._skill_manager = mock_manager

    tools = router._discover_skill_tools()

    assert tools == {}
