"""
test_channels_models.py — P4 测试：渠道数据模型

验证从 channels/__init__.py 提取到 channels/models.py 的 6 个数据类
"""

from __future__ import annotations

import pytest
from datetime import datetime

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
        assert MessageChannel.UNKNOWN.value == "unknown"

    def test_total_channel_count(self):
        """验证渠道总数（18 个）"""
        assert len(MessageChannel) == 18


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

    def test_has_ai_types(self):
        """验证 AI 生成类型存在"""
        assert ContentType.AI_IMAGE.value == "ai_image"
        assert ContentType.AI_VIDEO.value == "ai_video"


# ============================================================================
# 测试：UnifiedMessage
# ============================================================================

class TestUnifiedMessage:
    """UnifiedMessage 统一消息测试"""

    def test_create_basic_message(self):
        """验证创建基本消息"""
        now = datetime.now()
        msg = UnifiedMessage(
            message_id="msg-001",
            channel=MessageChannel.TELEGRAM,
            chat_id="chat-123",
            user_id="user-456",
            agent_id="agent-789",
            content="Hello, world!",
            content_type=ContentType.TEXT,
            timestamp=now,
        )
        assert msg.message_id == "msg-001"
        assert msg.channel == MessageChannel.TELEGRAM
        assert msg.content == "Hello, world!"
        assert msg.timestamp == now

    def test_default_values(self):
        """验证默认值"""
        now = datetime.now()
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", agent_id="a1", content="hi",
            content_type=ContentType.TEXT, timestamp=now,
        )
        assert msg.global_user_id == ""
        assert msg.session_id == ""
        assert msg.raw_message is None
        assert msg.metadata == {}
        assert msg.attachments == []
        assert msg.card_data == {}

    def test_timestamp_auto_now(self):
        """验证 timestamp 为 None 时自动设置为当前时间"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", agent_id="a1", content="hi",
            content_type=ContentType.TEXT, timestamp=None,
        )
        assert msg.timestamp is not None
        assert isinstance(msg.timestamp, datetime)

    def test_add_attachment(self):
        """验证添加附件"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.TELEGRAM, chat_id="c1",
            user_id="u1", agent_id="a1", content="hi",
            content_type=ContentType.TEXT, timestamp=datetime.now(),
        )
        msg.add_attachment("image", url="http://example.com/img.png", name="photo.png", size=12345)
        assert msg.has_attachments() is True
        assert len(msg.attachments) == 1
        assert msg.attachments[0]["type"] == "image"
        assert msg.attachments[0]["url"] == "http://example.com/img.png"

    def test_get_attachments_by_type(self):
        """验证按类型获取附件"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", agent_id="a1", content="hi",
            content_type=ContentType.TEXT, timestamp=datetime.now(),
        )
        msg.add_attachment("image", url="img1.png")
        msg.add_attachment("file", url="doc1.pdf")
        msg.add_attachment("image", url="img2.png")

        images = msg.get_attachments_by_type("image")
        assert len(images) == 2
        files = msg.get_attachments_by_type("file")
        assert len(files) == 1

    def test_has_attachments_empty(self):
        """验证空附件"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", agent_id="a1", content="hi",
            content_type=ContentType.TEXT, timestamp=datetime.now(),
        )
        assert msg.has_attachments() is False

    def test_card_data_default(self):
        """验证卡片数据默认是空字典"""
        msg = UnifiedMessage(
            message_id="m1", channel=MessageChannel.WEB, chat_id="c1",
            user_id="u1", agent_id="a1", content="hi",
            content_type=ContentType.CARD, timestamp=datetime.now(),
            card_data={"title": "Test Card"},
        )
        assert msg.card_data["title"] == "Test Card"


# ============================================================================
# 测试：UserIdentity
# ============================================================================

class TestUserIdentity:
    """UserIdentity 用户身份测试"""

    def test_create_identity(self):
        """验证创建基本身份"""
        identity = UserIdentity(global_user_id="g-user-001")
        assert identity.global_user_id == "g-user-001"
        assert identity.display_name == ""
        assert identity.feishu_open_id == ""

    def test_auto_timestamps(self):
        """验证时间戳自动设置"""
        identity = UserIdentity(global_user_id="u1")
        assert identity.created_at is not None
        assert identity.updated_at is not None
        assert isinstance(identity.created_at, datetime)

    def test_channel_specific_fields(self):
        """验证渠道特定字段"""
        identity = UserIdentity(
            global_user_id="u1",
            telegram_user_id="12345",
            telegram_username="testuser",
            feishu_open_id="ou_abc",
            dingtalk_user_id="dt_xyz",
        )
        assert identity.telegram_user_id == "12345"
        assert identity.telegram_username == "testuser"
        assert identity.feishu_open_id == "ou_abc"
        assert identity.dingtalk_user_id == "dt_xyz"

    def test_display_name(self):
        """验证显示名称"""
        identity = UserIdentity(global_user_id="u1", display_name="Test User")
        assert identity.display_name == "Test User"


# ============================================================================
# 测试：SessionContext
# ============================================================================

class TestSessionContext:
    """SessionContext 会话上下文测试"""

    def test_create_session(self):
        """验证创建基本会话"""
        session = SessionContext(
            session_id="s-001",
            agent_id="a-001",
            global_user_id="u-001",
            channel=MessageChannel.WEB,
            active_channels=[MessageChannel.WEB],
        )
        assert session.session_id == "s-001"
        assert session.agent_id == "a-001"
        assert session.global_user_id == "u-001"
        assert session.channel == MessageChannel.WEB

    def test_auto_timestamps(self):
        """验证时间戳自动设置"""
        session = SessionContext(
            session_id="s1", agent_id="a1", global_user_id="u1",
            channel=MessageChannel.WEB, active_channels=[MessageChannel.WEB],
        )
        assert session.created_at is not None
        assert session.updated_at is not None
        assert session.last_active is not None

    def test_default_lists(self):
        """验证默认列表"""
        session = SessionContext(
            session_id="s1", agent_id="a1", global_user_id="u1",
            channel=MessageChannel.WEB, active_channels=[],
        )
        assert session.conversation_history == []
        assert session.memory_keys == []

    def test_multiple_active_channels(self):
        """验证多个活跃渠道"""
        session = SessionContext(
            session_id="s1", agent_id="a1", global_user_id="u1",
            channel=MessageChannel.WEB,
            active_channels=[MessageChannel.WEB, MessageChannel.TELEGRAM],
        )
        assert len(session.active_channels) == 2
        assert MessageChannel.TELEGRAM in session.active_channels


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
        assert config.priority == 0

    def test_default_health_status(self):
        """验证默认健康状态"""
        config = ChannelConfig(channel=MessageChannel.WEB)
        assert config.health_status == "unknown"
        assert config.consecutive_failures == 0
        assert config.consecutive_successes == 0

    def test_feishu_fields(self):
        """验证飞书配置字段"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            feishu_app_id="app-123",
            feishu_app_secret="secret-456",
        )
        assert config.feishu_app_id == "app-123"
        assert config.feishu_app_secret == "secret-456"

    def test_telegram_fields(self):
        """验证 Telegram 配置字段"""
        config = ChannelConfig(
            channel=MessageChannel.TELEGRAM,
            telegram_bot_token="bot-token-123",
        )
        assert config.telegram_bot_token == "bot-token-123"

    def test_statistics_defaults(self):
        """验证统计默认值"""
        config = ChannelConfig(channel=MessageChannel.WEB)
        assert config.total_requests == 0
        assert config.total_errors == 0
        assert config.last_used is None


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

    def test_import_channel_adapter(self):
        """验证 ChannelAdapter 可从包导入"""
        from neurova.channels import ChannelAdapter
        from neurova.channels.base_adapter import ChannelAdapter as CA2
        assert ChannelAdapter is CA2
