"""
微信消息 Mixin

包含:
1. 消息发送 (send_message, _send_wecom_message, _send_app_message, _send_kf_message, _send_ilink_message, _send_official_message)
2. 消息接收与解析 (receive_message, parse_raw_message, _parse_wecom_message, _parse_ilink_message, _parse_official_message, _parse_xml_message, _parse_kf_message)
3. 策略检查 (should_process_message)
4. 签名验证 (verify_signature)

由 WeChatAdapter 通过多继承使用，所有属性都来自主类。
"""

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 消息类型常量
MSG_TYPE_TEXT = "text"
MSG_TYPE_IMAGE = "image"
MSG_TYPE_VOICE = "voice"
MSG_TYPE_VIDEO = "video"
MSG_TYPE_FILE = "file"
MSG_TYPE_LOCATION = "location"
MSG_TYPE_LINK = "link"
MSG_TYPE_EVENT = "event"
MSG_TYPE_NEWS = "news"
MSG_TYPE_MINIPROGRAM = "miniprogram"


class MessageMixin:
    """
    微信消息 Mixin

    提供:
    - 消息发送 (多种类型)
    - 消息接收与解析
    - 策略检查
    - 签名验证
    """

    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """
        发送消息

        参数:
            chat_id: 接收者 (openid 或 userid)
            content: 消息内容
            message_type: 消息类型

        返回:
            str: 消息 ID
        """
        auth_type = self.config.extra.get("auth_type", "wecom")

        if auth_type == "wecom":
            return await self._send_wecom_message(chat_id, content, message_type, **kwargs)
        elif auth_type == "official":
            return await self._send_official_message(chat_id, content, message_type, **kwargs)
        elif auth_type == "ilink":
            return await self._send_ilink_message(chat_id, content, message_type, **kwargs)
        else:
            logger.error(f"Unknown auth type for send_message: {auth_type}")
            return None

    async def _send_wecom_message(
        self,
        chat_id: str,
        content: str,
        message_type: str,
        **kwargs,
    ) -> Optional[str]:
        """企业微信消息发送"""
        try:
            # 构造消息体
            if message_type == "text":
                data = {
                    "touser": chat_id,
                    "msgtype": "text",
                    "agentid": self.config.extra.get("agent_id", 0),
                    "text": {"content": content},
                }
            elif message_type == "image":
                data = {
                    "touser": chat_id,
                    "msgtype": "image",
                    "agentid": self.config.extra.get("agent_id", 0),
                    "image": {"media_id": content},
                }
            elif message_type == "news":
                data = {
                    "touser": chat_id,
                    "msgtype": "news",
                    "agentid": self.config.extra.get("agent_id", 0),
                    "news": content,  # 应该是文章列表
                }
            else:
                logger.error(f"Unsupported message type: {message_type}")
                return None

            # 发送消息
            response = await self._api_request(
                "POST",
                "/message/send",
                data=data,
            )

            if response.get("errcode") == 0:
                logger.info(f"WeCom message sent to {chat_id}")
                return response.get("msgid")
            else:
                logger.error(f"WeCom message send failed: {response}")
                return None

        except Exception as e:
            logger.exception(f"WeCom message send error: {e}")
            return None

    async def _send_official_message(
        self,
        chat_id: str,
        content: str,
        message_type: str,
        **kwargs,
    ) -> Optional[str]:
        """公众号消息发送"""
        try:
            # 构造消息体
            if message_type == "text":
                data = {
                    "touser": chat_id,
                    "msgtype": "text",
                    "text": {"content": content},
                }
            elif message_type == "image":
                data = {
                    "touser": chat_id,
                    "msgtype": "image",
                    "image": {"media_id": content},
                }
            elif message_type == "news":
                data = {
                    "touser": chat_id,
                    "msgtype": "news",
                    "news": {"articles": content},  # 文章列表
                }
            else:
                logger.error(f"Unsupported message type: {message_type}")
                return None

            # 发送消息
            response = await self._api_request(
                "POST",
                "/message/custom/send",
                data=data,
            )

            if response.get("errcode") == 0:
                logger.info(f"Official message sent to {chat_id}")
                return response.get("msgid")
            else:
                logger.error(f"Official message send failed: {response}")
                return None

        except Exception as e:
            logger.exception(f"Official message send error: {e}")
            return None

    async def _send_ilink_message(
        self,
        chat_id: str,
        content: str,
        message_type: str,
        **kwargs,
    ) -> Optional[str]:
        """iLink 消息发送"""
        # iLink 消息发送实现
        logger.warning("iLink message sending not implemented")
        return None

    async def _send_kf_message(
        self,
        chat_id: str,
        content: str,
        message_type: str,
        **kwargs,
    ) -> Optional[str]:
        """客服消息发送"""
        try:
            data = {
                "touser": chat_id,
                "msgtype": message_type,
                "text": {"content": content} if message_type == "text" else None,
            }

            response = await self._api_request(
                "POST",
                "/message/custom/send",
                data=data,
            )

            if response.get("errcode") == 0:
                logger.info(f"KF message sent to {chat_id}")
                return response.get("msgid")
            else:
                logger.error(f"KF message send failed: {response}")
                return None

        except Exception as e:
            logger.exception(f"KF message send error: {e}")
            return None

    def receive_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        接收消息

        参数:
            data: 原始消息数据

        返回:
            Dict: 解析后的消息
        """
        auth_type = self.config.extra.get("auth_type", "wecom")

        if auth_type == "wecom":
            return self._parse_wecom_message(data)
        elif auth_type == "official":
            return self._parse_official_message(data)
        elif auth_type == "ilink":
            return self._parse_ilink_message(data)
        else:
            logger.error(f"Unknown auth type for receive_message: {auth_type}")
            return None

    def _parse_wecom_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析企业微信消息"""
        try:
            msg_type = data.get("MsgType", "")

            message = {
                "message_id": data.get("MsgId", ""),
                "from_user": data.get("FromUserName", ""),
                "to_user": data.get("ToUserName", ""),
                "message_type": msg_type,
                "create_time": data.get("CreateTime", 0),
                "raw_data": data,
            }

            if msg_type == "text":
                message["content"] = data.get("Content", "")
            elif msg_type == "image":
                message["content"] = data.get("PicUrl", "")
                message["media_id"] = data.get("MediaId", "")
            elif msg_type == "voice":
                message["content"] = data.get("Recognition", "")
                message["media_id"] = data.get("MediaId", "")
            elif msg_type == "video":
                message["content"] = data.get("Description", "")
                message["media_id"] = data.get("MediaId", "")
            elif msg_type == "location":
                message["content"] = data.get("Label", "")
                message["latitude"] = data.get("Location_X", "")
                message["longitude"] = data.get("Location_Y", "")
            elif msg_type == "link":
                message["content"] = data.get("Description", "")
                message["title"] = data.get("Title", "")
                message["url"] = data.get("Url", "")
            elif msg_type == "event":
                message["content"] = data.get("Event", "")
                message["event_key"] = data.get("EventKey", "")

            return message

        except Exception as e:
            logger.exception(f"WeCom message parse error: {e}")
            return None

    def _parse_official_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析公众号消息"""
        # 公众号消息解析与企业微信类似
        return self._parse_wecom_message(data)

    def _parse_ilink_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析 iLink 消息"""
        try:
            return {
                "message_id": data.get("msgId", ""),
                "from_user": data.get("openId", ""),
                "message_type": data.get("msgType", ""),
                "content": data.get("content", ""),
                "raw_data": data,
            }
        except Exception as e:
            logger.exception(f"iLink message parse error: {e}")
            return None

    def _parse_xml_message(self, xml_content: str) -> Optional[Dict[str, Any]]:
        """解析 XML 格式消息"""
        try:
            root = ET.fromstring(xml_content)
            message = {}

            for child in root:
                tag = child.tag
                text = child.text or ""
                message[tag] = text

            return message

        except Exception as e:
            logger.exception(f"XML message parse error: {e}")
            return None

    def parse_raw_message(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析原始消息数据

        参数:
            raw_data: 原始数据 (可能是 XML 字符串或字典)

        返回:
            Dict: 解析后的消息
        """
        if isinstance(raw_data, str):
            return self._parse_xml_message(raw_data)
        elif isinstance(raw_data, dict):
            return raw_data
        else:
            logger.error(f"Unsupported raw data type: {type(raw_data)}")
            return None

    def should_process_message(self, message: Dict[str, Any]) -> bool:
        """
        策略检查: 是否处理该消息

        参数:
            message: 消息数据

        返回:
            bool: 是否处理
        """
        # 过滤重复消息
        msg_id = message.get("message_id", "")
        if hasattr(self, "_processed_messages"):
            if msg_id in self._processed_messages:
                return False
            self._processed_messages.add(msg_id)
        else:
            self._processed_messages = {msg_id}

        # 过滤非文本消息（可配置）
        msg_type = message.get("message_type", "")
        if msg_type not in [MSG_TYPE_TEXT, MSG_TYPE_EVENT, MSG_TYPE_LOCATION]:
            logger.debug(f"Skipping message type: {msg_type}")
            return False

        return True

    def verify_signature(
        self,
        signature: str,
        timestamp: str,
        nonce: str,
        echostr: str = "",
    ) -> Optional[str]:
        """
        验证签名

        参数:
            signature: 微信签名
            timestamp: 时间戳
            nonce: 随机数
            echostr: 随机字符串 (仅验证时使用)

        返回:
            str: echostr (验证成功) 或 None (验证失败)
        """
        try:
            token = self.config.webhook_token
            if not token:
                logger.error("Webhook token not configured")
                return None

            # 按字典序排序
            params = sorted([token, timestamp, nonce])

            # SHA1 加密
            hash_str = "".join(params).encode("utf-8")
            hash_code = hashlib.sha1(hash_str).hexdigest()

            if hash_code == signature:
                return echostr
            else:
                logger.warning("Signature verification failed")
                return None

        except Exception as e:
            logger.exception(f"Signature verification error: {e}")
            return None
