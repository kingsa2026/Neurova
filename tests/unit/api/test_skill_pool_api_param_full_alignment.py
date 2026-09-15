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


# ─── 行为契约: 接受 agent_id kwarg（Wave F 演化：内存 dict 已废除，
# 以"迷你 manifest"服务替身保住 s6 原意——agent_id 参数被接受且
# create→list 链路在 agent 视图内闭环）───


class _MiniService:
    """dict 版 SkillService 替身（按 agent 分目录的 manifest 语义）。"""

    _stores = {}

    def __init__(self, agent_id, **kwargs):
        self.agent_id = agent_id
        self._skills = _MiniService._stores.setdefault(agent_id, {})

    def register_auto_skill(self, skill_id, name, description="", version="1.0.0", config=None, manifest_source="auto"):
        if skill_id in self._skills:
            return False
        self._skills[skill_id] = {
            "name": name, "description": description, "version": version,
            "enabled": True, "path": "", "usage": {},
            "manifest": {"source": manifest_source, "config": dict(config or {})},
        }
        return True

    def get_skill_info(self, skill_id):
        return self._skills.get(skill_id)

    def update_auto_skill(self, skill_id, version=None, config=None, name=None, description=None):
        entry = self._skills.get(skill_id)
        if entry is None:
            return False
        if name is not None:
            entry["name"] = name
        if description is not None:
            entry["description"] = description
        if config is not None:
            entry["manifest"]["config"] = dict(config)
        return True

    def uninstall_skill(self, skill_id):
        if self._skills.pop(skill_id, None) is None:
            return {"success": False, "error": "not found"}
        return {"success": True}

    def iter_skills(self):
        return list(self._skills.items())


@pytest.fixture
def mini(tmp_path, monkeypatch):
    _MiniService._stores = {}
    monkeypatch.setattr("neurova.skills.skill_service.SkillService", _MiniService)
    return _MiniService


def _create(name, desc, agent_id):
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillCreate

    return asyncio.run(mod.create_private_skill(SkillCreate(name=name, description=desc), agent_id=agent_id))


def test_create_private_skill_accepts_agent_id_kwarg(mini):
    """s6.4 演化: create_private_skill 接受 agent_id kwarg 且落对应视图。"""
    info = _create("test_skill", "测试", "alice")
    assert info.owner_id == "alice"
    assert "alice" in mini._stores and mini._stores["alice"], "技能应落 alice 视图"


def test_update_private_skill_accepts_agent_id_kwarg(mini):
    """s6.5 演化: update 接受 agent_id 且改动落回同一视图。"""
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillUpdate

    created = _create("old_name", "旧", "alice")
    result = asyncio.run(
        mod.update_private_skill(created.skill_id, SkillUpdate(name="new_name"), agent_id="alice")
    )
    assert result.name == "new_name"


def test_delete_private_skill_accepts_agent_id_kwarg(mini):
    """s6.6 演化: delete 接受 agent_id 并从视图移除。"""
    from neurova.api.endpoints import skill_pool_api as mod

    created = _create("to_delete", "待删", "alice")
    result = asyncio.run(mod.delete_private_skill(created.skill_id, agent_id="alice"))
    assert result["code"] == 0
    assert created.skill_id not in mini._stores["alice"]


def test_create_then_list_roundtrip_uses_agent_id(mini):
    """s6.7 演化: create(agent_id=bob) → list(agent_id=bob) 查到；
    其他 agent 视图查不到（目录级隔离，参数名不一致即链路断）。"""
    from neurova.api.endpoints import skill_pool_api as mod

    _create("roundtrip_skill", "链路测试", "bob")

    names = {r.name for r in asyncio.run(mod.list_private_skills(agent_id="bob"))}
    assert "roundtrip_skill" in names, (
        f"create/list 同 agent_id 链路必须闭环, 实际 names={names}"
    )
    other = {r.name for r in asyncio.run(mod.list_private_skills(agent_id="someone_else"))}
    assert "roundtrip_skill" not in other, "视图不得串"
