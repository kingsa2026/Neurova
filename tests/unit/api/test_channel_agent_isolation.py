"""渠道按 agent 多实例隔离——Phase A 后端核心回归（2026-09-13，对齐 QwenPaw 路由）。

契约（docs/渠道agent隔离改造计划_2026-09-13.md）：
1. 存储升 v2 `{version:2, agents:{agent_id:{channel_type:cfg}}}`；v1 平铺首载迁移进 default；
2. /v1/channel-configs 全端点加 agent_id（Query 默认 "default" 保旧调用兼容）；
3. manager 双视图：`_adapters[type]`=default agent 兼容视图（12 处既有 get_adapter 零破坏），
   `_agent_adapters[(agent_id,type)]`=全量实例表；register_adapter(adapter, agent_id=...)；
4. 装配期绑定（QP 式"adapter 实例即路由"）：事件回调按来源实例携带 agent，入站消息
   dispatch 时 metadata["agent_id"] 可见（替换 manager.py:373 硬编码 default 的数据通路）；
5. 配置级身份冲突检测：两 agent 配同 app_id/bot_token → 第二个保存 409。
"""
import importlib
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_agent_channels_0123")

from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import channel_config as CC
from neurova.channels.manager import ChannelManager
from neurova.channels.base import ChannelMessage

ADMIN = {"user_id": "u", "username": "u", "role": "admin"}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(CC, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(CC, "CONFIG_FILE", tmp_path / "channel_configs.json")
    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    # 保存路径上的适配器注册走 to_thread 工厂——测试里禁真网络：工厂返回 None
    monkeypatch.setattr(CC, "_create_adapter", lambda *a, **k: None)
    ChannelManager._instance = None  # 防跨文件泄漏：本文件所有用例自带干净单例
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()
    ChannelManager._instance = None


class TestStoreV2Migration:
    def test_v1_flat_migrates_to_default(self, api):
        c, tmp = api
        (tmp / "channel_configs.json").write_text(
            json.dumps({"feishu": {"channel_type": "feishu", "app_id": "old-bot", "enabled": True}}),
            encoding="utf-8",
        )
        rows = c.get("/api/v1/channel-configs").json()
        assert any(r["app_id_masked"].startswith("old-bot") for r in rows), "v1 数据未迁入 default 视图"

    def test_two_agents_independent_configs(self, api):
        c, tmp = api
        r1 = c.post("/api/v1/channel-configs", params={"agent_id": "a1"},
                   json={"channel_type": "feishu", "app_id": "bot-one", "app_secret": "s"})
        r2 = c.post("/api/v1/channel-configs", params={"agent_id": "a2"},
                   json={"channel_type": "feishu", "app_id": "bot-two", "app_secret": "s"})
        assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
        only_a1 = c.get("/api/v1/channel-configs", params={"agent_id": "a1"}).json()
        only_a2 = c.get("/api/v1/channel-configs", params={"agent_id": "a2"}).json()
        assert [x["channel_type"] for x in only_a1] == ["feishu"]
        assert only_a1[0]["app_id_masked"].startswith("bot-one")
        assert only_a2[0]["app_id_masked"].startswith("bot-two")
        # 物理结构 = v2 嵌套
        raw = json.loads((tmp / "channel_configs.json").read_text(encoding="utf-8"))
        assert raw.get("version") == 2
        assert set(raw["agents"]) >= {"a1", "a2"}


class TestIdentityConflict:
    def test_same_bot_across_agents_409(self, api):
        c, _ = api
        r1 = c.post("/api/v1/channel-configs", params={"agent_id": "a1"},
                   json={"channel_type": "feishu", "app_id": "same-bot", "app_secret": "s"})
        assert r1.status_code == 200
        r2 = c.post("/api/v1/channel-configs", params={"agent_id": "a2"},
                   json={"channel_type": "feishu", "app_id": "same-bot", "app_secret": "s"})
        assert r2.status_code == 409, "两 agent 撞同一 bot 身份必须拒（QP conflict 语义）"
        # 同 agent 自身覆盖保存不算冲突
        r3 = c.post("/api/v1/channel-configs", params={"agent_id": "a1"},
                   json={"channel_type": "feishu", "app_id": "same-bot", "app_secret": "s2"})
        assert r3.status_code == 200

    def test_telegram_identity_is_bot_token(self, api):
        c, _ = api
        c.post("/api/v1/channel-configs", params={"agent_id": "a1"},
              json={"channel_type": "telegram", "extra": {"bot_token": "TOK1"}})
        r = c.post("/api/v1/channel-configs", params={"agent_id": "a2"},
                  json={"channel_type": "telegram", "extra": {"bot_token": "TOK1"}})
        assert r.status_code == 409





class TestStartupBootstrap:
    """Phase B：服务启动按持久化配置逐 agent 重建适配器（根治"重启后配置在但全不连接"）。"""

    def test_bootstrap_registers_and_connects_enabled_per_agent(self, tmp_path, monkeypatch):
        import asyncio

        from neurova.api.endpoints import channel_config as cc
        from neurova.channels.manager import get_channel_manager

        class _A:
            def __init__(self):
                self.channel_type = "feishu"
                self.is_connected = False
                self.config = type("C", (), {"enabled": True})()
                self.connects = 0

            async def connect(self):
                self.connects += 1
                self.is_connected = True
                return True  # 真实契约：connect() 返回 bool

            async def disconnect(self):
                pass

            def set_event_callback(self, cb):
                self.cb = cb

        made = []

        def factory(*a, **k):
            inst = _A()
            made.append(inst)
            return inst

        monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cc, "CONFIG_FILE", tmp_path / "channel_configs.json")
        monkeypatch.setattr(cc, "_create_adapter", factory)
        (tmp_path / "channel_configs.json").write_text(
            json.dumps({
                "version": 2,
                "agents": {
                    "a1": {"feishu": {"channel_type": "feishu", "enabled": True, "app_id": "x1"}},
                    "a2": {"feishu": {"channel_type": "feishu", "enabled": False, "app_id": "x2"}},
                },
            }),
            encoding="utf-8",
        )
        ChannelManager._instance = None
        try:
            stats = asyncio.run(cc.bootstrap_channel_adapters())
            mgr = get_channel_manager()
            assert mgr.get_adapter("feishu", agent_id="a1") is not None, "enabled 实例未按 agent 重建"
            assert mgr.get_adapter("feishu", agent_id="a2") is None, "disabled 必须跳过"
            assert stats["connected"] == 1 and made[0].connects == 1
        finally:
            ChannelManager._instance = None


class _FakeAdapter:
    def __init__(self, channel_type):
        self.channel_type = channel_type
        self.is_connected = False
        self.config = type("C", (), {"enabled": True})()
        self._cb = None

    def set_event_callback(self, cb):
        self._cb = cb


class TestManagerDualView:
    @pytest.fixture()
    def manager(self):
        ChannelManager._instance = None
        m = ChannelManager()
        yield m
        ChannelManager._instance = None  # 不恢复他文件可能设过的实例，归零最干净

    def test_agent_registration_does_not_shadow_default_view(self, manager):
        d = _FakeAdapter("feishu")
        a1 = _FakeAdapter("feishu")
        manager.register_adapter(d)  # 默认 agent（兼容签名）
        manager.register_adapter(a1, agent_id="a1")
        assert manager.get_adapter("feishu") is d, "type 键必须仍是 default 视图"
        assert manager.get_adapter("feishu", agent_id="a1") is a1
        assert manager.get_adapter("feishu", agent_id="a2") is None

    def test_inbound_carries_source_agent(self, manager):
        seen = []
        async def handler(message):
            seen.append(message.metadata.get("agent_id"))
            return None

        manager.add_message_handler(handler)
        a1 = _FakeAdapter("feishu")
        manager.register_adapter(a1, agent_id="a1")
        msg = ChannelMessage(
            channel_type="feishu", message_id="m1", sender_id="s1",
            sender_name="n", content="hi", chat_id="c1",
        )
        import asyncio
        # 装配期绑定的事件回调（adapter._cb）携来源实例 → dispatch 后消息带 agent 上下文
        cb = a1._cb
        assert cb is not None, "register_adapter 未给实例绑定事件回调"
        from neurova.channels.base import ChannelEventType
        asyncio.run(cb(ChannelEventType.MESSAGE_RECEIVED, msg))
        assert seen and seen[-1] == "a1", "入站消息未携带来源 agent（路由硬编码 default 的通路缺陷）"
