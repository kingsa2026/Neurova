"""
微信消息发送 Mixin

处理企业微信、iLink、微信公众号三种模式的消息发送逻辑。
"""
from __future__ import annotations

import json
from neurova.core.logger import get_logger
from typing import TYPE_CHECKING, Any, Dict, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from neurova.channels.base import MessageChannel
from neurova.channels.models import ContentType, UnifiedMessage

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class WeChatMessagingMixin:
    """微信消息发送 Mixin — 消息发送与策略检查"""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def send_message(self, message: UnifiedMessage) -> bool:
        """
        发送微信消息

        参数:
        message: 统一消息对象

        返回:
        发送成功返回 True
        """
        if self.adapter.mode == "ilink":
            return self._send_ilink_message(message)
        elif self.adapter.mode == "official":
            return self._send_official_message(message)
        else:
            return self._send_wecom_message(message)

    def _send_wecom_message(self, message: UnifiedMessage) -> bool:
        """发送企业微信消息"""
        if not self.adapter._ensure_wecom_token():
            return False

        if not REQUESTS_AVAILABLE:
            logger.info("[企微模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            if self.adapter.kf_mode:
                return self._send_kf_message(message)
            else:
                return self._send_app_message(message)
        except Exception as e:
            logger.error("企业微信消息发送异常: %s", e)
            return False

    def _send_app_message(self, message: UnifiedMessage) -> bool:
        """发送企业微信应用消息"""
        a = self.adapter
        url = f"{a.WECOM_API_BASE}/cgi-bin/message/send"
        params = {"access_token": a.access_token}

        payload = {
            "touser": message.chat_id,
            "msgtype": "text",
            "agentid": int(a.agentid) if a.agentid else 0,
            "text": {"content": message.content},
        }

        if message.content_type == ContentType.IMAGE:
            payload["msgtype"] = "image"
            payload["image"] = {"media_id": message.file_url}
        elif message.content_type == ContentType.VOICE:
            payload["msgtype"] = "voice"
            payload["voice"] = {"media_id": message.file_url}
        elif message.content_type == ContentType.VIDEO:
            payload["msgtype"] = "video"
            payload["video"] = {
                "media_id": message.file_url,
                "title": message.file_name or "视频",
                "description": message.content or "",
            }
        elif message.content_type == ContentType.FILE:
            payload["msgtype"] = "file"
            payload["file"] = {"media_id": message.file_url}

        resp = requests.post(url, params=params, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode") == 0:
            logger.info("企业微信消息发送成功: %s", message.chat_id)
            return True
        else:
            logger.error("企业微信消息发送失败: %s", data)
            return False

    def _send_kf_message(self, message: UnifiedMessage) -> bool:
        """发送微信客服消息"""
        a = self.adapter
        url = f"{a.WECOM_API_BASE}/cgi-bin/kf/send_msg"
        params = {"access_token": a.access_token}

        payload = {
            "touser": message.chat_id,
            "open_kfid": a.open_kfid,
            "msgtype": "text",
            "text": {"content": message.content},
        }

        resp = requests.post(url, params=params, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode") == 0:
            logger.info("微信客服消息发送成功: %s", message.chat_id)
            return True
        else:
            logger.error("微信客服消息发送失败: %s", data)
            return False

    def _send_ilink_message(self, message: UnifiedMessage) -> bool:
        """
        发送 iLink 协议消息

        iLink 限制: context_token 最多回复 10 条消息
        建议关闭思考及工具输出，或使用消息合并功能
        """
        a = self.adapter
        if not a._ilink_initialized:
            logger.error("iLink 未初始化，请先扫码登录")
            return False

        # 检查回复次数限制
        session_key = f"{message.chat_id}:{message.session_id}"
        reply_count = a._reply_counts.get(session_key, 0)
        if reply_count >= 10:
            logger.warning("iLink 回复次数已达上限 (10次): %s", session_key)
            return False

        if not REQUESTS_AVAILABLE:
            logger.info("[iLink 模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            a._reply_counts[session_key] = reply_count + 1
            return True

        try:
            url = f"{a.ILINK_API_BASE}/message/send"
            headers = {"Authorization": f"Bearer {a.ilink_bot_token}"}

            payload = {
                "to_user": message.chat_id,
                "content": message.content,
                "msg_type": message.content_type.value,
            }

            # 如果启用消息合并，添加合并标识
            if a.ilink_message_merge:
                payload["merge"] = True

            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()

            if data.get("success"):
                a._reply_counts[session_key] = reply_count + 1
                return True
            else:
                logger.error("iLink 消息发送失败: %s", data)
                return False
        except Exception as e:
            logger.error("iLink 消息发送异常: %s", e)
            return False

    def _send_official_message(self, message: UnifiedMessage) -> bool:
        """发送微信公众号客服消息"""
        a = self.adapter
        if not a._ensure_official_token():
            return False

        if not REQUESTS_AVAILABLE:
            logger.info("[公众号模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            url = f"{a.WECHAT_OA_API_BASE}/cgi-bin/message/custom/send"
            params = {"access_token": a.official_access_token}

            payload = {
                "touser": message.chat_id,
                "msgtype": "text",
                "text": {"content": message.content},
            }

            if message.content_type == ContentType.IMAGE:
                payload["msgtype"] = "image"
                payload["image"] = {"media_id": message.file_url}
            elif message.content_type == ContentType.VOICE:
                payload["msgtype"] = "voice"
                payload["voice"] = {"media_id": message.file_url}
            elif message.content_type == ContentType.VIDEO:
                payload["msgtype"] = "video"
                payload["video"] = {
                    "media_id": message.file_url,
                    "title": message.file_name or "视频",
                    "description": message.content or "",
                }
            elif message.content_type == ContentType.CARD:
                payload["msgtype"] = "news"
                payload["news"] = {
                    "articles": [
                        {
                            "title": message.card_data.get("title", ""),
                            "description": message.card_data.get("description", ""),
                            "url": message.card_data.get("url", ""),
                            "picurl": message.card_data.get("picurl", ""),
                        }
                    ]
                }

            resp = requests.post(url, params=params, json=payload, timeout=10)
            data = resp.json()

            if data.get("errcode", 0) == 0:
                logger.info("微信公众号客服消息发送成功: %s", message.chat_id)
                return True
            else:
                logger.error("微信公众号客服消息发送失败: %s", data)
                return False
        except Exception as e:
            logger.error("微信公众号消息发送异常: %s", e)
            return False

    # ============================================================
    # 策略检查
    # ============================================================

    def should_process_message(self, raw_data: Dict) -> bool:
        """
        判断是否应该处理消息 (策略检查)

        主要用于 iLink 模式的群聊策略和白名单检查
        """
        a = self.adapter
        if a.mode != "ilink":
            return True

        chat_type = raw_data.get("chat_type", "single")
        from_user = raw_data.get("from_user", "")

        # 私聊策略
        if chat_type == "single":
            if a.ilink_private_strategy == "closed":
                return False
            if a.ilink_private_strategy == "whitelist":
                return from_user in a.ilink_whitelist_users

        # 群聊策略
        if chat_type == "group":
            if a.ilink_group_strategy == "closed":
                return False
            if a.ilink_group_strategy == "whitelist":
                return from_user in a.ilink_whitelist_users
            if a.ilink_require_mention:
                mention_list = raw_data.get("mention_list", [])
                bot_id = raw_data.get("to_user", "")
                return bot_id in mention_list

        return True

    def reset_reply_counts(self, session_key: str = None):
        """
        重置 iLink 回复计数器

        参数:
        session_key: 特定会话 key，如果为 None 则重置所有
        """
        if session_key:
            self.adapter._reply_counts.pop(session_key, None)
        else:
            self.adapter._reply_counts.clear()
