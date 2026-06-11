from __future__ import annotations

"""
钉钉渠道适配器

支持两种接入模式:
1. Stream 模式（WebSocket 长连接）- 推荐，无需公网 IP
2. Webhook 模式 - 群机器人 Webhook

使用钉钉官方 SDK: dingtalk-stream

API 参考:
- 钉钉开放平台: https://open.dingtalk.com
- dingtalk-stream PyPI: https://pypi.org/project/dingtalk-stream/
- Stream 模式文档: https://open.dingtalk.com/document/development/development-robot-overview
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)

logger = logging.getLogger(__name__)

class DingTalkAdapter(ChannelAdapter):
    """
    钉钉渠道适配器

    接入方式:
    1. 在钉钉开发者平台创建应用
    2. 启用机器人能力
    3. 配置权限: 机器人消息接收与发送
    4. 选择 Stream 模式或 Webhook 模式

    Stream 模式:
    - 使用 dingtalk-stream SDK 建立 WebSocket 连接
    - 无需公网 IP，本地开发友好

    Webhook 模式:
    - 群机器人 Webhook（只能发消息，不能收消息）
    - 自建应用 Webhook（需要公网 URL）
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "dingtalk"
        self._stream_client = None
        self._access_token = None
        self._token_expires_at = 0

    async def connect(self) -> bool:
        """建立钉钉连接"""
        try:
            if self.config.use_stream:
                return await self._connect_stream()
            else:
                return await self._connect_webhook()
        except Exception as e:
            logger.exception(f"DingTalk connect error: {e}")
            return False

    async def _connect_stream(self) -> bool:
        """Stream 模式: 通过 WebSocket 长连接接收事件"""
        try:

            # 创建凭证
            credential = dingtalk_stream.Credential(
                self.config.app_id,
                self.config.app_secret,
            )

            # 创建流式客户端
            self._stream_client = dingtalk_stream.DingtalkStreamClient(credential)

            # 注册机器人消息回调
            self._stream_client.register_callback_listener(
                "/v1.0/im/bot/messages/handle",
                self._handle_bot_message,
            )

            # 启动连接（非阻塞）
            import threading
            self._ws_thread = threading.Thread(
                target=self._stream_client.start,
                daemon=True,
            )
            self._ws_thread.start()

            self._connected = True
            logger.info("DingTalk Stream connected")
            return True

        except ImportError:
            logger.error(
                "dingtalk-stream not installed. Run: pip install dingtalk-stream"
            )
            return False
        except Exception as e:
            logger.exception(f"DingTalk Stream connect error: {e}")
            return False

    async def _connect_webhook(self) -> bool:
        """Webhook 模式: 群机器人 Webhook"""
        self._connected = True
        logger.info("DingTalk Webhook mode configured")
        return True

    def _handle_bot_message(self, data: Any) -> Any:
        """
        处理钉钉机器人消息（Stream 模式回调）

        回调数据结构:
        {
            "conversationId": "xxx",
            "chatbotCorpId": "xxx",
            "chatbotUserId": "xxx",
            "msgId": "xxx",
            "senderNick": "xxx",
            "senderCorpId": "xxx",
            "senderId": "xxx",
            "sessionWebhookExpiredTime": 1613635053921,
            "createAt": 1613635053921,
            "senderCorpId": "xxx",
            "conversationType": "1",  // 1=单聊, 2=群聊
            "senderId": "xxx",
            "sessionWebhook": "xxx",
            "text": {"content": "xxx"},
            "msgtype": "text"
        }
        """
        try:
            # 解析消息
            msg_id = data.get("msgId", "")
            sender_id = data.get("senderId", "")
            sender_name = data.get("senderNick", "")
            chat_id = data.get("conversationId", "")
            msg_type = data.get("msgtype", "text")
            conversation_type = data.get("conversationType", "1")

            # 解析内容
            content = ""
            if msg_type == "text":
                text_data = data.get("text", {})
                content = text_data.get("content", "").strip()
            elif msg_type == "markdown":
                markdown_data = data.get("markdown", {})
                content = markdown_data.get("text", "").strip()

            # 构造统一消息
            channel_msg = self._make_message(
                message_id=msg_id,
                sender_id=sender_id,
                sender_name=sender_name,
                content=content,
                chat_id=chat_id,
                chat_type="group" if conversation_type == "2" else "p2p",
                message_type=msg_type,
                raw_event=data,
            )

            # 保存 session_webhook 用于回复
            channel_msg.metadata["session_webhook"] = data.get("sessionWebhook", "")

            # 同步回调转异步
            # 使用 call_soon_threadsafe 调度到主事件循环，避免跨事件循环问题
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环正在运行，使用 call_soon_threadsafe
                    asyncio.run_coroutine_threadsafe(
                        self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg),
                        loop
                    )
                else:
                    # 如果事件循环未运行，直接运行
                    loop.run_until_complete(
                        self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
                    )
            except RuntimeError:
                # 如果没有事件循环，创建新的
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
                )
                loop.close()

        except Exception as e:
            logger.exception(f"DingTalk message handler error: {e}")

    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """发送消息到钉钉"""
        try:
            # 优先使用 session_webhook 回复（Stream 模式）
            session_webhook = kwargs.get("session_webhook", "")
            if session_webhook:
                return await self._send_via_session_webhook(
                    session_webhook, content, message_type
                )

            # 使用 Access Token API
            if not self._access_token or time.time() > self._token_expires_at:
                await self._refresh_access_token()

            if not self._access_token:
                logger.error("Failed to get DingTalk access token")
                return None

            return await self._send_via_api(chat_id, content, message_type)

        except Exception as e:
            logger.exception(f"DingTalk send error: {e}")
            return None

    async def _send_via_session_webhook(
        self, webhook_url: str, content: str, message_type: str
    ) -> Optional[str]:
        """通过 session webhook 发送回复"""
        import aiohttp

        payload = {
            "msgtype": message_type,
        }

        if message_type == "text":
            payload["text"] = {"content": content}
        elif message_type == "markdown":
            payload["markdown"] = {"title": "回复", "text": content}
        else:
            payload["text"] = {"content": content}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get("errcode") == 0:
                    logger.info("DingTalk session webhook message sent")
                    return result.get("messageId", "sent")
                else:
                    logger.error(f"DingTalk session webhook failed: {result}")
                    return None

    async def _send_via_api(
        self, chat_id: str, content: str, message_type: str
    ) -> Optional[str]:
        """通过 DingTalk OpenAPI 发送消息"""
        import aiohttp

        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        headers = {
            "x-acs-dingtalk-access-token": self._access_token,
            "Content-Type": "application/json",
        }

        msg_data = {"content": content}
        payload = {
            "robotCode": self.config.app_id,
            "userIds": [chat_id],
            "msgKey": f"sampleText" if message_type == "text" else f"sampleMarkdown",
            "msgParam": json.dumps(msg_data),
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                if resp.status == 200:
                    logger.info("DingTalk API message sent")
                    return result.get("processQueryKey", "sent")
                else:
                    logger.error(f"DingTalk API failed: {result}")
                    return None

    async def _refresh_access_token(self):
        """刷新钉钉 Access Token"""
        import aiohttp

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        payload = {"appKey": self.config.app_id, "appSecret": self.config.app_secret}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                if resp.status == 200 and "accessToken" in result:
                    self._access_token = result["accessToken"]
                    expire_in = result.get("expireIn", 7200)
                    self._token_expires_at = time.time() + expire_in - 300  # 提前5分钟刷新
                    logger.info("DingTalk access token refreshed")
                else:
                    logger.error(f"DingTalk token refresh failed: {result}")

    async def disconnect(self):
        """断开钉钉连接"""
        if self._stream_client:
            try:
                pass  # daemon 线程自动退出
            except Exception as e:
                logger.warning(f"DingTalk disconnect warning: {e}")

        self._connected = False
        self._stream_client = None
        self._access_token = None
        logger.info("DingTalk adapter disconnected")

    async def health_check(self) -> Dict[str, Any]:
        """钉钉健康检查"""
        base = await super().health_check()
        base.update({
            "app_id": self.config.app_id[:8] + "***" if self.config.app_id else "",
            "stream_mode": self.config.use_stream,
            "has_token": bool(self._access_token),
        })
        return base

# ============================================================
# 群机器人 Webhook 适配器（轻量级，仅发送）
# ============================================================

class DingTalkWebhookBot:
    """
    钉钉群机器人 Webhook

    仅支持发送消息，不支持接收。
    适用于告警通知、日报推送等单向场景。
    """

    def __init__(self, webhook_url: str, secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    async def send_text(self, text: str, at_all: bool = False, at_mobiles: list = None) -> bool:
        """发送文本消息"""
        import aiohttp
        import hashlib
        import base64
        import urllib.parse

        payload = {
            "msgtype": "text",
            "text": {"content": text},
            "at": {"isAtAll": at_all, "atMobiles": at_mobiles or []},
        }

        url = self.webhook_url
        if self.secret:
            timestamp = str(round(time.time() * 1000))
            sign_str = f"{timestamp}\n{self.secret}"
            hmac_code = hmac.new(
                self.secret.encode("utf-8"),
                sign_str.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
            url += f"&timestamp={timestamp}&sign={sign}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                return result.get("errcode") == 0

    async def send_markdown(self, title: str, text: str, at_all: bool = False) -> bool:
        """发送 Markdown 消息"""
        import aiohttp

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {"isAtAll": at_all},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                return result.get("errcode") == 0

def create_dingtalk_adapter(
    app_id: str,
    app_secret: str,
    use_stream: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> DingTalkAdapter:
    """创建钉钉适配器的工厂函数"""
    config = ChannelConfig(
        channel_type="dingtalk",
        app_id=app_id,
        app_secret=app_secret,
        use_stream=use_stream,
        extra=extra or {},
    )
    return DingTalkAdapter(config)
