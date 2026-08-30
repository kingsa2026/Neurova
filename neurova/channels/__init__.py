"""
Neurova 渠道集成模块

提供飞书、钉钉、企业微信、语音通话等第三方平台的接入能力。
支持 Stream 模式（WebSocket 长连接）和 Webhook 模式。

使用方式:
    from neurova.channels import ChannelManager, get_channel_manager

    manager = get_channel_manager()
    manager.start()
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from neurova.channels.base import (
        ChannelAdapter,
        ChannelConfig,
        ChannelEventType,
        ChannelMessage,
    )
except ImportError as _e:
    _logger.debug("channels.base 未可用: %s", _e)
    ChannelAdapter = None
    ChannelConfig = None
    ChannelMessage = None
    ChannelEventType = None

try:
    from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage, UserIdentity
except ImportError as _e:
    _logger.debug("channels.models 未可用: %s", _e)
    ContentType = None
    MessageChannel = None
    UnifiedMessage = None
    UserIdentity = None

try:
    from neurova.channels.manager import ChannelManager, get_channel_manager
except ImportError as _e:
    _logger.debug("channels.manager 未可用: %s", _e)
    ChannelManager = None
    get_channel_manager = None

try:
    from neurova.channels.xiaoyi import XiaoYiAdapter, create_xiaoyi_adapter
except ImportError as _e:
    _logger.debug("channels.xiaoyi 未可用: %s", _e)
    XiaoYiAdapter = None
    create_xiaoyi_adapter = None

try:
    from neurova.channels.voice import VoiceAdapter, create_voice_adapter
except ImportError as _e:
    _logger.debug("channels.voice 未可用: %s", _e)
    VoiceAdapter = None
    create_voice_adapter = None

try:
    from neurova.channels.telegram_adapter import TelegramAdapter, create_telegram_adapter
except ImportError as _e:
    _logger.debug("channels.telegram_adapter 未可用: %s", _e)
    TelegramAdapter = None
    create_telegram_adapter = None

try:
    from neurova.session_manager import SessionManager, SessionMessage, SessionRecord, get_session_manager
except ImportError as _e:
    _logger.debug("session_manager 未可用: %s", _e)
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
    "ContentType",
    "UnifiedMessage",
    "ChannelManager",
    "get_channel_manager",
    "XiaoYiAdapter",
    "create_xiaoyi_adapter",
    "VoiceAdapter",
    "create_voice_adapter",
    "TelegramAdapter",
    "create_telegram_adapter",
    "SessionManager",
    "SessionMessage",
    "SessionRecord",
    "get_session_manager",
    "UserIdentity",
]
