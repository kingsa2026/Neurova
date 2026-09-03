"""
渠道集成模块测试

遵循 TDD 原则:
- 测试公共接口的行为，不测试实现细节
- 每个测试描述一个可观察的行为
- 使用垂直切片方式逐步构建
"""

import asyncio
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.manager import ChannelManager, get_channel_manager
from neurova.channels.feishu import FeishuAdapter, create_feishu_adapter
from neurova.channels.dingtalk import DingTalkAdapter, create_dingtalk_adapter
from neurova.channels.wecom import WeComAdapter, create_wecom_adapter


# ============================================================
# 基础数据模型测试
# ============================================================


class TestChannelConfig:
    """ChannelConfig 数据模型测试"""

    def test_config_creation(self):
        config = ChannelConfig(channel_type="feishu", app_id="test123")
        assert config.channel_type == "feishu"
        assert config.app_id == "test123"
        assert config.enabled is True
        assert config.use_stream is True

    def test_config_to_dict_masks_secret(self):
        config = ChannelConfig(
            channel_type="feishu",
            app_id="test123",
            app_secret="super_secret_key",
        )
        d = config.to_dict()
        assert d["app_secret"] == "***"
        assert d["app_id"] == "test123"

    def test_config_empty_secret_masks(self):
        config = ChannelConfig(channel_type="feishu", app_secret="")
        d = config.to_dict()
        assert d["app_secret"] == ""


class TestChannelMessage:
    """ChannelMessage 数据模型测试"""

    def test_message_creation(self):
        msg = ChannelMessage(
            channel_type="feishu",
            message_id="msg_001",
            sender_id="user_001",
            sender_name="张三",
            content="你好",
        )
        assert msg.channel_type == "feishu"
        assert msg.message_id == "msg_001"
        assert msg.content == "你好"
        assert msg.chat_type == "p2p"

    def test_message_defaults(self):
        msg = ChannelMessage(
            channel_type="dingtalk",
            message_id="m1",
            sender_id="u1",
            sender_name="test",
            content="hello",
        )
        assert msg.message_type == "text"
        assert msg.chat_type == "p2p"
        assert isinstance(msg.timestamp, datetime)
        assert msg.raw_event == {}
        assert msg.metadata == {}


# ============================================================
# ChannelAdapter 基类测试
# ============================================================


class ConcreteAdapter(ChannelAdapter):
    """测试用的具体适配器"""

    def __init__(self, config):
        super().__init__(config)
        self.connect_called = False
        self.disconnect_called = False
        self.messages_sent = []

    async def connect(self) -> bool:
        self.connect_called = True
        self._connected = True
        return True

    async def disconnect(self):
        self.disconnect_called = True
        self._connected = False

    async def send_message(self, chat_id, content, message_type="text", **kwargs):
        self.messages_sent.append({
            "chat_id": chat_id,
            "content": content,
            "message_type": message_type,
        })
        return "msg_sent_001"


class TestChannelAdapter:
    """ChannelAdapter 基类行为测试"""

    def test_channel_type_property(self):
        config = ChannelConfig(channel_type="test_channel")
        adapter = ConcreteAdapter(config)
        assert adapter.channel_type == "test_channel"

    def test_initial_not_connected(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        assert adapter.is_connected is False

    def test_set_event_callback(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        callback = AsyncMock()
        adapter.set_event_callback(callback)
        assert adapter._event_callback is callback

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected is True
        assert adapter.connect_called is True

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        await adapter.connect()
        await adapter.disconnect()
        assert adapter.is_connected is False
        assert adapter.disconnect_called is True

    @pytest.mark.asyncio
    async def test_send_message_returns_id(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        msg_id = await adapter.send_message("chat_001", "hello")
        assert msg_id == "msg_sent_001"
        assert len(adapter.messages_sent) == 1
        assert adapter.messages_sent[0]["chat_id"] == "chat_001"

    @pytest.mark.asyncio
    async def test_health_check(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        health = await adapter.health_check()
        assert health["channel_type"] == "test"
        assert health["connected"] is False

    @pytest.mark.asyncio
    async def test_emit_event(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        callback = AsyncMock()
        adapter.set_event_callback(callback)

        msg = ChannelMessage(
            channel_type="test",
            message_id="m1",
            sender_id="u1",
            sender_name="test",
            content="hello",
        )
        await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, msg)
        callback.assert_called_once_with(ChannelEventType.MESSAGE_RECEIVED, msg)

    @pytest.mark.asyncio
    async def test_emit_event_handles_error(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        callback = AsyncMock(side_effect=RuntimeError("boom"))
        adapter.set_event_callback(callback)

        msg = ChannelMessage(
            channel_type="test",
            message_id="m1",
            sender_id="u1",
            sender_name="test",
            content="hello",
        )
        # 不应该抛出异常
        await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, msg)

    def test_make_message(self):
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        msg = adapter._make_message(
            message_id="m1",
            sender_id="u1",
            sender_name="张三",
            content="你好",
            chat_id="c1",
            chat_type="group",
        )
        assert msg.channel_type == "test"
        assert msg.message_id == "m1"
        assert msg.chat_type == "group"


# ============================================================
# ChannelManager 测试
# ============================================================


class TestChannelManager:
    """ChannelManager 行为测试"""

    def setup_method(self):
        # 重置单例以隔离测试
        ChannelManager._instance = None

    def teardown_method(self):
        ChannelManager._instance = None

    def test_singleton(self):
        m1 = get_channel_manager()
        m2 = get_channel_manager()
        assert m1 is m2

    def test_register_adapter(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="feishu")
        adapter = FeishuAdapter(config)
        manager.register_adapter(adapter)
        assert manager.get_adapter("feishu") is adapter

    def test_unregister_adapter(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="feishu")
        adapter = FeishuAdapter(config)
        manager.register_adapter(adapter)
        assert manager.unregister_adapter("feishu") is True
        assert manager.get_adapter("feishu") is None

    def test_unregister_nonexistent(self):
        manager = ChannelManager()
        assert manager.unregister_adapter("nonexistent") is False

    def test_list_adapters(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="feishu")
        adapter = FeishuAdapter(config)
        manager.register_adapter(adapter)

        adapters = manager.list_adapters()
        assert "feishu" in adapters
        assert adapters["feishu"]["connected"] is False

    @pytest.mark.asyncio
    async def test_message_handler_called(self):
        manager = ChannelManager()
        handler = AsyncMock(return_value="收到!")
        manager.set_message_handler(handler)

        msg = ChannelMessage(
            channel_type="feishu",
            message_id="m1",
            sender_id="u1",
            sender_name="test",
            content="你好",
            chat_id="c1",
        )

        await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, msg)
        handler.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_message_handler_reply_sent(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        manager.register_adapter(adapter)

        handler = AsyncMock(return_value="回复内容")
        manager.set_message_handler(handler)

        msg = ChannelMessage(
            channel_type="test",
            message_id="m1",
            sender_id="u1",
            sender_name="test",
            content="你好",
            chat_id="c1",
        )

        await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, msg)
        assert len(adapter.messages_sent) == 1
        assert adapter.messages_sent[0]["content"] == "回复内容"

    @pytest.mark.asyncio
    async def test_message_handler_error_sends_fallback(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        manager.register_adapter(adapter)

        handler = AsyncMock(side_effect=RuntimeError("处理失败"))
        manager.set_message_handler(handler)

        msg = ChannelMessage(
            channel_type="test",
            message_id="m1",
            sender_id="u1",
            sender_name="test",
            content="你好",
            chat_id="c1",
        )

        await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, msg)
        # 应该发送错误提示
        assert len(adapter.messages_sent) == 1
        assert "错误" in adapter.messages_sent[0]["content"]

    @pytest.mark.asyncio
    async def test_health_check(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteAdapter(config)
        manager.register_adapter(adapter)

        health = await manager.health_check()
        assert health["running"] is False
        assert "test" in health["adapters"]

    @pytest.mark.asyncio
    async def test_start_stop(self):
        manager = ChannelManager()
        config = ChannelConfig(channel_type="test", enabled=True)
        adapter = ConcreteAdapter(config)
        manager.register_adapter(adapter)

        await manager.start()
        assert adapter.is_connected is True

        await manager.stop()
        assert adapter.is_connected is False


# ============================================================
# 飞书适配器测试
# ============================================================


class TestFeishuAdapter:
    """飞书适配器行为测试"""

    def test_create_adapter(self):
        adapter = create_feishu_adapter(
            app_id="cli_test123",
            app_secret="secret123",
            use_stream=True,
        )
        assert adapter.channel_type == "feishu"
        assert adapter.config.app_id == "cli_test123"
        assert adapter.config.use_stream is True

    @pytest.mark.asyncio
    async def test_webhook_mode_connects(self):
        adapter = create_feishu_adapter(
            app_id="cli_test123",
            app_secret="secret123",
            use_stream=False,
        )
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    @pytest.mark.asyncio
    async def test_health_check_includes_app_id(self):
        adapter = create_feishu_adapter(
            app_id="cli_test123",
            app_secret="secret123",
        )
        health = await adapter.health_check()
        assert health["channel_type"] == "feishu"
        assert "cli_test" in health["app_id"]

    def test_verify_url_challenge(self):
        result = FeishuAdapter.verify_url_challenge("test_challenge", "token")
        assert result == {"challenge": "test_challenge"}

    @pytest.mark.asyncio
    async def test_disconnect(self):
        adapter = create_feishu_adapter(
            app_id="cli_test123",
            app_secret="secret123",
        )
        await adapter.connect()
        await adapter.disconnect()
        assert adapter.is_connected is False


# ============================================================
# 钉钉适配器测试
# ============================================================


class TestDingTalkAdapter:
    """钉钉适配器行为测试"""

    def test_create_adapter(self):
        adapter = create_dingtalk_adapter(
            app_id="ding_test123",
            app_secret="secret123",
            use_stream=True,
        )
        assert adapter.channel_type == "dingtalk"
        assert adapter.config.app_id == "ding_test123"

    @pytest.mark.asyncio
    async def test_webhook_mode_connects(self):
        adapter = create_dingtalk_adapter(
            app_id="ding_test123",
            app_secret="secret123",
            use_stream=False,
        )
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    @pytest.mark.asyncio
    async def test_health_check(self):
        adapter = create_dingtalk_adapter(
            app_id="ding_test123",
            app_secret="secret123",
        )
        health = await adapter.health_check()
        assert health["channel_type"] == "dingtalk"
        assert "stream_mode" in health


# ============================================================
# 企业微信适配器测试
# ============================================================


class TestWeComAdapter:
    """企业微信适配器行为测试"""

    def test_create_adapter(self):
        adapter = create_wecom_adapter(
            corpid="ww_test123",
            app_secret="secret123",
            agentid="1000001",
            use_stream=True,
        )
        assert adapter.channel_type == "wecom"
        assert adapter.config.app_id == "ww_test123"

    @pytest.mark.asyncio
    async def test_webhook_mode_connects(self):
        adapter = create_wecom_adapter(
            corpid="ww_test123",
            app_secret="secret123",
            use_stream=False,
        )
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_verify_url_without_token(self):
        adapter = create_wecom_adapter(
            corpid="ww_test123",
            app_secret="secret123",
        )
        # 无 token 时直接返回 echostr
        result = adapter.verify_url("", "", "", "echo_str")
        assert result == "echo_str"

    def test_verify_url_with_correct_signature(self):
        from neurova.channels.wecom import _wecom_callback_signature

        adapter = create_wecom_adapter(
            corpid="ww_test123",
            app_secret="secret123",
            callback_token="test_token",
        )
        # 官方规范（文档 90968）: 签名含第 4 元加密 echostr
        timestamp = "1234567890"
        nonce = "nonce123"
        echostr = "echo_str"
        signature = _wecom_callback_signature("test_token", timestamp, nonce, echostr)
        result = adapter.verify_url(signature, timestamp, nonce, echostr)
        assert result == echostr

    def test_build_reply_xml(self):
        adapter = create_wecom_adapter(
            corpid="ww_test123",
            app_secret="secret123",
        )
        xml = adapter._build_reply_xml("user1", "agent1", "你好")
        assert "user1" in xml
        assert "agent1" in xml
        assert "你好" in xml
        assert "<xml>" in xml

    @pytest.mark.asyncio
    async def test_health_check(self):
        adapter = create_wecom_adapter(
            corpid="ww_test123",
            app_secret="secret123",
        )
        health = await adapter.health_check()
        assert health["channel_type"] == "wecom"
        assert "corpid" in health


# ============================================================
# 集成测试: 多渠道协作
# ============================================================


class TestMultiChannelIntegration:
    """多渠道集成测试"""

    def setup_method(self):
        ChannelManager._instance = None

    def teardown_method(self):
        ChannelManager._instance = None

    @pytest.mark.asyncio
    async def test_multiple_adapters_register(self):
        manager = ChannelManager()

        feishu = create_feishu_adapter("app1", "sec1")
        dingtalk = create_dingtalk_adapter("app2", "sec2")
        wecom = create_wecom_adapter("corp1", "sec3")

        manager.register_adapter(feishu)
        manager.register_adapter(dingtalk)
        manager.register_adapter(wecom)

        adapters = manager.list_adapters()
        assert len(adapters) == 3
        assert "feishu" in adapters
        assert "dingtalk" in adapters
        assert "wecom" in adapters

    @pytest.mark.asyncio
    async def test_start_all_webhook_adapters(self):
        manager = ChannelManager()

        feishu = create_feishu_adapter("app1", "sec1", use_stream=False)
        dingtalk = create_dingtalk_adapter("app2", "sec2", use_stream=False)
        wecom = create_wecom_adapter("corp1", "sec3", use_stream=False)

        manager.register_adapter(feishu)
        manager.register_adapter(dingtalk)
        manager.register_adapter(wecom)

        await manager.start()

        assert feishu.is_connected
        assert dingtalk.is_connected
        assert wecom.is_connected

        await manager.stop()

        assert not feishu.is_connected
        assert not dingtalk.is_connected
        assert not wecom.is_connected
