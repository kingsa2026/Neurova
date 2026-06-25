"""
微信消息解析 Mixin

处理企业微信、iLink、微信公众号三种模式的消息接收与解析。
"""
from __future__ import annotations

import json
from neurova.core.logger import get_logger
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from xml.etree import ElementTree as ET

from neurova.channels.base import MessageChannel
from neurova.channels.models import ContentType, UnifiedMessage

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class WeChatParsingMixin:
    """微信消息解析 Mixin — 消息接收与解析"""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收消息 (需通过 Webhook 回调)"""
        logger.warning("微信消息接收请使用 Webhook 模式")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析微信原始消息

        参数:
        raw_data: 微信原始消息数据 (dict/XML字符串/iLink JSON)

        返回:
        统一消息对象
        """
        if self.adapter.mode == "ilink":
            return self._parse_ilink_message(raw_data)
        elif self.adapter.mode == "official":
            return self._parse_official_message(raw_data)
        else:
            return self._parse_wecom_message(raw_data)

    def _parse_wecom_message(self, raw_data: Any) -> UnifiedMessage:
        """解析企业微信原始消息"""
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                return self._parse_xml_message(raw_data)

        if self.adapter.kf_mode:
            return self._parse_kf_message(raw_data)

        msg_type = raw_data.get("MsgType", "text")
        from_user = raw_data.get("FromUserName", "")
        content = ""
        content_type = ContentType.TEXT
        timestamp = None

        # 解析时间戳
        if "CreateTime" in raw_data:
            try:
                timestamp = datetime.fromtimestamp(int(raw_data["CreateTime"]))
            except (ValueError, TypeError):
                timestamp = datetime.now()

        # 解析消息内容
        if msg_type == "text":
            content = raw_data.get("Content", "")
        elif msg_type == "image":
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg_type == "voice":
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg_type == "video":
            content_type = ContentType.VIDEO
            content = "[视频]"
        elif msg_type == "file":
            content_type = ContentType.FILE
            content = "[文件]"
        elif msg_type == "location":
            content_type = ContentType.LOCATION
            content = f"[位置] Lat:{raw_data.get('Location_X', '')}, Lng:{raw_data.get('Location_Y', '')}"
        elif msg_type == "event":
            event = raw_data.get("Event", "")
            if event == "subscribe":
                content = "[关注事件]"
            elif event == "unsubscribe":
                content = "[取消关注事件]"
            elif event == "CLICK":
                content = f"[菜单点击: {raw_data.get('EventKey', '')}]"
            else:
                content = f"[事件: {event}]"
            content_type = ContentType.SYSTEM

        return UnifiedMessage(
            message_id=raw_data.get("MsgId", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=from_user,
            user_id=from_user,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            raw_message=raw_data,
            metadata={
                "msg_type": msg_type,
                "agent_id": raw_data.get("AgentID", ""),
                "pic_url": raw_data.get("PicUrl", ""),
                "media_id": raw_data.get("MediaId", ""),
                "event": raw_data.get("Event", ""),
                "event_key": raw_data.get("EventKey", ""),
            },
        )

    def _parse_ilink_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析 iLink 协议消息

        iLink 消息格式 (假设):
        {
            "msg_id": "xxx",
            "from_user": "wxid_xxx",
            "to_user": "bot_wxid",
            "content": "消息内容",
            "msg_type": "text",
            "chat_type": "single/group",
            "chat_id": "群ID或个人ID",
            "timestamp": 1234567890,
            "mention_list": ["@bot_wxid"],
            "is_group": false,
        }
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                raw_data = {}

        msg_type = raw_data.get("msg_type", "text")
        from_user = raw_data.get("from_user", "")
        content = raw_data.get("content", "")
        chat_type = raw_data.get("chat_type", "single")
        chat_id = raw_data.get("chat_id", from_user)
        timestamp_raw = raw_data.get("timestamp")

        # 从 datetime 转换
        ts = None
        if timestamp_raw:
            try:
                ts = datetime.fromtimestamp(timestamp_raw)
            except (ValueError, TypeError):
                ts = datetime.now()
        else:
            ts = datetime.now()

        # 确定内容类型
        content_type = ContentType.TEXT
        if msg_type == "image":
            content_type = ContentType.IMAGE
        elif msg_type == "voice":
            content_type = ContentType.VOICE
        elif msg_type == "video":
            content_type = ContentType.VIDEO
        elif msg_type == "file":
            content_type = ContentType.FILE
        elif msg_type == "location":
            content_type = ContentType.LOCATION

        # 检查是否需要 @提及
        if self.adapter.ilink_require_mention and chat_type == "group":
            mention_list = raw_data.get("mention_list", [])
            bot_id = raw_data.get("to_user", "")
            if bot_id not in mention_list:
                logger.debug("群消息未@机器人，忽略")

        # 检查策略
        if not self.adapter.should_process_message(raw_data):
            logger.debug("消息被策略过滤: %s, user=%s", chat_type, from_user)

        return UnifiedMessage(
            message_id=raw_data.get("msg_id", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=chat_id,
            user_id=from_user,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=ts,
            raw_message=raw_data,
            metadata={
                "msg_type": msg_type,
                "chat_type": chat_type,
                "is_group": raw_data.get("is_group", False),
                "mention_list": raw_data.get("mention_list", []),
                "to_user": raw_data.get("to_user", ""),
                "file_url": raw_data.get("file_url", ""),
                "file_name": raw_data.get("file_name", ""),
            },
        )

    def _parse_official_message(self, raw_data: Any) -> UnifiedMessage:
        """解析微信公众号原始消息"""
        # 公众号消息通常是 XML 格式
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                return self._parse_xml_message(raw_data)

        msg_type = raw_data.get("MsgType", "text")
        from_user = raw_data.get("FromUserName", "")
        content = ""
        content_type = ContentType.TEXT
        timestamp = None

        if "CreateTime" in raw_data:
            try:
                timestamp = datetime.fromtimestamp(int(raw_data["CreateTime"]))
            except (ValueError, TypeError):
                timestamp = datetime.now()

        if msg_type == "text":
            content = raw_data.get("Content", "")
        elif msg_type == "image":
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg_type == "voice":
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg_type == "video":
            content_type = ContentType.VIDEO
            content = "[视频]"
        elif msg_type == "location":
            content_type = ContentType.LOCATION
            content = f"[位置] Lat:{raw_data.get('Location_X', '')}, Lng:{raw_data.get('Location_Y', '')}"
        elif msg_type == "event":
            event = raw_data.get("Event", "")
            if event == "subscribe":
                content = "[关注事件]"
            elif event == "unsubscribe":
                content = "[取消关注事件]"
            elif event == "CLICK":
                content = f"[菜单点击: {raw_data.get('EventKey', '')}]"
            else:
                content = f"[事件: {event}]"
            content_type = ContentType.SYSTEM

        return UnifiedMessage(
            message_id=raw_data.get("MsgId", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=from_user,
            user_id=from_user,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            raw_message=raw_data,
            metadata={
                "msg_type": msg_type,
                "event": raw_data.get("Event", ""),
                "event_key": raw_data.get("EventKey", ""),
                "pic_url": raw_data.get("PicUrl", ""),
                "media_id": raw_data.get("MediaId", ""),
            },
        )

    def _parse_xml_message(self, xml_data: str) -> UnifiedMessage:
        """解析 XML 格式消息"""
        try:
            root = ET.fromstring(xml_data)

            def get_text(tag):
                elem = root.find(tag)
                return elem.text if elem is not None else ""

            msg_type = get_text("MsgType")
            from_user = get_text("FromUserName")
            content = get_text("Content") if msg_type == "text" else ""
            msg_id = get_text("MsgId") or str(int(time.time()))

            create_time = get_text("CreateTime")
            timestamp = None
            if create_time:
                try:
                    timestamp = datetime.fromtimestamp(int(create_time))
                except (ValueError, TypeError):
                    timestamp = datetime.now()

            content_type = ContentType.TEXT
            if msg_type == "image":
                content_type = ContentType.IMAGE
                content = "[图片]"
            elif msg_type == "voice":
                content_type = ContentType.VOICE
                content = "[语音]"
            elif msg_type == "video":
                content_type = ContentType.VIDEO
                content = "[视频]"
            elif msg_type == "location":
                content_type = ContentType.LOCATION
                content = f"[位置] Lat:{get_text('Location_X')}, Lng:{get_text('Location_Y')}"
            elif msg_type == "event":
                content_type = ContentType.SYSTEM
                event = get_text("Event")
                content = f"[事件: {event}]"

            return UnifiedMessage(
                message_id=msg_id,
                channel=MessageChannel.WECHAT,
                chat_id=from_user,
                user_id=from_user,
                agent_id="",
                content=content,
                content_type=content_type,
                timestamp=timestamp,
                raw_message=xml_data,
                metadata={
                    "msg_type": msg_type,
                    "event": get_text("Event"),
                    "event_key": get_text("EventKey"),
                    "pic_url": get_text("PicUrl"),
                    "media_id": get_text("MediaId"),
                },
            )
        except ET.ParseError as e:
            logger.error("XML 解析失败: %s", e)
            return UnifiedMessage(
                message_id=str(int(time.time())),
                channel=MessageChannel.WECHAT,
                chat_id="",
                user_id="",
                agent_id="",
                content="",
                content_type=ContentType.TEXT,
                timestamp=datetime.now(),
                raw_message=xml_data,
                metadata={"error": f"XML 解析失败: {e}"},
            )

    def _parse_kf_message(self, data: Dict) -> UnifiedMessage:
        """解析微信客服消息"""
        msg_list = data.get("msg_list", [])
        if not msg_list:
            return UnifiedMessage(
                message_id=str(int(time.time())),
                channel=MessageChannel.WECHAT,
                chat_id="",
                user_id="",
                agent_id="",
                content="",
                content_type=ContentType.TEXT,
                timestamp=datetime.now(),
                raw_message=data,
                metadata={"error": "空消息列表"},
            )

        msg = msg_list[0]
        msg_type = msg.get("msgtype", "text")
        external_userid = msg.get("external_userid", "")

        content = ""
        content_type = ContentType.TEXT

        if msg_type == "text":
            content = msg.get("text", {}).get("content", "")
        elif msg_type == "image":
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg_type == "voice":
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg_type == "video":
            content_type = ContentType.VIDEO
            content = "[视频]"

        return UnifiedMessage(
            message_id=msg.get("msgid", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=external_userid,
            user_id=external_userid,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=datetime.now(),
            raw_message=data,
            metadata={
                "msg_type": msg_type,
                "open_kfid": msg.get("open_kfid", ""),
            },
        )
