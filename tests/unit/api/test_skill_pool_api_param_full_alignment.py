"""s6 TDD: 对齐 create/update/delete_private_skill 参数名 (WARTN 2)

背景:
- s4 已将 list_private_skills 参数从 user_id 改为 agent_id, 与前端对齐.
- 但同模块 create_private_skill / update_private_skill / delete_private_skill
  仍用 user_id (skill_pool_api.py:151/171/185).
- 前端 skill-pool.ts 的 createSkill/updateSkill/deleteSkill 不主动传该参数
  (走服务端默认 "default"), 所以改名不破坏前端契约.
- 但同模块内参数名不一致是潜在陷阱: 未来调用方传 ?agent_id=xxx 创建技能
  会查不到 (因 create 读 user_id 默认 default, list 按 agent_id 过滤).

契约: 三个端点都使用 agent_id 参数名 (与 list_private_skills 一致).
"""

import asyncio
import inspect
import importlib
from unittest.mock import MagicMock, patch

import pytest


def _get_func(mod, name):
    """从模块获取顶层 async 函数"""
    return getattr(mod, name)


# ─── 静态契约: 参数名 ───


def test_create_private_skill_param_is_agent_id():
    """s6.1 静态契约: create_private_skill 参数名为 agent_id"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.create_private_skill)
    # 函数签名行
    sig_line = src.split(":\n", 1)[0]
    assert "agent_id" in sig_line, (
        f"create_private_skill 签名应含 agent_id, 实际: {sig_line}"
    )
    assert "user_id" not in sig_line, (
        f"create_private_skill 签名不应再含 user_id, 实际: {sig_line}"
    )


def test_update_private_skill_param_is_agent_id():
    """s6.2 静态契约: update_private_skill 参数名为 agent_id"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.update_private_skill)
    sig_line = src.split(":\n", 1)[0]
    assert "agent_id" in sig_line, (
        f"update_private_skill 签名应含 agent_id, 实际: {sig_line}"
    )
    assert "user_id" not in sig_line, (
        f"update_private_skill 签名不应再含 user_id, 实际: {sig_line}"
    )


def test_delete_private_skill_param_is_agent_id():
    """s6.3 静态契约: delete_private_skill 参数名为 agent_id"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.delete_private_skill)
    sig_line = src.split(":\n", 1)[0]
    assert "agent_id" in sig_line, (
        f"delete_private_skill 签名应含 agent_id, 实际: {sig_line}"
    )
    assert "user_id" not in sig_line, (
        f"delete_private_skill 签名不应再含 user_id, 实际: {sig_line}"
    )


# ─── 行为契约: 接受 agent_id kwarg ───


def test_create_private_skill_accepts_agent_id_kwarg():
    """s6.4 行为契约: create_private_skill 接受 agent_id 关键字参数"""
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillCreate

    mod._private_skills.clear()
    body = SkillCreate(name="test_skill", description="测试", category="general")
    try:
        result = asyncio.run(mod.create_private_skill(body, agent_id="alice"))
        assert result.owner_id == "alice", (
            f"create_private_skill(agent_id='alice') 应设置 owner_id='alice', "
            f"实际: {result.owner_id}"
        )
    except TypeError as e:
        pytest.fail(f"create_private_skill 不接受 agent_id kwarg: {e}")
    finally:
        mod._private_skills.clear()


def test_update_private_skill_accepts_agent_id_kwarg():
    """s6.5 行为契约: update_private_skill 接受 agent_id 关键字参数"""
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillCreate, SkillUpdate

    mod._private_skills.clear()
    # 先用 agent_id 创建 (s6.4 通过后才能这样创建)
    body_create = SkillCreate(name="old_name", description="旧", category="general")
    created = asyncio.run(mod.create_private_skill(body_create, agent_id="alice"))
    sid = created.skill_id

    try:
        body_update = SkillUpdate(name="new_name")
        result = asyncio.run(mod.update_private_skill(sid, body_update, agent_id="alice"))
        assert result.name == "new_name", f"更新后 name 应为 new_name, 实际: {result.name}"
    except TypeError as e:
        pytest.fail(f"update_private_skill 不接受 agent_id kwarg: {e}")
    finally:
        mod._private_skills.clear()


def test_delete_private_skill_accepts_agent_id_kwarg():
    """s6.6 行为契约: delete_private_skill 接受 agent_id 关键字参数"""
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillCreate

    mod._private_skills.clear()
    body = SkillCreate(name="to_delete", description="待删", category="general")
    created = asyncio.run(mod.create_private_skill(body, agent_id="alice"))
    sid = created.skill_id

    try:
        result = asyncio.run(mod.delete_private_skill(sid, agent_id="alice"))
        assert result["code"] == 0, f"删除应返回 code=0, 实际: {result}"
        assert sid not in mod._private_skills, "删除后 _private_skills 不应再含该 sid"
    except TypeError as e:
        pytest.fail(f"delete_private_skill 不接受 agent_id kwarg: {e}")
    finally:
        mod._private_skills.clear()


# ─── 语义一致性: create→list 链路 ───


def test_create_then_list_roundtrip_uses_agent_id():
    """s6.7 集成契约: create_private_skill(agent_id=X) → list_private_skills(agent_id=X) 能查到

    这是 WARTN 2 的核心修复动机: 原参数不一致导致 create→list 链路断裂.
    """
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillCreate

    mod._private_skills.clear()

    # 用 agent_id 创建
    body = SkillCreate(name="roundtrip_skill", description="链路测试", category="general")
    asyncio.run(mod.create_private_skill(body, agent_id="bob"))

    # 用 agent_id 查询 (s2 修复: 聚合 _private_skills + SkillService)
    # 为隔离测试, mock SkillService 返回空列表
    mock_service = MagicMock()
    mock_service.list_skills.return_value = []
    with patch("neurova.skills.skill_service.SkillService", return_value=mock_service):
        result = asyncio.run(mod.list_private_skills(agent_id="bob"))

    names = {r.name for r in result}
    assert "roundtrip_skill" in names, (
        f"create(agent_id=bob) 后 list(agent_id=bob) 应查到 roundtrip_skill, "
        f"实际 names={names} (参数名不一致会导致 list 用默认 default 过滤掉 bob 的技能)"
    )

    mod._private_skills.clear()
