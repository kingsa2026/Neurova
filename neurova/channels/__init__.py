"""
Neurova 渠道集成模块

提供飞书、钉钉、企业微信、语音通话等第三方平台的接入能力。
支持 Stream 模式（WebSocket 长连接）和 Webhook 模式。

使用方式:
    from neurova.channels import ChannelManager, get_channel_manager

    manager = get_channel_manager()
    manager.start()
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.channels.base import (
        ChannelAdapter,
        ChannelConfig,
        ChannelMessage,
        ChannelEventType,
        MessageChannel,
    )
except ImportError as _e:
    _logger.debug(f"channels.base 未可用: {_e}")
    ChannelAdapter = None
    ChannelConfig = None
    ChannelMessage = None
    ChannelEventType = None
    MessageChannel = None

try:
    from neurova.channels.manager import ChannelManager, get_channel_manager
except ImportError as _e:
    _logger.debug(f"channels.manager 未可用: {_e}")
    ChannelManager = None
    get_channel_manager = None

try:
    from neurova.channels.xiaoyi import XiaoYiAdapter, create_xiaoyi_adapter
except ImportError as _e:
    _logger.debug(f"channels.xiaoyi 未可用: {_e}")
    XiaoYiAdapter = None
    create_xiaoyi_adapter = None

try:
    from neurova.channels.voice import VoiceAdapter, create_voice_adapter
except ImportError as _e:
    _logger.debug(f"channels.voice 未可用: {_e}")
    VoiceAdapter = None
    create_voice_adapter = None

try:
    from neurova.session_manager import SessionManager, SessionMessage, SessionRecord, get_session_manager
except ImportError as _e:
    _logger.debug(f"session_manager 未可用: {_e}")
    SessionManager = None
    SessionMessage = None
    SessionRecord = None
    get_session_manager = None

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
