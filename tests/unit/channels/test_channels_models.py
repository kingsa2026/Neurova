"""
test_channels_models.py — 渠道数据模型测试

验证 channels/models.py 的数据类（MessageChannel, ContentType,
UnifiedMessage, UserIdentity, SessionContext, ChannelConfig）。

注意：断言以生产契约为准——
- 时间戳字段为 float（Unix 秒），__post_init__ 自动补当前时间
- 可选集合字段默认 None（不自动初始化为空容器）
- BUG AUDIT C-01: UnifiedMessage.global_user_id 字段必须存在
"""

from __future__ import annotations

import pytest

from neurova.channels.models import (
    MessageChannel,
    ContentType,
    UnifiedMessage,
    UserIdentity,
    SessionContext,
    ChannelConfig,
)


# ============================================================================
# 测试：MessageChannel 枚举
# ============================================================================

class TestMessageChannel:
    """MessageChannel 枚举测试"""

    def test_has_required_channels(self):
        """验证关键渠道类型存在"""
        assert MessageChannel.FEISHU.value == "feishu"
        assert MessageChannel.TELEGRAM.value == "telegram"
        assert MessageChannel.WEB.value == "web"
        assert MessageChannel.API.value == "api"
        # 第三方平台渠道（C-01 修复涉及的 7 个适配器渠道必须可用）
        for name in ("WECHAT", "DINGTALK", "WECOM", "SIP", "QQBOT", "QQ", "MQTT", "DISCORD", "WEBSOCKET"):
            assert hasattr(MessageChannel, name), f"缺少渠道枚举: {name}"

    def test_members_are_unique(self):
        """验证渠道枚举值唯一"""
        values = [m.value for m in MessageChannel]
        assert len(values) == len(set(values))


# ============================================================================
# 测试：ContentType 枚举
# ============================================================================

class TestContentType:
    """ContentType 枚举测试"""

    def test_has_basic_types(self):
        """验证基本类型存在"""
        assert ContentType.TEXT.value == "text"
        assert ContentType.IMAGE.value == "image"
        assert ContentType.FILE.value == "file"
        assert ContentType.VOICE.value == "voice"
        assert ContentType.CARD.value == "card"


# ============================================================================
# 测试：UnifiedMessage
# ============================================================================

class TestUnifiedMessage:
    """UnifiedMessage 统一消息测试"""

    def test_create_basic_message(self):
        """验证创建基本消息"""
        msg = UnifiedMessage(
            message_id="msg-001",
            channel=MessageChannel.TELEGRAM,
            chat_id="chat-123",
            user_id="user-456",
            agent_id="agent-789",
            content="Hello, world!",
            content_type=ContentType.TEXT,
        )
        assert msg.message_id == "msg-001"
        assert msg.channel == MessageChannel.TELEGRAM
        assert msg.content == "Hello, world!"
        assert msg.chat_id == "chat-123"

    def test_global_user_id_field_exists(self):
        """BUG AUDIT C-01: global_user_id 字段必须存在且可赋值。

        discord/websocket/sip/qq/qqbot/mqtt 7 个适配器构造消息时都传该字段。
        """
        msg = UnifiedMessage(
            message_id="m1",
            channel=MessageChannel.DISCORD,
            content_type=ContentType.TEXT,
            content="hi",
            user_id="u1",
            global_user_id="discord:12345",
        )
        assert msg.global_user_id == "discord:12345"

    def test_default_values(self):
        """验证可选字段默认 None"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", content="hi",
            content_type=ContentType.TEXT,
        )
        assert msg.global_user_id is None
        assert msg.session_id is None
        assert msg.raw_message is None
        assert msg.metadata is None
        assert msg.attachments is None
        assert msg.card_data is None

    def test_timestamp_auto_now(self):
        """验证 timestamp 为 None 时自动设置为当前 Unix 时间（float）"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", content="hi",
            content_type=ContentType.TEXT, timestamp=None,
        )
        assert msg.timestamp is not None
        assert isinstance(msg.timestamp, float)

    def test_explicit_timestamp_preserved(self):
        """验证显式 timestamp 不被覆盖"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB,
            user_id="u1", content="hi",
            content_type=ContentType.TEXT, timestamp=1700000000.0,
        )
        assert msg.timestamp == 1700000000.0

    def test_to_dict_from_dict_roundtrip(self):
        """验证序列化往返：enum 转字符串值，可完整还原"""
        msg = UnifiedMessage(
            message_id="m2",
            channel=MessageChannel.FEISHU,
            content_type=ContentType.CARD,
            content="card",
            user_id="u2",
            chat_id="c2",
            card_data={"title": "T"},
            metadata={"k": "v"},
            global_user_id="feishu:ou_1",
        )
        d = msg.to_dict()
        assert d["channel"] == "feishu"
        assert d["content_type"] == "card"

        restored = UnifiedMessage.from_dict(d)
        assert restored == msg

    def test_attachments_list_payload(self):
        """验证附件以列表载荷传递（附件管理由各适配器/metadata 承担）"""
        msg = UnifiedMessage(
            message_id="m3", channel=MessageChannel.WEB,
            user_id="u1", content="file",
            content_type=ContentType.FILE,
            attachments=[{"type": "image", "url": "img.png", "name": "img.png"}],
            file_url="img.png",
            file_name="img.png",
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0]["type"] == "image"
        assert msg.file_name == "img.png"


# ============================================================================
# 测试：UserIdentity
# ============================================================================

class TestUserIdentity:
    """UserIdentity 用户身份测试"""

    def test_create_identity(self):
        """验证创建基本身份（user_id + channel + channel_user_id 三元组）"""
        identity = UserIdentity(
            user_id="u-001",
            channel=MessageChannel.FEISHU,
            channel_user_id="ou_abc",
        )
        assert identity.user_id == "u-001"
        assert identity.channel == MessageChannel.FEISHU
        assert identity.channel_user_id == "ou_abc"
        assert identity.display_name is None

    def test_auto_timestamp(self):
        """验证 created_at 自动设置为当前 Unix 时间（float）"""
        identity = UserIdentity(
            user_id="u1", channel=MessageChannel.WEB, channel_user_id="c1",
        )
        assert identity.created_at is not None
        assert isinstance(identity.created_at, float)

    def test_display_name(self):
        """验证显示名称"""
        identity = UserIdentity(
            user_id="u1", channel=MessageChannel.TELEGRAM,
            channel_user_id="12345", display_name="Test User",
        )
        assert identity.display_name == "Test User"

    def test_to_dict_from_dict_roundtrip(self):
        """验证序列化往返"""
        identity = UserIdentity(
            user_id="u1", channel=MessageChannel.WEB,
            channel_user_id="c1", display_name="Tester",
        )
        d = identity.to_dict()
        assert d["channel"] == "web"
        assert UserIdentity.from_dict(d) == identity


# ============================================================================
# 测试：SessionContext
# ============================================================================

class TestSessionContext:
    """SessionContext 会话上下文测试"""

    def test_create_session(self):
        """验证创建基本会话"""
        session = SessionContext(
            session_id="s-001",
            user_id="u-001",
            channel=MessageChannel.WEB,
            agent_id="a-001",
        )
        assert session.session_id == "s-001"
        assert session.user_id == "u-001"
        assert session.agent_id == "a-001"
        assert session.message_count == 0

    def test_auto_timestamps(self):
        """验证 started_at/last_active_at 自动设置（float）"""
        session = SessionContext(
            session_id="s1", user_id="u1", channel=MessageChannel.WEB,
        )
        assert session.started_at is not None
        assert session.last_active_at is not None

    def test_touch_updates_activity(self):
        """验证 touch() 更新活跃时间并累加消息计数"""
        import time as _time

        session = SessionContext(
            session_id="s1", user_id="u1", channel=MessageChannel.WEB,
            message_count=1,
        )
        _time.sleep(0.01)
        session.touch()
        assert session.last_active_at >= session.started_at
        assert session.message_count == 2

    def test_to_dict_from_dict_roundtrip(self):
        """验证序列化往返"""
        session = SessionContext(
            session_id="s1", user_id="u1", channel=MessageChannel.WEB,
            context_data={"page": "home"},
        )
        d = session.to_dict()
        assert d["channel"] == "web"
        assert SessionContext.from_dict(d) == session


# ============================================================================
# 测试：ChannelConfig
# ============================================================================

class TestChannelConfig:
    """ChannelConfig 渠道配置测试"""

    def test_create_config(self):
        """验证创建基本配置"""
        config = ChannelConfig(channel=MessageChannel.TELEGRAM)
        assert config.channel == MessageChannel.TELEGRAM
        assert config.enabled is True
        assert config.max_message_length == 4096
        assert config.rate_limit == 60

    def test_default_content_types(self):
        """验证默认允许的内容类型"""
        config = ChannelConfig(channel=MessageChannel.WEB)
        assert config.allowed_content_types == [ContentType.TEXT]

    def test_credentials_fields(self):
        """验证凭证字段（app_id/app_secret/webhook_url）"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            app_id="app-123",
            app_secret="secret-456",
            webhook_url="https://example.com/hook",
        )
        assert config.app_id == "app-123"
        assert config.app_secret == "secret-456"
        assert config.webhook_url == "https://example.com/hook"

    def test_welcome_message_default(self):
        """验证欢迎语默认值"""
        config = ChannelConfig(channel=MessageChannel.WEB)
        assert "Neurova" in config.welcome_message
        assert config.bot_name == "Neurova"

    def test_to_dict_from_dict_roundtrip(self):
        """验证序列化往返（enum 与 allowed_content_types 需转换）"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            allowed_content_types=[ContentType.TEXT, ContentType.IMAGE],
            metadata={"ver": 1},
        )
        d = config.to_dict()
        assert d["channel"] == "feishu"
        assert d["allowed_content_types"] == ["text", "image"]
        assert ChannelConfig.from_dict(d) == config


# ============================================================================
# 测试：跨模块导入兼容性
# ============================================================================

class TestBackwardCompatibility:
    """验证从 channels 包导入仍然可用（向后兼容）"""

    def test_import_from_channels_package(self):
        """验证 from neurova.channels import MessageChannel 仍然有效"""
        from neurova.channels import (
            MessageChannel as MC,
            UnifiedMessage as UM,
            UserIdentity as UI,
            ChannelConfig as CC,
        )
        assert MC.FEISHU.value == "feishu"
        assert UM is not None
        assert UI is not None
        assert CC is not None
