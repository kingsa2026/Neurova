from __future__ import annotations

"""channels/models.py — 渠道系统核心数据模型

包含：MessageChannel, ContentType, UnifiedMessage, UserIdentity, SessionContext, ChannelConfig
"""

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageChannel(Enum):
    """消息渠道"""

    WEB = "web"
    API = "api"
    FEISHU = "feishu"
    DINGTALK = "dingtalk"
    WECOM = "wecom"
    MOBILE = "mobile"
    VOICE = "voice"
    CLI = "cli"


class ContentType(Enum):
    """内容类型"""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO = "video"
    FILE = "file"
    LOCATION = "location"
    CARD = "card"
    MIXED = "mixed"
    SYSTEM = "system"


@dataclass
class UnifiedMessage:
    """统一消息模型 — 跨渠道消息格式"""

    message_id: str
    channel: MessageChannel
    content_type: ContentType
    content: str
    user_id: str
    chat_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    timestamp: Optional[float] = None
    reply_to: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    card_data: Optional[Dict[str, Any]] = None
    raw_message: Optional[Any] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["channel"] = self.channel.value
        result["content_type"] = self.content_type.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMessage":
        d = data.copy()
        d["channel"] = MessageChannel(d["channel"])
        d["content_type"] = ContentType(d["content_type"])
        return cls(**d)


@dataclass
class UserIdentity:
    """用户身份映射"""

    user_id: str
    channel: MessageChannel
    channel_user_id: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    mobile_device_id: Optional[str] = None
    created_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["channel"] = self.channel.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserIdentity":
        d = data.copy()
        d["channel"] = MessageChannel(d["channel"])
        return cls(**d)


@dataclass
class SessionContext:
    """会话上下文"""

    session_id: str
    user_id: str
    channel: MessageChannel
    agent_id: Optional[str] = None
    started_at: Optional[float] = None
    last_active_at: Optional[float] = None
    message_count: int = 0
    context_data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        now = time.time()
        if self.started_at is None:
            self.started_at = now
        if self.last_active_at is None:
            self.last_active_at = now

    def touch(self):
        """更新最后活跃时间"""
        self.last_active_at = time.time()
        self.message_count += 1

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["channel"] = self.channel.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        d = data.copy()
        d["channel"] = MessageChannel(d["channel"])
        return cls(**d)


@dataclass
class ChannelConfig:
    """渠道配置"""

    channel: MessageChannel
    enabled: bool = True
    webhook_url: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    bot_name: str = "Neurova"
    welcome_message: str = "你好！我是 Neurova，有什么可以帮你的？"
    max_message_length: int = 4096
    allowed_content_types: List[ContentType] = field(default_factory=lambda: [ContentType.TEXT])
    rate_limit: int = 60
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["channel"] = self.channel.value
        result["allowed_content_types"] = [ct.value for ct in self.allowed_content_types]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChannelConfig":
        d = data.copy()
        d["channel"] = MessageChannel(d["channel"])
        d["allowed_content_types"] = [ContentType(ct) for ct in d.get("allowed_content_types", ["text"])]
        return cls(**d)
