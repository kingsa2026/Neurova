"""
s4 TDD: GET /private 后端参数 user_id → agent_id 对齐前端

Bug 根因 (bug-hunt Phase 3):
  前端 skill-pool.ts:53-55 的 getPrivateSkills(agentId) 发送 ?agent_id=xxx,
  但后端 skill_pool_api.py:106 的 list_private_skills(user_id=...) 期望 ?user_id=xxx.
  参数名不匹配 → 后端用默认值 "default" → 前端永远看到 "default" 用户的技能, 而非指定 agent 的.

修复契约 (s4 P1 #6):
  1. list_private_skills 的 query 参数从 user_id 改为 agent_id
  2. 内部逻辑使用 agent_id (替代 user_id) 作为 owner_id 过滤 + SkillService 构造
  3. 调用方传 agent_id= 不抛 TypeError
"""

import inspect
from unittest.mock import patch, MagicMock


def test_list_private_skills_param_is_agent_id():
    """s4.1 静态契约: list_private_skills 参数应为 agent_id (而非 user_id)"""
    from neurova.api.endpoints import skill_pool_api as mod
    sig = inspect.signature(mod.list_private_skills)
    assert "agent_id" in sig.parameters, (
        f"list_private_skills 应有 agent_id 参数, 实际参数: {list(sig.parameters)}"
    )


def test_list_private_skills_accepts_agent_id_kwarg():
    """s4.2 行为契约: 调用方传 agent_id= 不抛 TypeError"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
        # 不应抛 TypeError: unexpected keyword argument 'agent_id'
        result = asyncio.run(mod.list_private_skills(agent_id="my_agent"))
        assert result == [], "应正常返回空列表"


def test_list_private_skills_uses_agent_id_for_skill_service():
    """s4.3 行为契约: agent_id 透传给 SkillService (而非 user_id)"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mock_service = MagicMock()
    mock_service.list_skills.return_value = []

    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service) as mock_cls:
        asyncio.run(mod.list_private_skills(agent_id="agent-xyz"))
        call_args, call_kwargs = mock_cls.call_args
        if call_args:
            assert "agent-xyz" in call_args, f"agent_id 应透传, call_args={call_args}"
        else:
            assert call_kwargs.get("agent_id") == "agent-xyz", (
                f"agent_id 应透传, call_kwargs={call_kwargs}"
            )


def test_list_private_skills_uses_agent_id_for_owner_filter():
    """s4.4 行为契约: _private_skills 按 owner_id == agent_id 过滤"""
    import asyncio
    from neurova.api.endpoints import skill_pool_api as mod

    mod._private_skills.clear()
    mod._private_skills["a-1"] = {
        "skill_id": "a-1",
        "name": "agent_a_skill",
        "owner_id": "agentA",
        "scope": "private",
        "category": "general",
        "version": "1.0.0",
        "enabled": True,
        "created_at": 0,
        "updated_at": 0,
    }
    mod._private_skills["b-1"] = {
        "skill_id": "b-1",
        "name": "agent_b_skill",
        "owner_id": "agentB",
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
            result = asyncio.run(mod.list_private_skills(agent_id="agentA"))
            names = {r.name for r in result}
            assert "agent_a_skill" in names
            assert "agent_b_skill" not in names, "应按 agent_id 过滤 owner_id"
    finally:
        mod._private_skills.clear()
