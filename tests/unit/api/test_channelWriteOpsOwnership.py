# -*- coding: utf-8 -*-
"""渠道写操作端点的属主门（CHAN-01，2026-11-25 全仓审计·批次 C）。

同一份渠道管理面里 restart / clear-queue / webhook 三件已有 requireAgentOwner
归属门（test_channel_mgmt_access_290.py），但 connect / disconnect / send 三个
写口仍只验登录：
- POST /{type}/connect    —— 可覆盖他人渠道的运行凭据（app_id/app_secret/extra）；
- POST /{type}/disconnect —— 可拆掉他人 bot 的长连接；
- POST /{type}/send       —— 可冒充他人 bot 代发消息。

判据（与 290 批同源同形，门复用 requireAgentOwner 单源）：非属主 → 403
（且动作不发生、凭据不被改）；属主与 admin 照常（反向控制）；default（无主
agent）仅 admin。
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_channel_writes_01")

from neurova.api.deps import get_current_user as auth_u
from neurova.api.endpoints import channels as ch
from neurova.api.endpoints import set_app_state
from neurova.channels.base import ChannelConfig
from neurova.channels.manager import ChannelManager

ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}
PREFIX = "/api/v1/channel-adapters"


class _FakeAdapter:
    """最小真适配器：connect/disconnect/send 都记数，凭据可被端点改写。"""

    def __init__(self, channel_type):
        self.channel_type = channel_type
        self.config = ChannelConfig(channel_type=channel_type,
                                    app_id="orig-app", app_secret="orig-sec")
        self.is_connected = True
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.sent = []

    def set_event_callback(self, cb):
        self.cb = cb

    async def connect(self):
        self.connect_calls += 1
        self.is_connected = True
        return True

    async def disconnect(self):
        self.disconnect_calls += 1
        self.is_connected = False

    async def send_message(self, chat_id, content, message_type="text", **kwargs):
        self.sent.append((chat_id, content, message_type))
        return "msg-1"


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
    app.include_router(ch.router, prefix=PREFIX)
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, app
    app.dependency_overrides.clear()
    ChannelManager._instance = None
    set_app_state(None)


def _as(app, identity):
    app.dependency_overrides[auth_u] = lambda: dict(identity)


def _register(agent_id: str, channel_type: str = "feishu") -> _FakeAdapter:
    from neurova.channels.manager import get_channel_manager

    adapter = _FakeAdapter(channel_type)
    get_channel_manager().register_adapter(adapter, agent_id=agent_id)
    return adapter


class TestConnectIsOwnerGated:
    def test_strangerCannotConnectOthersChannel(self, env):
        """非属主 connect：拒，且不得覆盖他人运行凭据、不得重连他人 bot。"""
        c, app = env
        adapter = _register("kai")
        _as(app, STRANGER)

        r = c.post(f"{PREFIX}/feishu/connect", params={"agent_id": "kai"},
                   json={"app_id": "evil-app", "app_secret": "evil-sec"})

        assert r.status_code == 403, f"非属主改写了他人渠道凭据: {r.text}"
        assert adapter.config.app_id == "orig-app", "他人渠道的 app_id 被覆盖"
        assert adapter.config.app_secret == "orig-sec", "他人渠道的 app_secret 被覆盖"
        assert adapter.connect_calls == 0, "他人渠道被重连"

    def test_ownerCanConnectOwnChannel(self, env):
        """反向控制：属主本人照常连接并更新自己渠道的凭据。"""
        c, app = env
        adapter = _register("kai")
        _as(app, OWNER)

        r = c.post(f"{PREFIX}/feishu/connect", params={"agent_id": "kai"},
                   json={"app_id": "new-app", "use_stream": False})

        assert r.status_code == 200, r.text
        assert adapter.config.app_id == "new-app"
        assert adapter.connect_calls == 1

    def test_adminCanConnectAnyChannel(self, env):
        c, app = env
        adapter = _register("kai")
        _as(app, ADMIN)

        r = c.post(f"{PREFIX}/feishu/connect", params={"agent_id": "kai"}, json={})

        assert r.status_code == 200, r.text
        assert adapter.connect_calls == 1


class TestDisconnectIsOwnerGated:
    def test_strangerCannotDisconnectOthersBot(self, env):
        """非属主 disconnect：拒，他人的长连接不被拆。"""
        c, app = env
        adapter = _register("kai")
        _as(app, STRANGER)

        r = c.post(f"{PREFIX}/feishu/disconnect", params={"agent_id": "kai"})

        assert r.status_code == 403, f"非属主拆了他人 bot 的长连接: {r.text}"
        assert adapter.disconnect_calls == 0 and adapter.is_connected, "他人渠道被断开"

    def test_ownerCanDisconnectOwnBot(self, env):
        c, app = env
        adapter = _register("kai")
        _as(app, OWNER)

        r = c.post(f"{PREFIX}/feishu/disconnect", params={"agent_id": "kai"})

        assert r.status_code == 200, r.text
        assert adapter.disconnect_calls == 1 and not adapter.is_connected

    def test_defaultAgentMgmtIsAdminOnly(self, env):
        """default 是无主 agent：非管理员连它的渠道也动不了。"""
        c, app = env
        adapter = _register("default")
        _as(app, OWNER)

        r = c.post(f"{PREFIX}/feishu/disconnect", params={"agent_id": "default"})

        assert r.status_code == 403, f"非管理员断开了默认智能体的渠道: {r.text}"
        assert adapter.disconnect_calls == 0


class TestSendIsOwnerGated:
    def test_strangerCannotSendAsOthersBot(self, env):
        """非属主 send：拒，且一条消息都不许发出去（门在 manager 之前）。"""
        c, app = env
        adapter = _register("kai")
        _as(app, STRANGER)
        from neurova.channels.manager import get_channel_manager

        mgr = get_channel_manager()
        original = mgr.send_message

        async def _spy(**kwargs):
            adapter.sent.append(kwargs)
            return "should-not-happen"

        mgr.send_message = _spy
        try:
            r = c.post(f"{PREFIX}/feishu/send", params={"agent_id": "kai"},
                       json={"chat_id": "oc_x", "content": "hi"})
        finally:
            mgr.send_message = original

        assert r.status_code == 403, f"非属主借他人 bot 代发了消息: {r.text}"
        assert adapter.sent == [], "门被绕过：消息真的发出去了"

    def test_ownerCanSendViaOwnBot(self, env):
        """反向控制：属主走真发送链路（manager → adapter）照常发。"""
        c, app = env
        adapter = _register("kai")
        _as(app, OWNER)

        r = c.post(f"{PREFIX}/feishu/send", params={"agent_id": "kai"},
                   json={"chat_id": "oc_x", "content": "hello"})

        assert r.status_code == 200, r.text
        assert r.json()["success"] is True, r.text
        assert adapter.sent == [("oc_x", "hello", "text")], adapter.sent

    def test_adminCanSendViaAnyBot(self, env):
        c, app = env
        adapter = _register("kai")
        _as(app, ADMIN)

        r = c.post(f"{PREFIX}/feishu/send", params={"agent_id": "kai"},
                   json={"chat_id": "oc_x", "content": "hello"})

        assert r.status_code == 200, r.text
        assert adapter.sent == [("oc_x", "hello", "text")], adapter.sent
