"""Wave H-W0 属主治理（三层技能库前置安全）

现状（三层库侦查坐实）：agent 的 owner_user_id 创建→落盘→重启链已通，但——
①list_agents/get_agent 无鉴权无过滤（任何登录用户看到全库 agent，含他人）；
②update/delete 仅 Depends(get_current_user)，登录即可改/删**他人** agent——
三层技能库后这等于绕过"不可调用别的用户私库"（改其 agent 配置/删除）；
③channel_router 读 `getattr(agent,"owner_user_id")`（字段在 .config 上）恒
None → 渠道会话归属链断裂；④中枢登记 agents.json 无 owner。

口径：与 chat 现行执行门完全一致（admin 全量；非 admin 仅 owner==self；
**无 owner 仅 admin**）——显示对齐执行，不再出现"列表可见、对话被拒"的
误导态。判定单源 `agent_access.can_access_agent`，chat/agent 两端点共用。
"""

import asyncio
import inspect
from types import SimpleNamespace

import pytest


class _Req:
    """最小 Request 替体（端点只用 request 透传/取 id）。"""

    headers = {}

    class _S:
        user_id = "x"

    state = _S()


# ── 单源判定函数语义 ───────────────────────────────────────


def test_access_matrix():
    from neurova.api.agent_access import can_access_agent

    assert can_access_agent("u1", "user", owner="u1") is True
    assert can_access_agent("u1", "user", owner="u2") is False
    assert can_access_agent("u1", "user", owner=None) is False
    assert can_access_agent("u1", "user", owner="") is False
    assert can_access_agent("root", "admin", owner="u2") is True
    assert can_access_agent("root", "admin", owner=None) is True


def test_chat_gate_delegates_to_single_source():
    """chat 的执行门改由单源承载（行为不变，杜绝双实现漂移）。"""
    from neurova.api.endpoints import chat

    src = inspect.getsource(chat._user_can_access_agent)
    assert "can_access_agent" in src, "chat 门应委托 agent_access 单源"


# ── list/get 过滤 ──────────────────────────────────────────


class _Cfg:
    def __init__(self, owner):
        self.owner_user_id = owner


class _Agent:
    def __init__(self, agent_id, owner):
        self.agent_id = agent_id
        self.name = agent_id
        self.config = _Cfg(owner)


@pytest.fixture
def app_env(monkeypatch):
    from neurova.api.endpoints import agent as agent_ep

    agents = {
        "mine": _Agent("mine", "u1"),
        "theirs": _Agent("theirs", "u2"),
        "orphan": _Agent("orphan", None),
    }
    monkeypatch.setattr(agent_ep, "_get_app_state", lambda: {"agents": agents})
    monkeypatch.setattr(agent_ep, "get_agent_from_state", lambda agent_id: agents.get(agent_id))

    class _CM:
        def list_agents(self):
            return []

    monkeypatch.setattr(agent_ep, "get_agent_config_manager", lambda: _CM())
    # agent_to_info 真身读一堆属性——直接透传最小信息（属主治理只关心 owner 面）
    monkeypatch.setattr(
        agent_ep,
        "agent_to_info",
        lambda a: {
            "agent_id": a.agent_id,
            "name": a.name,
            "status": "running",
            "owner_user_id": getattr(a.config, "owner_user_id", None),
        },
    )
    return agent_ep, agents


def _list(agent_ep, user):
    return asyncio.run(agent_ep.list_agents(_Req(), current_user=user))


_U1 = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
_ROOT = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "root"}


def test_list_agents_filtered_by_owner(app_env):
    agent_ep, _ = app_env
    ids = {a.agent_id for a in _list(agent_ep, _U1)}
    assert ids == {"mine"}, f"非 admin 只见自己 owner 的 agent，实际 {ids}"
    ids_admin = {a.agent_id for a in _list(agent_ep, _ROOT)}
    assert ids_admin == {"mine", "theirs", "orphan"}


def test_agent_info_exposes_owner(app_env):
    agent_ep, _ = app_env
    rows = _list(agent_ep, _ROOT)
    owners = {r.agent_id: getattr(r, "owner_user_id", "MISSING") for r in rows}
    assert owners["mine"] == "u1", "AgentInfo 回传 owner（前端属主徽标数据源）"


def test_get_agent_non_owner_404(app_env):
    """他人 agent 详情按 deny≡404（防枚举，aigc 账本先例）。"""
    from fastapi import HTTPException

    agent_ep, agents = app_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_ep.get_agent(_Req(), "theirs", current_user=_U1))
    assert exc.value.status_code == 404


# ── 写口属主校验 ───────────────────────────────────────────


def test_update_agent_non_owner_403(app_env):
    from fastapi import HTTPException

    from neurova.api.endpoints.agent import UpdateAgentRequest

    agent_ep, _agents = app_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_ep.update_agent(_Req(), "theirs", UpdateAgentRequest(name="hijack"), _U1))
    assert exc.value.status_code == 403


def test_update_agent_orphan_non_admin_403(app_env):
    from fastapi import HTTPException

    from neurova.api.endpoints.agent import UpdateAgentRequest

    agent_ep, _agents = app_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_ep.update_agent(_Req(), "orphan", UpdateAgentRequest(name="x"), _U1))
    assert exc.value.status_code == 403


def test_delete_agent_non_owner_403(app_env):
    from fastapi import HTTPException

    agent_ep, agents = app_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_ep.delete_agent(_Req(), "theirs", _U1))
    assert exc.value.status_code == 403
    assert "theirs" in agents, "拒绝路径不得先执行删除副作用"


def test_delete_agent_orphan_non_admin_403(app_env):
    from fastapi import HTTPException

    agent_ep, agents = app_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_ep.delete_agent(_Req(), "orphan", _U1))
    assert exc.value.status_code == 403


# ── 渠道归属读对象修复 ─────────────────────────────────────


def test_channel_router_reads_config_owner():
    """渠道 owner 读 agent.config.owner_user_id（原 getattr(agent,...) 恒 None）。"""
    from neurova.channels import channel_router

    src = inspect.getsource(channel_router)
    assert 'getattr(agent, "owner_user_id", "")' not in src, "旧读法（恒 None）必须移除"
    assert "owner_user_id" in src
