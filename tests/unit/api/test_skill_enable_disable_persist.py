"""
C2 测试：验证 enable/disable 端点真正持久化 enabled 状态

验证：
1. SkillRegistry 提供 set_skill_enabled 方法
2. enable_skill 端点调用 registry.set_skill_enabled(skill_id, True)
3. disable_skill 端点调用 registry.set_skill_enabled(skill_id, False)
4. 行为验证：mock registry，验证 set_skill_enabled 被调用
"""

import inspect
from unittest.mock import patch, MagicMock


def test_skill_registry_has_set_enabled_method():
    """C2.1: SkillRegistry 应提供 set_skill_enabled 方法"""
    from neurova.skills.registry import SkillRegistry
    assert hasattr(SkillRegistry, "set_skill_enabled"), "SkillRegistry 应提供 set_skill_enabled 方法"


def test_enable_skill_calls_set_enabled():
    """C2.2: enable_skill 应调用 registry.set_skill_enabled(skill_id, True)"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.enable_skill)
    assert "set_skill_enabled" in source, "enable_skill 应调用 set_skill_enabled"
    assert "True" in source, "enable_skill 应传递 enabled=True"


def test_disable_skill_calls_set_enabled():
    """C2.3: disable_skill 应调用 registry.set_skill_enabled(skill_id, False)"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.disable_skill)
    assert "set_skill_enabled" in source, "disable_skill 应调用 set_skill_enabled"
    assert "False" in source, "disable_skill 应传递 enabled=False"


def test_enable_skill_behavior_calls_registry():
    """C2.4: 行为验证 — enable_skill 应通过 registry 持久化 enabled=True"""
    import asyncio
    from fastapi import Request
    from neurova.api.endpoints import skill as skill_module

    # 构造 mock registry，包含一个 skill
    mock_manifest = MagicMock()
    mock_manifest.id = "test_skill"
    mock_manifest.name = "Test"
    mock_manifest.description = ""
    mock_manifest.version = "1.0.0"
    mock_manifest.keywords = []
    mock_manifest.enabled = False
    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [mock_manifest]
    mock_registry.set_skill_enabled = MagicMock()

    with patch("neurova.skills.get_skill_registry", return_value=mock_registry):
        request = MagicMock(spec=Request)
        result = asyncio.run(skill_module.enable_skill(request, "test_skill"))
        assert mock_registry.set_skill_enabled.called, "enable_skill 应调用 registry.set_skill_enabled"
        call_args = mock_registry.set_skill_enabled.call_args
        assert call_args[0][0] == "test_skill" or call_args[1].get("skill_id") == "test_skill", \
            "set_skill_enabled 第一个参数应为 skill_id"
        assert call_args[0][1] is True or call_args[1].get("enabled") is True, \
            "set_skill_enabled 第二个参数应为 True"


def test_disable_skill_behavior_calls_registry():
    """C2.5: 行为验证 — disable_skill 应通过 registry 持久化 enabled=False"""
    import asyncio
    from fastapi import Request
    from neurova.api.endpoints import skill as skill_module

    mock_manifest = MagicMock()
    mock_manifest.id = "test_skill"
    mock_manifest.name = "Test"
    mock_manifest.description = ""
    mock_manifest.version = "1.0.0"
    mock_manifest.keywords = []
    mock_manifest.enabled = True
    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [mock_manifest]
    mock_registry.set_skill_enabled = MagicMock()

    with patch("neurova.skills.get_skill_registry", return_value=mock_registry):
        request = MagicMock(spec=Request)
        result = asyncio.run(skill_module.disable_skill(request, "test_skill"))
        assert mock_registry.set_skill_enabled.called, "disable_skill 应调用 registry.set_skill_enabled"
        call_args = mock_registry.set_skill_enabled.call_args
        assert call_args[0][1] is False or call_args[1].get("enabled") is False, \
            "set_skill_enabled 第二个参数应为 False"
