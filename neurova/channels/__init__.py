"""
Neurova 渠道集成模块

提供飞书、钉钉、企业微信、语音通话等第三方平台的接入能力。
支持 Stream 模式（WebSocket 长连接）和 Webhook 模式。

使用方式:
    from neurova.channels import ChannelManager, get_channel_manager

    manager = get_channel_manager()
    manager.start()
"""

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelMessage,
    ChannelEventType,
    MessageChannel,
)
from neurova.channels.manager import ChannelManager, get_channel_manager
from neurova.channels.xiaoyi import XiaoYiAdapter, create_xiaoyi_adapter
from neurova.channels.voice import VoiceAdapter, create_voice_adapter
from neurova.session_manager import SessionManager, SessionMessage, SessionRecord, get_session_manager

__all__ = [
    "ChannelAdapter",
    "ChannelConfig",
    "ChannelMessage",
    "ChannelEventType",
    "MessageChannel",
    "ChannelManager",
    "get_channel_manager",
    "XiaoYiAdapter",
    "create_xiaoyi_adapter",
    "VoiceAdapter",
    "create_voice_adapter",
    "SessionManager",
    "SessionMessage",
    "SessionRecord",
    "get_session_manager",
]
