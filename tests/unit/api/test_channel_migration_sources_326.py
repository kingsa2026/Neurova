# -*- coding: utf-8 -*-
"""存量渠道迁移的「候选源 / 可迁渠道」读面（Issue #326 第 1、2 条）。

## 用户拍的两条

1.「选择迁移后，首先选择从哪个 agent 迁移，即源（需要按用户隔离），现状无选择需要迁移的源」
2.「选择完源后，选择既有的渠道（勾选/全选），现状无选择需要迁移的渠道」

第 2 条的**端点能力已存在**（`migrate-agent` 的 `channel_types` 收窄，
见 test_channel_agent_migration_290.py 的 `test_migrationCanBeScopedToSomeChannels`），
缺的是让用户**看见有哪些可选**：前端此前只会一键把 `default` 整表搬走
（`migrateAgentChannelConfigs('default', target)`），源不可选、渠道也不可选。

故本轮补的是候选面这一读端点。它与迁移端点是**同一道归属门**：能不能列出来，
取决于能不能迁走 —— 否则会出现"列出来的源点下去 403"的假选项（多一个可点的
死路，比没有选项更坏）。

## 判据

1. 只列**有渠道**的候选源（空源列出来，点下去只会得到 `migrated: []`）；
2. 候选源与迁移门**同口径**（教义第 6 条：不新造第二套归属判定）——
   非 admin 只看得见自己属主的 agent，`default`（无主）仅 admin；
3. 目标自身不出现在候选里（迁给自己是 400，不该被列成一个可选项）；
4. 每条候选点名名下**有哪些渠道** —— 第 2 条的勾选/全选靠它，不为此再发 N 次请求。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_channel_migration_sources_326")

from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import channel_config as CC
from neurova.channels.manager import ChannelManager

ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}

SOURCES_URL = "/api/v1/channel-configs/migration-sources"


def _agentWithOwner(agent_id: str, owner):
    return SimpleNamespace(
        agent_id=agent_id,
        config=SimpleNamespace(owner_user_id=owner, agent_id=agent_id),
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))

    from neurova.api.endpoints import set_app_state

    set_app_state({
        "agents": {
            "default": _agentWithOwner("default", None),   # 与 api/app.py 同形：无主
            "kai": _agentWithOwner("kai", "u1"),
            "other": _agentWithOwner("other", "u2"),
        }
    })

    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)

    ChannelManager._instance = None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, app
    app.dependency_overrides.clear()
    ChannelManager._instance = None
    set_app_state(None)


def _as(app, identity):
    app.dependency_overrides[auth_u] = lambda: dict(identity)


def _seed(agent_id: str, types):
    """按真实 v2 文件形状落盘某 agent 的渠道配置。"""
    store = CC._load_store()
    store["agents"].setdefault(agent_id, {}).update({
        p: {"channel_type": p, "enabled": True, "app_id": f"{agent_id}-{p}",
            "app_secret": "s", "extra": {}}
        for p in types
    })
    CC._save_store(store)


def _sources(r):
    return {s["agent_id"]: list(s["channels"]) for s in r.json()["sources"]}


def test_listsOnlyAgentsThatOwnChannels(env):
    """判据 1：空源不入候选 —— 列出来点下去只会得到「什么都没迁」。"""
    c, app = env
    _seed("default", ["feishu", "dingtalk"])
    _seed("kai", [])
    _seed("other", ["telegram"])
    _as(app, ADMIN)

    r = c.get(SOURCES_URL)

    assert r.status_code == 200, r.text
    assert _sources(r) == {"default": ["dingtalk", "feishu"], "other": ["telegram"]}


def test_candidateSourcesShareTheMigrationGate(env):
    """判据 2：候选面与迁移门同口径 —— 非 admin 看不见无主/他人的 agent。

    反向控制（同一判据的另一半）：admin 必须看得见全部三条，否则"看不见"可能只是
    实现把所有人一起滤掉了。
    """
    c, app = env
    _seed("default", ["feishu"])
    _seed("kai", ["telegram"])
    _seed("other", ["qq"])

    _as(app, OWNER)
    assert _sources(c.get(SOURCES_URL)) == {"kai": ["telegram"]}, "非属主的源不该出现"

    _as(app, STRANGER)
    assert _sources(c.get(SOURCES_URL)) == {"other": ["qq"]}

    _as(app, ADMIN)
    assert sorted(_sources(c.get(SOURCES_URL))) == ["default", "kai", "other"]


def test_targetIsNotOfferedAsItsOwnSource(env):
    """判据 3：迁给自己是 400，候选面不许把它列成一个可选项。"""
    c, app = env
    _seed("default", ["feishu"])
    _seed("kai", ["telegram"])
    _as(app, ADMIN)

    r = c.get(SOURCES_URL, params={"to_agent_id": "kai"})

    assert r.status_code == 200, r.text
    assert _sources(r) == {"default": ["feishu"]}


def test_candidateCarriesItsChannelList(env):
    """判据 4：渠道清单随候选一次带回（勾选/全选的数据面），且顺序确定。"""
    c, app = env
    _seed("default", ["qq", "feishu", "dingtalk"])
    _as(app, ADMIN)

    r = c.get(SOURCES_URL, params={"to_agent_id": "kai"})

    assert r.status_code == 200, r.text
    assert _sources(r)["default"] == ["dingtalk", "feishu", "qq"], "渠道清单须稳定排序"
