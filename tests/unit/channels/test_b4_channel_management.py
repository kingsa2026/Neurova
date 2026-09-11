# -*- coding: utf-8 -*-
"""B4-a/b 渠道管理能力面 + 群聊会话隔离测试（QP #7208/#7001 对齐）。

锁定契约：
1. ChannelIngressQueue.clear(channel_type) 只清 pending，返回条数。
2. ChannelManager.restart_channel：disconnect→connect；未注册渠道诚实失败。
3. ChannelManager.clear_channel_queue / conflict_check。
4. resolve_session_scope_id：share_session_in_group=False → chat:sender；
   True/默认 → chat_id（既有行为等价）。"true"/"false" 字符串兼容。
5. 渠道 REST：/{type}/restart、/{type}/clear-queue、/conflicts/check 可达。
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.channels.base import ChannelConfig, ChannelMessage
from neurova.channels.manager import ChannelManager


class _FakeAdapter:
    def __init__(self, channel_type: str, connect_ok: bool = True):
        self.channel_type = channel_type
        self.config = ChannelConfig(channel_type=channel_type)
        self.connect_ok = connect_ok
        self.connected = False
        self.disconnected = 0

    def set_event_callback(self, callback) -> None:
        return None

    async def connect(self) -> bool:
        if not self.connect_ok:
            raise RuntimeError("boom")
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnected += 1

    async def health_check(self):
        return {"connected": self.connected}


class TestIngressClear:
    def test_clear_only_pending(self, tmp_path):
        from neurova.channels.channel_ingress_queue import ChannelIngressQueue

        q = ChannelIngressQueue(db_path=str(tmp_path / "q.db"))
        try:
            from neurova.channels.base import ChannelMessage
            from datetime import datetime

            def msg(mid):
                return ChannelMessage(
                    message_id=mid, channel_type="feishu", chat_id="c1",
                    sender_id="u1", sender_name="u", content="hi",
                    message_type="text", timestamp=datetime.now(),
                )

            q.enqueue(msg("m1"))
            q.enqueue(msg("m2"))
            cleared = q.clear("feishu")
            assert cleared == 2
            assert q.clear("feishu") == 0
        finally:
            q.close()


class TestRestartChannel:
    def test_restart_disconnect_then_connect(self):
        manager = ChannelManager()
        adapter = _FakeAdapter("feishu")
        manager.register_adapter(adapter)
        adapter.connected = True
        result = asyncio.run(manager.restart_channel("feishu"))
        assert result["success"] is True
        assert adapter.connected is True
        assert adapter.disconnected == 1

    def test_restart_unregistered_fails_honest(self):
        manager = ChannelManager()
        result = asyncio.run(manager.restart_channel("nope"))
        assert result["success"] is False
        assert "error" in result

    def test_restart_connect_failure_reported(self):
        manager = ChannelManager()
        adapter = _FakeAdapter("dingtalk", connect_ok=False)
        manager.register_adapter(adapter)
        result = asyncio.run(manager.restart_channel("dingtalk"))
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_conflict_check_detects_shared_identity(self):
        manager = ChannelManager()
        a = _FakeAdapter("feishu")
        a.config.app_id = "shared-app"
        b = _FakeAdapter("dingtalk")
        b.config.app_id = "shared-app"
        c = _FakeAdapter("wecom")
        c.config.app_id = "other"
        manager.register_adapter(a)
        manager.register_adapter(b)
        manager.register_adapter(c)
        result = manager.conflict_check()
        assert len(result["conflicts"]) == 1
        assert set(result["conflicts"][0]["channels"]) == {"feishu", "dingtalk"}


class TestSessionScopeResolution:
    def _message(self, channel="feishu", chat="grp1", sender="u1"):
        from neurova.channels.base import ChannelMessage
        from datetime import datetime

        return ChannelMessage(
            message_id="m1", channel_type=channel, chat_id=chat,
            sender_id=sender, sender_name=sender, content="hi",
            message_type="text", timestamp=datetime.now(),
        )

    def test_default_shares_session(self):
        manager = ChannelManager()
        manager.register_adapter(_FakeAdapter("feishu"))
        assert manager.resolve_session_scope_id(self._message()) == "grp1"

    def test_isolated_uses_sender_suffix(self):
        manager = ChannelManager()
        adapter = _FakeAdapter("feishu")
        adapter.share_session_in_group = False
        manager.register_adapter(adapter)
        assert manager.resolve_session_scope_id(self._message()) == "grp1:u1"

    def test_string_false_coerced(self):
        manager = ChannelManager()
        adapter = _FakeAdapter("feishu")
        adapter.share_session_in_group = "false"
        manager.register_adapter(adapter)
        assert manager.resolve_session_scope_id(self._message()) == "grp1:u1"

    def test_isolated_without_sender_falls_back_to_chat(self):
        manager = ChannelManager()
        adapter = _FakeAdapter("feishu")
        adapter.share_session_in_group = False
        manager.register_adapter(adapter)
        msg = self._message()
        msg.sender_id = ""
        assert manager.resolve_session_scope_id(msg) == "grp1"

    def test_feishu_adapter_reads_metadata_flag(self):
        from neurova.channels.feishu import FeishuAdapter

        cfg = ChannelConfig(channel_type="feishu",
                            extra={"share_session_in_group": "false"})
        assert FeishuAdapter(cfg).share_session_in_group is False
        assert FeishuAdapter(ChannelConfig(channel_type="feishu")).share_session_in_group is True


class TestPluginChannelRegistry:
    """B4-d：插件化自定义渠道（register_channel + config_fields schema）。"""

    def test_register_and_schema(self):
        from neurova.channels.plugin_channels import (
            PluginChannelSpec,
            get_plugin_channel_registry,
            reset_plugin_channel_registry,
        )

        reset_plugin_channel_registry()
        reg = get_plugin_channel_registry()
        reg.register(PluginChannelSpec(
            channel_type="acme-bot",
            name="Acme Bot",
            description="示例插件渠道",
            config_fields=[
                {"key": "webhook_url", "label": "回调地址", "type": "string", "required": True},
                {"key": "use_stream", "label": "流式", "type": "bool", "default": True},
            ],
        ))
        schemas = reg.schemas()
        assert schemas[0]["channel_type"] == "acme-bot"
        assert schemas[0]["config_fields"][0]["key"] == "webhook_url"
        reset_plugin_channel_registry()

    def test_register_rejects_invalid_type(self):
        from neurova.channels.plugin_channels import (
            PluginChannelSpec,
            get_plugin_channel_registry,
            reset_plugin_channel_registry,
        )

        reset_plugin_channel_registry()
        reg = get_plugin_channel_registry()
        with pytest.raises(ValueError):
            reg.register(PluginChannelSpec(channel_type="bad type!", name="x"))
        with pytest.raises(ValueError):
            reg.register(PluginChannelSpec(
                channel_type="ok", name="x",
                config_fields=[{"key": "k", "type": "dict"}],
            ))
        reset_plugin_channel_registry()

    def test_create_adapter_via_registry(self):
        from neurova.channels.plugin_channels import (
            PluginChannelSpec,
            get_plugin_channel_registry,
            reset_plugin_channel_registry,
        )
        from neurova.channels.base import ChannelConfig

        reset_plugin_channel_registry()
        reg = get_plugin_channel_registry()

        def factory(config):
            return {"made_from": config}

        reg.register(PluginChannelSpec(
            channel_type="plug-1", name="P1", factory=factory,
        ))
        cfg = ChannelConfig(channel_type="plug-1")
        assert reg.create_adapter("plug-1", cfg) == {"made_from": cfg}
        assert reg.create_adapter("unknown", cfg) is None
        reset_plugin_channel_registry()

    def test_schemas_endpoint_reachable(self, client_authless=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import channel_config as cc

        app = FastAPI()
        # 路由级鉴权（dependencies=[Depends(get_current_user)]）是正确设计——
        # 单测 override 后专注 schema 契约本身
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "t"}
        app.include_router(cc.router)
        client = TestClient(app)
        resp = client.get("/channel-configs/schemas")
        assert resp.status_code == 200
        assert resp.json()["data"]["schemas"] == []
