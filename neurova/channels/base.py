from __future__ import annotations

"""
渠道适配器基类

定义所有渠道适配器的公共接口和数据模型。
这是一个深度模块：小接口、深实现。

设计原则:
- 适配器不需要知道消息如何被处理，只需收发
- 所有平台差异封装在具体适配器中
- ChannelManager 负责生命周期和路由
"""

from neurova.core.logger import get_logger
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

logger = get_logger(__name__)

# ============================================================
# 数据模型
# ============================================================


class ChannelEventType(str, Enum):
    """渠道事件类型"""

    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    BOT_CONNECTED = "bot_connected"
    BOT_DISCONNECTED = "bot_disconnected"
    BOT_ERROR = "bot_error"
    USER_SUBSCRIBED = "user_subscribed"
    USER_UNSUBSCRIBED = "user_unsubscribed"


class MessageChannel(str, Enum):
    """消息渠道枚举"""

    WECHAT = "wechat"
    FEISHU = "feishu"
    DINGTALK = "dingtalk"
    WECOM = "wecom"
    WEBHOOK = "webhook"
    API = "api"
    TELEGRAM = "telegram"
    WEBSOCKET = "websocket"
    SIP = "sip"
    QQBOT = "qqbot"
    QQ = "qq"
    QCLAW = "qclaw"
    MQTT = "mqtt"
    DISCORD = "discord"
    MOBILE = "mobile"
    XIAOYI = "xiaoyi"


@dataclass
class ChannelConfig:
    """渠道配置"""

    channel_type: str  # feishu / dingtalk / wecom
    enabled: bool = True
    app_id: str = ""
    app_secret: str = ""
    # Webhook 模式
    webhook_url: str = ""
    webhook_token: str = ""
    # Stream 模式（长连接）
    use_stream: bool = True
    # 加密
    encrypt_key: str = ""
    verification_token: str = ""
    # 自定义
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_type": self.channel_type,
            "enabled": self.enabled,
            "app_id": self.app_id,
            "app_secret": "***" if self.app_secret else "",
            "webhook_url": self.webhook_url,
            "use_stream": self.use_stream,
            "extra": self.extra,
        }


@dataclass
class ChannelMessage:
    """渠道消息 - 跨平台统一消息格式"""

    channel_type: str  # feishu / dingtalk / wecom
    message_id: str  # 平台消息 ID
    sender_id: str  # 发送者 ID
    sender_name: str  # 发送者名称
    content: str  # 消息文本内容
    message_type: str = "text"  # text / image / file / ...
    chat_id: str = ""  # 会话 ID（群聊/私聊）
    chat_type: str = "p2p"  # p2p / group
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_event: Dict[str, Any] = field(default_factory=dict)  # 原始事件
    metadata: Dict[str, Any] = field(default_factory=dict)  # 附加元数据


# 事件回调类型
ChannelEventCallback = Callable[[ChannelEventType, ChannelMessage], Coroutine[Any, Any, None]]

# ============================================================
# 适配器基类
# ============================================================


class ChannelAdapter(ABC):
    """
    渠道适配器抽象基类

    每个具体适配器（飞书、钉钉、企业微信）需要实现:
    - connect(): 建立连接（Stream 模式建立 WebSocket，Webhook 模式注册）
    - disconnect(): 断开连接
    - send_message(): 发送消息到平台
    - is_connected(): 检查连接状态

    这是一个深度接口:
    - 调用者只需知道 connect / disconnect / send_message
    - 具体实现处理协议差异、重连、认证等复杂逻辑
    """

    def __init__(self, config: ChannelConfig):
        self.config = config
        self._connected = False
        self._event_callback: Optional[ChannelEventCallback] = None

    @property
    def channel_type(self) -> str:
        return self.config.channel_type

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_event_callback(self, callback: ChannelEventCallback):
        """设置事件回调 - 收到消息时调用"""
        self._event_callback = callback

    @abstractmethod
    async def connect(self) -> bool:
        """
        建立与平台的连接

        返回:
            bool: 连接是否成功
        """
        ...

    @abstractmethod
    async def disconnect(self):
        """断开连接并清理资源"""
        ...

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """
        发送消息到平台

        参数:
            chat_id: 会话 ID
            content: 消息内容
            message_type: 消息类型 (text, image, file, interactive)
            **kwargs: 平台特有参数

        返回:
            str: 发送成功时返回消息 ID，失败返回 None
        """
        ...

    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查

        返回:
            Dict: 包含 connected, channel_type, last_error 等
        """
        return {
            "channel_type": self.channel_type,
            "connected": self._connected,
            "enabled": self.config.enabled,
        }

    async def _emit_event(self, event_type: ChannelEventType, message: ChannelMessage):
        """触发事件回调"""
        if self._event_callback:
            try:
                await self._event_callback(event_type, message)
            except Exception as e:
                logger.exception("Event callback error for %s: %s", self.channel_type, e)

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置"""
        return {
            "channel_type": self.channel_type,
            "enabled": self.config.enabled,
            "app_id": self.config.app_id,
            "app_secret": "***" if self.config.app_secret else "",
            "webhook_url": self.config.webhook_url,
            "use_stream": self.config.use_stream,
            "extra": self.config.extra,
        }

    def update_config(self, updates: Dict[str, Any]):
        """更新渠道配置"""
        for key, value in updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            elif key in self.config.extra:
                self.config.extra[key] = value
            else:
                self.config.extra[key] = value

    def _make_message(
        self,
        message_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        chat_id: str,
        chat_type: str = "p2p",
        message_type: str = "text",
        raw_event: Optional[Dict[str, Any]] = None,
    ) -> ChannelMessage:
        """构造统一消息对象"""
        return ChannelMessage(
            channel_type=self.channel_type,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            message_type=message_type,
            chat_id=chat_id,
            chat_type=chat_type,
            raw_event=raw_event or {},
        )
