"""
s1 TDD: 验证 GET /agent/{agent_id}/skills 端点连接真实 SkillService

Bug 根因 (bug-hunt Phase 3):
  skill_pool_api.py:176-179 的 get_agent_skills 直接 `return []`,
  从未调用 SkillService.list_skills(), 导致前端 AgentSkillPage 永远显示空列表,
  无论 agent 实际有多少技能。

修复契约 (s1):
  1. 静态: get_agent_skills 源码包含 SkillService 与 list_skills (而非 bare `return []`)
  2. 静态: get_agent_skills 使用 path 参数 agent_id 构造 SkillService
  3. 行为: mock SkillService, 验证 list_skills() 被调用
  4. 行为: list_skills 返回非空时, 端点返回该非空列表 (而非 [])
  5. 行为: agent_id 从路径参数透传到 SkillService 构造函数
  6. 行为: SkillService 抛异常时, 端点记录日志并返回 [] (优雅降级, 不静默吞)
"""

import inspect
from unittest.mock import patch, MagicMock

import pytest


def test_get_agent_skills_source_uses_skill_service():
    """s1.1 静态契约: get_agent_skills 源码必须引用 SkillService 与 list_skills"""
    from neurova.api.endpoints import skill_pool_api as mod
    src = inspect.getsource(mod.get_agent_skills)
    assert "SkillService" in src, "get_agent_skills 应引用 SkillService"
    assert "list_skills" in src, "get_agent_skills 应调用 list_skills()"


def test_get_agent_skills_source_not_hardcoded_empty():
    """s1.2 静态契约: get_agent_skills 不能是 bare `return []`"""
    from neurova.api.endpoints import skill_pool_api as mod
    src = inspect.getsource(mod.get_agent_skills)
    # 允许在异常分支返回 [], 但主路径必须调用 SkillService
    # 简化检查: 源码行数应大于 3 (bare return [] 只有 2 行)
    line_count = len([ln for ln in src.splitlines() if ln.strip()])
    assert line_count > 3, (
        f"get_agent_skills 过于简短 ({line_count} 行), 疑似 bare `return []`. 源码:\n{src}"
    )


def test_get_agent_skills_calls_list_skills_behavior():
    """s1.3 行为契约: get_agent_skills 应调用 SkillService.list_skills()"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service) as mock_cls:
        result = asyncio.run(mod.get_agent_skills(agent_id="test_agent"))
        assert mock_cls.called, "应实例化 SkillService"
        assert mock_service.list_skills.called, "应调用 list_skills()"
        assert result == [], "空 list_skills 返回时应返回 []"


def test_get_agent_skills_returns_nonempty_when_service_has_skills():
    """s1.4 行为契约: SkillService 返回非空时, 端点应返回该非空列表"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    fake_skill = {
        "id": "skill_001",
        "name": "weather",
        "version": "1.0.0",
        "description": "weather skill",
        "enabled": True,
        "installed_at": "2026-07-15T10:00:00",
    }
    mock_service = MagicMock()
    mock_service.list_skills.return_value = [fake_skill]

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
        result = asyncio.run(mod.get_agent_skills(agent_id="agent_with_skills"))
        assert len(result) == 1, f"应返回 1 个技能, 实际 {len(result)}"
        assert result[0].name == "weather", f"技能名应为 weather, 实际 {result[0].name}"


def test_get_agent_skills_passes_agent_id_to_skill_service():
    """s1.5 行为契约: 路径参数 agent_id 透传给 SkillService 构造函数"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service) as mock_cls:
        asyncio.run(mod.get_agent_skills(agent_id="my-special-agent"))
        # 验证 SkillService 被以 agent_id="my-special-agent" 构造
        call_args, call_kwargs = mock_cls.call_args
        # agent_id 可能是位置参数或关键字参数
        if call_args:
            assert "my-special-agent" in call_args, f"agent_id 应透传, call_args={call_args}"
        else:
            assert call_kwargs.get("agent_id") == "my-special-agent", (
                f"agent_id 应透传, call_kwargs={call_kwargs}"
            )


def test_get_agent_skills_degrades_gracefully_on_exception():
    """s1.6 行为契约: SkillService 抛异常时, 端点应记录日志并返回 [] (非静默)"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.side_effect = RuntimeError("DB locked")

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
        with patch.object(mod.logger, "exception") as mock_log_exc:
            result = asyncio.run(mod.get_agent_skills(agent_id="broken_agent"))
            assert result == [], "异常时应优雅降级返回 []"
            assert mock_log_exc.called, "异常时必须调用 logger.exception (不能静默吞)"
