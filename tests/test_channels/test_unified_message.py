"""
统一消息模型测试

测试目标：neurova/channels/__init__.py 中的 UnifiedMessage, MessageChannel, ContentType
"""

from datetime import datetime
import pytest
from neurova.channels import UnifiedMessage, MessageChannel, ContentType


class TestMessageChannel:
    """消息渠道枚举"""

    def test_major_channels(self):
        assert MessageChannel.WECHAT.value == "wechat"
        assert MessageChannel.FEISHU.value == "feishu"
        assert MessageChannel.TELEGRAM.value == "telegram"
        assert MessageChannel.DINGTALK.value == "dingtalk"
        assert MessageChannel.API.value == "api"

    def test_other_channels(self):
        assert MessageChannel.QQ.value == "qq"
        assert MessageChannel.QCLAW.value == "qclaw"
        assert MessageChannel.WEB.value == "web"
        assert MessageChannel.CLI.value == "cli"

    def test_from_string(self):
        assert MessageChannel("wechat") == MessageChannel.WECHAT
        assert MessageChannel("feishu") == MessageChannel.FEISHU


class TestContentType:
    """内容类型枚举"""

    def test_values(self):
        assert ContentType.TEXT.value == "text"
        assert ContentType.IMAGE.value == "image"
        assert ContentType.VOICE.value == "voice"
        assert ContentType.VIDEO.value == "video"
        assert ContentType.FILE.value == "file"

    def test_advanced_types(self):
        assert ContentType.CARD.value == "card"
        assert ContentType.SYSTEM.value == "system"
        assert ContentType.AUDIO.value == "audio"

    def test_no_ai_image_type(self):
        """使用 AUDIO 代替 AI_IMAGE"""
        assert ContentType.AUDIO is not None
        assert not hasattr(ContentType, "AI_IMAGE")


def _make_msg(
    channel=MessageChannel.WECHAT,
    chat_id="chat_001",
    user_id="user_001",
    agent_id="agent_001",
    content="hello",
    content_type=ContentType.TEXT,
    timestamp=None,
    **kwargs,
):
    """辅助函数：创建 UnifiedMessage 实例（自动填充必需字段）"""
    return UnifiedMessage(
        message_id="",
        channel=channel,
        chat_id=chat_id,
        user_id=user_id,
        agent_id=agent_id,
        content=content,
        content_type=content_type,
        timestamp=timestamp or datetime.now(),
        **kwargs,
    )


class TestUnifiedMessage:
    """统一消息"""

    def test_required_fields(self):
        msg = _make_msg(content="你好")
        assert msg.channel == MessageChannel.WECHAT
        assert msg.chat_id == "chat_001"
        assert msg.user_id == "user_001"
        assert msg.agent_id == "agent_001"
        assert msg.content == "你好"
        assert msg.content_type == ContentType.TEXT

    def test_custom_content_type(self):
        msg = _make_msg(
            channel=MessageChannel.FEISHU,
            content="![image](url)",
            content_type=ContentType.IMAGE,
        )
        assert msg.content_type == ContentType.IMAGE

    def test_session_id(self):
        msg = _make_msg()
        msg.session_id = "sess_001"
        assert msg.session_id == "sess_001"

    def test_with_attachments(self):
        msg = _make_msg(content="看这个文件")
        msg.add_attachment("file", url="https://example.com/doc.pdf", name="doc.pdf")
        assert msg.has_attachments() is True
        attachments = msg.get_attachments_by_type("file")
        assert len(attachments) == 1
        assert attachments[0]["name"] == "doc.pdf"

    def test_multiple_attachments(self):
        msg = _make_msg(content="多附件")
        msg.add_attachment("image", url="a.jpg")
        msg.add_attachment("image", url="b.jpg")
        msg.add_attachment("file", url="c.pdf")
        assert msg.has_attachments() is True
        assert len(msg.get_attachments_by_type("image")) == 2
        assert len(msg.get_attachments_by_type("file")) == 1
        assert len(msg.attachments) == 3

    def test_no_attachments(self):
        msg = _make_msg()
        assert msg.has_attachments() is False
        assert msg.get_attachments_by_type("image") == []

    def test_global_user_id(self):
        msg = _make_msg()
        msg.global_user_id = "global_u1"
        assert msg.global_user_id == "global_u1"

    def test_metadata(self):
        msg = _make_msg(metadata={"source_ip": "192.168.1.1"})
        assert msg.metadata["source_ip"] == "192.168.1.1"

    def test_file_fields(self):
        msg = _make_msg(
            file_url="https://example.com/file.pdf",
            file_name="doc.pdf",
            file_size=1024,
        )
        assert msg.file_url == "https://example.com/file.pdf"
        assert msg.file_name == "doc.pdf"
        assert msg.file_size == 1024
