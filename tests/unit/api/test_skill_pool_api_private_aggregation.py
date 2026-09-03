"""
s2 TDD: 验证 GET /private 聚合多数据源

Bug 根因 (bug-hunt Phase 3):
  skill_pool_api.py:105-109 的 list_private_skills 仅读 _private_skills (API 内存状态),
  导致通过 POST /install-from-url 或 POST /install-from-zip 安装的技能
  (存在于 SkillService 的磁盘 manifest) 在前端 SkillPoolPage 不可见 — split-brain.

修复契约 (s2 P0 #1):
  list_private_skills 应聚合:
    源1: _private_skills (POST /private 创建的, 按 owner_id 过滤)
    源2: SkillService(agent_id=user_id).list_skills() (安装的, 磁盘持久化)
  SkillRegistry 不纳入 /private (它是 global, 应走 /public).
  AutoSkillBuilder → SkillService 的桥接由 s3 单独修复.

测试:
  1. 静态: list_private_skills 源码引用 SkillService 与 list_skills
  2. 行为: mock SkillService, 验证 list_skills() 被调用
  3. 行为: _private_skills 有1条 + SkillService 返回1条 → 结果2条 (聚合)
  4. 行为: SkillService 抛异常时, 仍返回 _private_skills 的内容 (优雅降级 + 日志)
  5. 行为: user_id 透传给 SkillService 构造函数
"""

import inspect
from unittest.mock import patch, MagicMock


def test_list_private_skills_source_uses_skill_service():
    """s2.1 静态契约: list_private_skills 源码引用 SkillService 与 list_skills"""
    from neurova.api.endpoints import skill_pool_api as mod
    src = inspect.getsource(mod.list_private_skills)
    assert "SkillService" in src, "list_private_skills 应引用 SkillService"
    assert "list_skills" in src, "list_private_skills 应调用 list_skills()"


def test_list_private_skills_calls_skill_service_behavior():
    """s2.2 行为契约: list_private_skills 应调用 SkillService.list_skills()"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service) as mock_cls:
        asyncio.run(mod.list_private_skills(agent_id="test_user"))
        assert mock_cls.called, "应实例化 SkillService"
        assert mock_service.list_skills.called, "应调用 list_skills()"


def test_list_private_skills_aggregates_two_sources():
    """s2.3 行为契约: 聚合 _private_skills (1条) + SkillService (1条) → 2条"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    # 源1: _private_skills 中预置一条
    mod._private_skills.clear()
    mod._private_skills["priv-1"] = {
        "skill_id": "priv-1",
        "name": "api_created_skill",
        "description": "via POST /private",
        "category": "general",
        "version": "1.0.0",
        "scope": "private",
        "owner_id": "test_user",
        "enabled": True,
        "created_at": 1000.0,
        "updated_at": 1000.0,
    }
    # 源2: SkillService 返回一条
    mock_service = MagicMock()
    mock_service.list_skills.return_value = [
        {
            "id": "installed-1",
            "name": "installed_skill",
            "version": "0.2.0",
            "description": "via install_from_url",
            "enabled": True,
            "installed_at": "2026-07-15",
        }
    ]

    try:
        with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
            result = asyncio.run(mod.list_private_skills(agent_id="test_user"))
            assert len(result) == 2, f"应聚合 2 条, 实际 {len(result)}"
            names = {r.name for r in result}
            assert names == {"api_created_skill", "installed_skill"}, (
                f"应包含两个源的技能, 实际 {names}"
            )
    finally:
        mod._private_skills.clear()


def test_list_private_skills_degrades_when_skill_service_raises():
    """s2.4 行为契约: SkillService 抛异常时, 仍返回 _private_skills 的内容 + 记录日志"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mod._private_skills.clear()
    mod._private_skills["priv-1"] = {
        "skill_id": "priv-1",
        "name": "survivor",
        "description": "should survive SkillService failure",
        "category": "general",
        "version": "1.0.0",
        "scope": "private",
        "owner_id": "test_user",
        "enabled": True,
        "created_at": 1000.0,
        "updated_at": 1000.0,
    }

    mock_service = MagicMock()
    mock_service.list_skills.side_effect = RuntimeError("disk error")

    try:
        with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
            with patch.object(mod.logger, "exception") as mock_log_exc:
                result = asyncio.run(mod.list_private_skills(agent_id="test_user"))
                # 优雅降级: 仍返回 _private_skills 的内容
                assert len(result) == 1, f"应降级返回 1 条, 实际 {len(result)}"
                assert result[0].name == "survivor"
                # 必须记录日志 (不静默吞)
                assert mock_log_exc.called, "SkillService 异常时必须 logger.exception"
    finally:
        mod._private_skills.clear()


def test_list_private_skills_passes_user_id_to_skill_service():
    """s2.5 行为契约: user_id 透传给 SkillService 构造函数 (作为 agent_id)"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service) as mock_cls:
        asyncio.run(mod.list_private_skills(agent_id="alice"))
        call_args, call_kwargs = mock_cls.call_args
        if call_args:
            assert "alice" in call_args, f"user_id 应透传, call_args={call_args}"
        else:
            assert call_kwargs.get("agent_id") == "alice", (
                f"user_id 应作为 agent_id 透传, call_kwargs={call_kwargs}"
            )


def test_list_private_skills_filters_by_owner_id():
    """s2.6 行为契约: _private_skills 仍按 owner_id == user_id 过滤 (保留原语义)"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mod._private_skills.clear()
    # alice 的私有技能
    mod._private_skills["alice-skill"] = {
        "skill_id": "alice-skill",
        "name": "alice_skill",
        "owner_id": "alice",
        "scope": "private",
        "category": "general",
        "version": "1.0.0",
        "enabled": True,
        "created_at": 0,
        "updated_at": 0,
    }
    # bob 的私有技能 (不应出现在 alice 的列表中)
    mod._private_skills["bob-skill"] = {
        "skill_id": "bob-skill",
        "name": "bob_skill",
        "owner_id": "bob",
        "scope": "private",
        "category": "general",
        "version": "1.0.0",
        "enabled": True,
        "created_at": 0,
        "updated_at": 0,
    }

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    try:
        with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
            result = asyncio.run(mod.list_private_skills(agent_id="alice"))
            names = {r.name for r in result}
            assert "alice_skill" in names
            assert "bob_skill" not in names, "不应返回其他用户的私有技能"
    finally:
        mod._private_skills.clear()
