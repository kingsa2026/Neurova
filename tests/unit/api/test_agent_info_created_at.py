# -*- coding: utf-8 -*-
"""AgentInfo.created_at 投影赋值断链（U1 复核发现·R7 必做）。

agent.py 的 AgentInfo 声明了 created_at（:223），但全部投影构造点从不赋值——
响应恒 null，鸿蒙端 AgentsApi.createdAt（dc4cc4949 改读 created_at）因此恒空串。
事实源已存在：AgentConfigManager 的 cfg 字典创建时写入 created_at
（agent_config.py:240），读取时带回（:167）。本档钉住两条投影路径：
1. config_only 分支（state 无该 agent，走持久化 cfg）；
2. 运行态分支（state 装配的 agent）。
cfg 无 created_at 时维持 None（诚实缺省，不编造）。
"""

import asyncio
from types import SimpleNamespace

from neurova.api.endpoints import agent as agent_ep
from neurova.api.endpoints import set_app_state

_ADMIN = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "root"}
_CREATED = "2026-11-17T09:00:00"


class _Req:
    headers = {}

    class _S:
        user_id = "x"

    state = _S()


class _Cfg:
    def __init__(self, agent_id, owner):
        self.agent_id = agent_id
        self.name = agent_id
        self.description = ""
        self.owner_user_id = owner


class _Agent:
    def __init__(self, agent_id, owner):
        self.agent_id = agent_id
        self.name = agent_id
        self.config = _Cfg(agent_id, owner)


def _patch_cfg_manager(monkeypatch, created):
    class _CM:
        def list_agents(self):
            return [{"id": "a1", "created_at": created}]

        def get_agent(self, agent_id):
            if agent_id == "a1":
                return {"id": "a1", "created_at": created}
            return None

    monkeypatch.setattr(agent_ep, "get_agent_config_manager", lambda: _CM())


def test_config_only_branch_returns_created_at(monkeypatch):
    """config_only 分支（state 无该 agent，走持久化 cfg）必须回传 created_at。"""
    set_app_state({"agents": {}})
    _patch_cfg_manager(monkeypatch, _CREATED)
    info = asyncio.run(agent_ep.get_agent(_Req(), "a1", _ADMIN))
    assert info.created_at == _CREATED, (
        f"config_only 投影必须回传 cfg 的 created_at，实得 {info.created_at!r}（恒 null 即断链未修）"
    )


def test_running_agent_branch_returns_created_at(monkeypatch):
    """运行态分支（state 装配的 agent）同样回传持久化 cfg 的 created_at。"""
    set_app_state({"agents": {"a1": _Agent("a1", "root")}})
    _patch_cfg_manager(monkeypatch, _CREATED)
    infos = asyncio.run(agent_ep.list_agents(_Req(), _ADMIN))
    hit = [a for a in infos if a.agent_id == "a1"]
    assert hit, "运行态 agent 应出现在列表"
    assert hit[0].created_at == _CREATED, (
        f"运行态投影必须回传 cfg 的 created_at，实得 {hit[0].created_at!r}"
    )


def test_missing_created_at_stays_none(monkeypatch):
    """cfg 没有 created_at（存量形态）→ 维持 None 诚实缺省，不得编造。"""
    set_app_state({"agents": {}})
    _patch_cfg_manager(monkeypatch, "")
    info = asyncio.run(agent_ep.get_agent(_Req(), "a1", _ADMIN))
    assert info.created_at is None
