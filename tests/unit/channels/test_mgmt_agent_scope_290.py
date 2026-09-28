# -*- coding: utf-8 -*-
"""管理面 agent 盲：restart / clear-queue / conflicts 三端点必须带 agent 维度
（Issue #290 未闭环项③ —— 红灯探针，实现前跑）。

判据（各带反向控制）：
1. 三端点接受 agent_id 形参，缺省仍为 default（向后兼容）；
2. **按 agent 取实例**：非 default 身份的 restart/clear-queue 动的是**该 agent**
   的适配器，不是 default 的同平台实例；
3. conflict 扫描面覆盖全量 agent（不是只扫 default 视图）；
4. 反向控制：不存在的 agent 诚实失败（不复用 default 实例冒充成功）。
"""
from __future__ import annotations

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_mgmt_agent_0123")

from neurova.api.deps import get_current_user as auth_u
from neurova.api.endpoints import channels as ch
from neurova.channels.base import ChannelConfig
from neurova.channels.manager import ChannelManager

ADMIN = {"user_id": "u", "username": "u", "role": "admin"}


class _CountingAdapter:
    def __init__(self, channel_type, app_id=""):
        self.channel_type = channel_type
        self.config = ChannelConfig(channel_type=channel_type, app_id=app_id)
        self.is_connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0

    def set_event_callback(self, cb):
        self.cb = cb

    async def connect(self):
        self.connect_calls += 1
        self.is_connected = True
        return True

    async def disconnect(self):
        self.disconnect_calls += 1
        self.is_connected = False


@pytest.fixture()
def api(tmp_path):
    ChannelManager._instance = None
    app = FastAPI()
    app.include_router(ch.router, prefix="/api/v1/channel-adapters")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    ChannelManager._instance = None


def test_restart_targetsTheAgentInstance(api):
    from neurova.channels.manager import get_channel_manager

    mgr = get_channel_manager()
    default_adapter = _CountingAdapter("feishu", app_id="d")
    kai_adapter = _CountingAdapter("feishu", app_id="k")
    mgr.register_adapter(default_adapter, agent_id="default")
    mgr.register_adapter(kai_adapter, agent_id="kai")

    r = api.post("/api/v1/channel-adapters/feishu/restart", params={"agent_id": "kai"})

    assert r.status_code == 200, r.text
    assert kai_adapter.disconnect_calls == 1, "重启动的不是该 agent 的实例（管理面 agent 盲）"
    assert default_adapter.disconnect_calls == 0, "重启串到了 default 的同平台实例"


def test_clearQueueScopedToAgent(api):
    from neurova.channels.manager import get_channel_manager
    from neurova.channels.base import ChannelMessage
    from datetime import datetime

    mgr = get_channel_manager()
    mgr.register_adapter(_CountingAdapter("feishu"), agent_id="default")

    def msg(mid, agent):
        return ChannelMessage(
            message_id=mid, channel_type="feishu", chat_id="c", sender_id="u",
            sender_name="u", content="hi", message_type="text",
            timestamp=datetime.now(), metadata={"agent_id": agent},
        )

    import tempfile
    from pathlib import Path
    from neurova.channels.channel_ingress_queue import ChannelIngressQueue

    with tempfile.TemporaryDirectory() as d:
        q = ChannelIngressQueue(db_path=str(Path(d) / "q.db"))
        mgr.ingress_queue = q
        try:
            q.enqueue(msg("d1", "default"))
            q.enqueue(msg("k1", "kai"))
            q.enqueue(msg("k2", "kai"))

            r = api.post("/api/v1/channel-adapters/feishu/clear-queue", params={"agent_id": "kai"})

            assert r.status_code == 200, r.text
            assert r.json()["data"]["cleared"] == 2, "清队列没按 agent 收口"
            assert q.stats()["pending"] == 1, "default 的 pending 被一起清了（串台）"
        finally:
            q.close()
            mgr.ingress_queue = None


def test_conflictCheckScansEveryAgent(api):
    from neurova.channels.manager import get_channel_manager

    mgr = get_channel_manager()
    a = _CountingAdapter("feishu", app_id="shared")
    b = _CountingAdapter("dingtalk", app_id="shared")
    mgr.register_adapter(a, agent_id="kai")
    mgr.register_adapter(b, agent_id="default")

    r = api.get("/api/v1/channel-adapters/conflicts/check", params={"agent_id": "kai"})

    assert r.status_code == 200, r.text
    conflicts = r.json()["data"]["conflicts"]
    assert len(conflicts) == 1, "跨 agent 的同身份渠道未被检出（管理面 agent 盲）"


def test_unknownAgentFailsHonest(api):
    from neurova.channels.manager import get_channel_manager

    mgr = get_channel_manager()
    mgr.register_adapter(_CountingAdapter("feishu"), agent_id="default")

    r = api.post("/api/v1/channel-adapters/feishu/restart", params={"agent_id": "ghost"})

    body = r.json()
    assert body.get("success") is False or body.get("code") == 1, (
        "不存在的 agent 被 default 实例冒充成功（诚实报错纪律）"
    )
