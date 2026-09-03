"""
C1 测试：验证 skill.py 端点连接真实 SkillRegistry

验证：
1. skill.py 模块导入 get_skill_registry（通过 _get_skills_from_registry 间接导入）
2. get_skills 端点调用 _get_skills_from_registry()（内部调用 get_skill_registry）
3. get_skill_stats 端点调用 _get_skills_from_registry()
4. get_skill 端点调用 _get_skills_from_registry()
5. enable/disable 端点调用 _get_skills_from_registry()
6. execute_skill 端点调用 _get_skills_from_registry()
7. _get_builtin_skills 不再被端点直接调用
8. 行为验证：mock get_skill_registry，验证 registry.list_skills() 被调用
"""

import inspect
from unittest.mock import patch, MagicMock


def test_skill_endpoint_imports_skill_registry():
    """C1.1: skill.py 模块应通过 _get_skills_from_registry 间接导入 get_skill_registry"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module)
    assert "get_skill_registry" in source, "skill.py 应导入 get_skill_registry"


def test_get_skills_uses_registry_via_helper():
    """C1.2: get_skills 应调用 _get_skills_from_registry()（而非 _get_builtin_skills）"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.get_skills)
    assert "_get_skills_from_registry()" in source, "get_skills 应调用 _get_skills_from_registry()"
    assert "_get_builtin_skills()" not in source, "get_skills 不应直接调用 _get_builtin_skills()"


def test_get_skill_stats_uses_registry_via_helper():
    """C1.3: get_skill_stats 应调用 _get_skills_from_registry()"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.get_skill_stats)
    assert "_get_skills_from_registry()" in source, "get_skill_stats 应调用 _get_skills_from_registry()"


def test_get_skill_uses_registry_via_helper():
    """C1.4: get_skill 应调用 _get_skills_from_registry()"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.get_skill)
    assert "_get_skills_from_registry()" in source, "get_skill 应调用 _get_skills_from_registry()"


def test_enable_skill_uses_registry_via_helper():
    """C1.5: enable_skill 应调用 _get_skills_from_registry()"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.enable_skill)
    assert "_get_skills_from_registry()" in source, "enable_skill 应调用 _get_skills_from_registry()"


def test_disable_skill_uses_registry_via_helper():
    """C1.6: disable_skill 应调用 _get_skills_from_registry()"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.disable_skill)
    assert "_get_skills_from_registry()" in source, "disable_skill 应调用 _get_skills_from_registry()"


def test_execute_skill_uses_registry_via_helper():
    """C1.7: execute_skill 应调用 _get_skills_from_registry()"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.execute_skill)
    assert "_get_skills_from_registry()" in source, "execute_skill 应调用 _get_skills_from_registry()"


def test_get_builtin_skills_not_called_by_endpoints():
    """C1.8: _get_builtin_skills 不应被任何端点直接调用（仅作为 fallback）"""
    from neurova.api.endpoints import skill as skill_module
    endpoint_names = ["get_skills", "get_skill_stats", "get_skill", "enable_skill", "disable_skill", "execute_skill"]
    for name in endpoint_names:
        func = getattr(skill_module, name)
        source = inspect.getsource(func)
        assert "_get_builtin_skills()" not in source, f"{name} 不应直接调用 _get_builtin_skills()"


def test_get_skills_behavior_calls_registry():
    """C1.9: 行为验证 — get_skills 应通过 _get_skills_from_registry 调用 get_skill_registry"""
    import asyncio
    from neurova.api.endpoints import skill as skill_module

    # 构造 mock registry，返回空 list_skills
    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = []

    with patch("neurova.skills.get_skill_registry", return_value=mock_registry):
        # 调用 _get_skills_from_registry 验证它确实调用了 get_skill_registry
        result = skill_module._get_skills_from_registry()
        assert mock_registry.list_skills.called, "_get_skills_from_registry 应调用 registry.list_skills()"
        assert result == [], "空 registry 应返回空列表"
