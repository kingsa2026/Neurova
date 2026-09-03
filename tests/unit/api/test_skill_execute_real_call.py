"""
C3 测试：验证 execute_skill 端点真实调用 SkillRegistry（而非返回 stub）

验证：
1. execute_skill 端点应通过 registry.execute_skill() 真实执行
2. 当 agent 不可用时，应降级到 registry.execute_skill()
3. 行为验证：mock registry，验证 execute_skill 被调用
"""

import inspect
from unittest.mock import patch, MagicMock, AsyncMock


def test_execute_skill_calls_registry_when_agent_unavailable():
    """C3.1: execute_skill 在 agent 不可用时应调用 registry.execute_skill()"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.execute_skill)
    assert "registry.execute_skill" in source or "execute_skill(" in source, \
        "execute_skill 应调用 registry.execute_skill()"


def test_execute_skill_no_longer_returns_simulated_stub():
    """C3.2: execute_skill 不应再返回 'execution simulated' stub"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.execute_skill)
    # 不应再包含模拟执行的降级路径
    assert "execution simulated" not in source, \
        "execute_skill 不应再返回 'execution simulated' stub"


def test_execute_skill_behavior_calls_registry():
    """C3.3: 行为验证 — agent 不可用时，execute_skill 应调用 registry.execute_skill()"""
    import asyncio
    from fastapi import Request
    from neurova.api.endpoints import skill as skill_module
    from neurova.skills.executor import SkillResult

    # 构造 mock manifest
    mock_manifest = MagicMock()
    mock_manifest.id = "test_skill"
    mock_manifest.name = "Test"
    mock_manifest.description = ""
    mock_manifest.version = "1.0.0"
    mock_manifest.keywords = []
    mock_manifest.enabled = True

    # 构造 mock registry
    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [mock_manifest]
    mock_registry.execute_skill = AsyncMock(return_value=SkillResult(success=True, output={"result": "ok"}))

    with patch("neurova.skills.get_skill_registry", return_value=mock_registry):
        # mock _get_agent 返回 None（agent 不可用）
        with patch.object(skill_module, "_get_agent", return_value=None):
            request = MagicMock(spec=Request)
            request.state.request_id = "test"
            result = asyncio.run(skill_module.execute_skill(request, "test_skill"))
            # 验证 registry.execute_skill 被调用
            assert mock_registry.execute_skill.called, \
                "agent 不可用时，execute_skill 应调用 registry.execute_skill()"
            # 验证返回结果
            assert result.success is True, "应返回 success=True"


def test_execute_skill_behavior_returns_real_result():
    """C3.4: 行为验证 — execute_skill 应返回真实 SkillResult 的 output"""
    import asyncio
    from fastapi import Request
    from neurova.api.endpoints import skill as skill_module
    from neurova.skills.executor import SkillResult

    mock_manifest = MagicMock()
    mock_manifest.id = "test_skill"
    mock_manifest.name = "Test"
    mock_manifest.description = ""
    mock_manifest.version = "1.0.0"
    mock_manifest.keywords = []
    mock_manifest.enabled = True

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [mock_manifest]
    expected_output = {"computed": 42}
    mock_registry.execute_skill = AsyncMock(
        return_value=SkillResult(success=True, output=expected_output)
    )

    with patch("neurova.skills.get_skill_registry", return_value=mock_registry):
        with patch.object(skill_module, "_get_agent", return_value=None):
            request = MagicMock(spec=Request)
            request.state.request_id = "test"
            result = asyncio.run(skill_module.execute_skill(request, "test_skill"))
            assert result.result == expected_output, \
                f"应返回真实 SkillResult.output，期望 {expected_output}，实际 {result.result}"


def test_execute_skill_behavior_handles_failure():
    """C3.5: 行为验证 — registry.execute_skill 失败时应返回 success=False"""
    import asyncio
    from fastapi import Request
    from neurova.api.endpoints import skill as skill_module
    from neurova.skills.executor import SkillResult

    mock_manifest = MagicMock()
    mock_manifest.id = "test_skill"
    mock_manifest.name = "Test"
    mock_manifest.description = ""
    mock_manifest.version = "1.0.0"
    mock_manifest.keywords = []
    mock_manifest.enabled = True

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [mock_manifest]
    mock_registry.execute_skill = AsyncMock(
        return_value=SkillResult(success=False, error="execution failed")
    )

    with patch("neurova.skills.get_skill_registry", return_value=mock_registry):
        with patch.object(skill_module, "_get_agent", return_value=None):
            request = MagicMock(spec=Request)
            request.state.request_id = "test"
            result = asyncio.run(skill_module.execute_skill(request, "test_skill"))
            assert result.success is False, "失败时应返回 success=False"
            assert result.error == "execution failed", "应传递错误信息"
