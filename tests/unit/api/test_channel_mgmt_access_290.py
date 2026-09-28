# -*- coding: utf-8 -*-
"""渠道管理面三端点的归属门（Issue #290 追问② 同一根因的第三批命中点）。

## 为什么这批不能漏

教义第 5 条：一个断链被点名后，**同一契约的全部消费方**要一并修。

`/channel-configs` 加了归属门，但**同一份渠道配置的第二套操作面**是
`/channel-adapters`（restart / clear-queue / conflicts，Issue #290 未闭环项③
给它们补了 agent 维度）。它们此前只挂 `Depends(get_current_user)`，而这三个是
**破坏性运维动作**：

- restart：拆掉该 agent 的 bot 长连接再重连——任何登录用户都能让别人的机器人掉线；
- clear-queue：清空该 agent 的入站积压——别人的待处理消息被就地删掉；
- conflicts：列出全量实例的平台身份——别人的 bot 身份（app_id）从中可读。

只锁配置面不锁管理面，等于把同一道门留在旁边的入口上。

判据：非管理员/非属主 → 403；属主与管理员照常（反向控制）。
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_channel_mgmt_290")

from neurova.api.deps import get_current_user as auth_u
from neurova.api.endpoints import channels as ch
from neurova.api.endpoints import set_app_state
from neurova.channels.base import ChannelConfig
from neurova.channels.manager import ChannelManager

ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}


class _CountingAdapter:
    def __init__(self, channel_type):
        self.channel_type = channel_type
        self.config = ChannelConfig(channel_type=channel_type)
        self.is_connected = False

    def set_event_callback(self, cb):
        self.cb = cb

    async def connect(self):
        self.is_connected = True
        return True

    async def disconnect(self):
        self.is_connected = False


def _agentWithOwner(agent_id, owner):
    from types import SimpleNamespace

    return SimpleNamespace(
        agent_id=agent_id,
        config=SimpleNamespace(owner_user_id=owner, agent_id=agent_id),
    )


@pytest.fixture()
def env():
    set_app_state({"agents": {
        "default": _agentWithOwner("default", None),
        "kai": _agentWithOwner("kai", "u1"),
    }})
    ChannelManager._instance = None
    app = FastAPI()
    app.include_router(ch.router, prefix="/api/v1/channel-adapters")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, app
    app.dependency_overrides.clear()
    ChannelManager._instance = None
    set_app_state(None)


def _as(app, identity):
    app.dependency_overrides[auth_u] = lambda: dict(identity)


def _register(agent_id: str, channel_type: str = "feishu"):
    from neurova.channels.manager import get_channel_manager

    adapter = _CountingAdapter(channel_type)
    get_channel_manager().register_adapter(adapter, agent_id=agent_id)
    return adapter


def test_restartIsGatedOnAgentOwnership(env):
    c, app = env
    _register("kai")
    _as(app, STRANGER)

    r = c.post("/api/v1/channel-adapters/feishu/restart", params={"agent_id": "kai"})

    assert r.status_code == 403, f"非属主重启了他人 agent 的渠道（拆别人的长连接）: {r.text}"


def test_clearQueueIsGatedOnAgentOwnership(env):
    c, app = env
    _register("kai")
    _as(app, STRANGER)

    r = c.post("/api/v1/channel-adapters/feishu/clear-queue", params={"agent_id": "kai"})

    assert r.status_code == 403, f"非属主清空了他人 agent 的队列（删别人的待处理消息）: {r.text}"


def test_defaultViewMgmtIsAdminOnly(env):
    """default 是无主 agent：非管理员连它的管理面也动不了。"""
    c, app = env
    _register("default")
    _as(app, OWNER)

    r = c.post("/api/v1/channel-adapters/feishu/restart", params={"agent_id": "default"})

    assert r.status_code == 403, f"非管理员重启了默认智能体的渠道: {r.text}"


def test_conflictCheckRejectsNonAdmin(env):
    """冲突检测列的是**全量实例的平台身份**——非管理员从中可读别人的 bot 身份。"""
    c, app = env
    _register("kai")
    _as(app, OWNER)

    r = c.get("/api/v1/channel-adapters/conflicts/check")

    assert r.status_code == 403, f"非管理员读到了全量渠道身份清单: {r.text}"


def test_ownerAndAdminStillWork(env):
    """反向控制：门不得一刀切成"只有管理员能用"。"""
    c, app = env
    _register("kai")

    _as(app, OWNER)
    owner_view = c.post("/api/v1/channel-adapters/feishu/restart", params={"agent_id": "kai"})
    assert owner_view.status_code == 200, owner_view.text

    _as(app, ADMIN)
    admin_view = c.post("/api/v1/channel-adapters/feishu/clear-queue", params={"agent_id": "kai"})
    assert admin_view.status_code == 200, admin_view.text
