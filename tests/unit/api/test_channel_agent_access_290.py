# -*- coding: utf-8 -*-
"""默认智能体渠道的配置门：仅管理员可配（Issue #290 追问 ② 的红灯探针）。

## 用户问的那句话

「默认 agent 的渠道是否仅管理员可配置，其他用户不可配置」

## 核实到的现状（实现前实测）

`channel_config.py` 的 router 只挂 `Depends(get_current_user)`——**任何登录用户
都能读写任意 agent 的渠道配置**，含 `default`、含别人的 agent。而定论口径在
仓内早已收口到 `api/agent_access.py` 单源（`can_access_agent`：admin 全量 /
属主匹配 / **无主仅 admin**），chat 执行门、agent 列表/详情/写口、技能库审批面
都已接上，只有渠道配置这一面漏了——同一份契约少了一个消费方。

`default` 智能体是**无主 agent**（`api/app.py` 建它时不传 `owner_user_id`），
按单源口径即「仅 admin」——这正是用户问的那条语义，此前无门，故不成立。

## 判据（各带反向控制）

1. 非 admin 对 `default` 的读/写/删/测试全 403（现状一律 200/404，红灯）；
2. 非 admin 读**他人属主**的 agent 渠道 403（越权读写他人 bot 凭据）；
3. 反向控制：**属主自己**的 agent 渠道照常 200——门不得一刀切成"只有 admin 能用"；
4. 反向控制：admin 对未登记/虚构 agent 照常 200（门只裁权，不裁存在性——
   存在性判定属 agent 面，混进来会把 `a1`/`a2` 这类直配 agent 的既有链路打死）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_channel_access_290")

from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import channel_config as CC
from neurova.channels.manager import ChannelManager

ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}


def _agentWithOwner(agent_id: str, owner):
    return SimpleNamespace(
        agent_id=agent_id,
        config=SimpleNamespace(owner_user_id=owner, agent_id=agent_id),
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """真 HTTP 链路 + 真属主来源（app state 的 agent 实例），身份由 override 换。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(CC, "_create_adapter", lambda *a, **k: None)

    from neurova.api.endpoints import set_app_state

    set_app_state({
        # default：无主 agent（与 api/app.py 建它时的形态一致）
        "agents": {
            "default": _agentWithOwner("default", None),
            "kai": _agentWithOwner("kai", "u1"),
        }
    })

    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)

    ChannelManager._instance = None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, app, tmp_path
    app.dependency_overrides.clear()
    ChannelManager._instance = None
    set_app_state(None)


def _as(app, identity):
    app.dependency_overrides[auth_u] = lambda: dict(identity)


def _seedDefault(platform: str = "feishu"):
    CC._save_configs({platform: {"channel_type": platform, "enabled": True, "app_id": "bot-x"}})


# ── 1. default 视图：非 admin 一律拒绝 ─────────────────────────────


def test_defaultViewRejectedForNonAdminAcrossAllEndpoints(env):
    c, app, _ = env
    _seedDefault()
    _as(app, STRANGER)

    reads = c.get("/api/v1/channel-configs", params={"agent_id": "default"})
    write = c.post("/api/v1/channel-configs", params={"agent_id": "default"},
                   json={"channel_type": "telegram", "extra": {"bot_token": "t"}})
    delete = c.delete("/api/v1/channel-configs/feishu", params={"agent_id": "default"})
    one = c.get("/api/v1/channel-configs/feishu", params={"agent_id": "default"})
    probe = c.post("/api/v1/channel-configs/feishu/test", params={"agent_id": "default"},
                   json={"channel_type": "feishu", "app_id": "bot-x"})

    assert reads.status_code == 403, f"非 admin 读到了默认智能体的渠道配置: {reads.text}"
    assert write.status_code == 403, f"非 admin 写进了默认智能体的渠道配置: {write.text}"
    assert delete.status_code == 403, f"非 admin 删掉了默认智能体的渠道配置: {delete.text}"
    assert one.status_code == 403, f"非 admin 读到了默认智能体的单条配置: {one.text}"
    assert probe.status_code == 403, f"非 admin 拿默认智能体凭据发了测试连接: {probe.text}"


def test_ownerCanStillUseOwnAgent(env):
    """反向控制：属主自己的 agent 照常可配（门不是"只有 admin 能用"）。"""
    c, app, _ = env
    _as(app, OWNER)

    write = c.post("/api/v1/channel-configs", params={"agent_id": "kai"},
                   json={"channel_type": "feishu", "app_id": "bot-kai", "app_secret": "s"})
    reads = c.get("/api/v1/channel-configs", params={"agent_id": "kai"})

    assert write.status_code == 200, write.text
    assert reads.status_code == 200, reads.text
    assert [r["channel_type"] for r in reads.json()] == ["feishu"]


def test_strangerRejectedOnSomeoneAgent(env):
    """非属主读写他人 agent 的 bot 凭据必须拒绝（此前一律放行）。"""
    c, app, _ = env
    _as(app, OWNER)
    c.post("/api/v1/channel-configs", params={"agent_id": "kai"},
           json={"channel_type": "feishu", "app_id": "bot-kai", "app_secret": "secret"})

    _as(app, STRANGER)
    reads = c.get("/api/v1/channel-configs", params={"agent_id": "kai"})
    write = c.post("/api/v1/channel-configs", params={"agent_id": "kai"},
                   json={"channel_type": "telegram", "extra": {"bot_token": "t"}})

    assert reads.status_code == 403, f"非属主读到了他人 agent 的渠道配置: {reads.text}"
    assert write.status_code == 403, f"非属主写进了他人 agent 的渠道配置: {write.text}"


def test_adminKeepsFullAccessIncludingUnregisteredAgent(env):
    """admin 全量；且门不裁存在性——未登记 agent 仍可直配（既有链路零破坏）。"""
    c, app, _ = env
    _as(app, ADMIN)

    write = c.post("/api/v1/channel-configs", params={"agent_id": "a9"},
                   json={"channel_type": "feishu", "app_id": "bot-a9"})
    reads = c.get("/api/v1/channel-configs", params={"agent_id": "a9"})

    assert write.status_code == 200, write.text
    assert reads.status_code == 200
    assert [r["channel_type"] for r in reads.json()] == ["feishu"]
