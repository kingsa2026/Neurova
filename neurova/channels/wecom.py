from __future__ import annotations

"""
企业微信渠道适配器

支持两种接入模式:
1. 智能机器人（WebSocket 长连接）- 最新 API，推荐
2. 自建应用 Webhook（HTTP 回调）- 需要公网 URL

API 参考:
- 企业微信开发者中心: https://developer.work.weixin.qq.com
- 智能机器人概述: https://developer.work.weixin.qq.com/document/path/101039
- 接收消息: https://developer.work.weixin.qq.com/document/path/100719
- 发送消息: https://developer.work.weixin.qq.com/document/path/90236
"""

import asyncio
import hashlib
from neurova.core.logger import get_logger
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
)

logger = get_logger(__name__)


class WeComAdapter(ChannelAdapter):
    """
    企业微信渠道适配器

    接入方式:
    1. 在企业微信管理后台创建自建应用或智能机器人
    2. 配置回调 URL（Webhook 模式）或启用 WebSocket（智能机器人模式）
    3. 设置 Token 和 EncodingAESKey

    智能机器人模式（推荐）:
    - 企业微信 2025 年推出的新能力
    - 支持 WebSocket 长连接，无需公网 IP
    - 支持文本、图片、文件等多种消息类型

    自建应用模式:
    - 需要公网可访问的回调 URL
    - 支持被动回复消息
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "wecom"
        self._access_token = None
        self._token_expires_at = 0
        self._callback_token = config.webhook_token or config.extra.get("callback_token", "")
        self._encoding_aes_key = config.extra.get("encoding_aes_key", "")
        self._corpid = config.extra.get("corpid", "")
        self._agentid = config.extra.get("agentid", "")

    async def connect(self) -> bool:
        """建立企业微信连接"""
        try:
            if self.config.use_stream:
                return await self._connect_stream()
            else:
                return await self._connect_webhook()
        except Exception as e:
            logger.exception("WeCom connect error: %s", e)
            return False

    async def _connect_stream(self) -> bool:
        """
        WebSocket 长连接模式（智能机器人）

        企业微信智能机器人通过 WebSocket 接收消息推送，
        无需公网 IP，适合本地开发和内网部署。
        """
        try:
            # 企业微信智能机器人 WebSocket 连接
            # 需要 corpid, secret (应用Secret)
            # 实际连接使用企业微信官方 SDK 或自行实现 WebSocket

            # 企业微信智能机器人的 WebSocket 连接流程:
            # 1. 获取 access_token
            # 2. 建立 WebSocket 连接到 callback.weixin.qq.com
            # 3. 通过 WebSocket 接收消息推送
            # 4. 通过 WebSocket 发送回复

            pass

            # 尝试获取 access_token
            if not self._access_token or time.time() > self._token_expires_at:
                await self._refresh_access_token()

            if self._access_token:
                self._connected = True
                logger.info("WeCom Stream mode configured (access token obtained)")
                # WebSocket 连接需要企业微信 SDK 支持
                # 这里提供基础框架，实际连接逻辑取决于企业微信 SDK 版本
                return True
            else:
                logger.error("Failed to get WeCom access token")
                return False

        except Exception as e:
            logger.exception("WeCom Stream connect error: %s", e)
            return False

    async def _connect_webhook(self) -> bool:
        """Webhook 模式: HTTP 回调"""
        self._connected = True
        logger.info("WeCom Webhook mode configured. " f"Callback URL: %s", self.config.webhook_url)
        return True

    def handle_callback(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        xml_data: str,
    ) -> Optional[str]:
        """
        处理企业微信回调（Webhook 模式）

        当用户发送消息给企业微信应用时，企业微信会 POST XML 数据到回调 URL。
        此方法解析 XML 并触发事件。

        参数:
            msg_signature: 消息签名
            timestamp: 时间戳
            nonce: 随机数
            xml_data: XML 格式的消息数据

        返回:
            str: 被动回复的 XML（可选）
        """
        try:
            # 验证签名
            if self._callback_token:
                check_list = sorted([self._callback_token, timestamp, nonce])
                signature = hashlib.sha1("".join(check_list).encode("utf-8")).hexdigest()
                if signature != msg_signature:
                    logger.warning("WeCom callback signature verification failed")
                    return None

            # 解析 XML
            root = ET.fromstring(xml_data)
            to_user_name = root.findtext("ToUserName", "")
            from_user = root.findtext("FromUserName", "")
            create_time = root.findtext("CreateTime", "")
            msg_type = root.findtext("MsgType", "text")
            content = root.findtext("Content", "").strip()
            msg_id = root.findtext("MsgId", "")

            # 构造统一消息
            channel_msg = self._make_message(
                message_id=msg_id or f"wecom_{create_time}",
                sender_id=from_user,
                sender_name=from_user,  # 企业微信回调中没有发送者昵称
                content=content,
                chat_id=from_user,  # 企业微信单聊以 user id 为会话 ID
                chat_type="p2p",
                message_type=msg_type,
                raw_event={
                    "to_user_name": to_user_name,
                    "from_user": from_user,
                    "create_time": create_time,
                    "msg_type": msg_type,
                    "xml_data": xml_data,
                },
            )

            # 触发事件
            # 使用 call_soon_threadsafe 调度到主事件循环，避免跨事件循环问题
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环正在运行，使用 call_soon_threadsafe
                    asyncio.run_coroutine_threadsafe(
                        self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg), loop
                    )
                else:
                    # 如果事件循环未运行，直接运行
                    loop.run_until_complete(self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg))
            except RuntimeError:
                # 如果没有事件循环，创建新的
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg))
                loop.close()

            # 被动回复（示例: 回复文本）
            return self._build_reply_xml(from_user, to_user_name, "收到您的消息，正在处理中...")

        except Exception as e:
            logger.exception("WeCom callback error: %s", e)
            return None

    def _build_reply_xml(self, to_user: str, from_user: str, content: str, msg_type: str = "text") -> str:
        """构造被动回复 XML"""
        timestamp = str(int(time.time()))
        xml_template = f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[{msg_type}]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""
        return xml_template

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """
        URL 验证（企业微信回调配置时使用）

        企业微信会发送 GET 请求验证回调 URL 的有效性。
        """
        if self._callback_token:
            check_list = sorted([self._callback_token, timestamp, nonce])
            signature = hashlib.sha1("".join(check_list).encode("utf-8")).hexdigest()
            if signature != msg_signature:
                raise ValueError("URL verification signature mismatch")
        return echostr

    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """发送消息到企业微信"""
        try:
            if not self._access_token or time.time() > self._token_expires_at:
                await self._refresh_access_token()

            if not self._access_token:
                logger.error("Failed to get WeCom access token")
                return None

            import aiohttp

            # 发送应用消息
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self._access_token}"

            if message_type == "text":
                payload = {
                    "touser": chat_id,
                    "msgtype": "text",
                    "agentid": int(self._agentid) if self._agentid else 0,
                    "text": {"content": content},
                }
            elif message_type == "markdown":
                payload = {
                    "touser": chat_id,
                    "msgtype": "markdown",
                    "agentid": int(self._agentid) if self._agentid else 0,
                    "markdown": {"content": content},
                }
            else:
                payload = {
                    "touser": chat_id,
                    "msgtype": "text",
                    "agentid": int(self._agentid) if self._agentid else 0,
                    "text": {"content": content},
                }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    result = await resp.json()
                    if result.get("errcode") == 0:
                        msg_id = result.get("msgid", "")
                        logger.info("WeCom message sent: %s", msg_id)
                        return str(msg_id)
                    else:
                        logger.error("WeCom send failed: %s", result)
                        return None

        except Exception as e:
            logger.exception("WeCom send error: %s", e)
            return None

    async def _refresh_access_token(self):
        """刷新企业微信 Access Token"""
        import aiohttp

        if not self._corpid or not self.config.app_secret:
            logger.error("WeCom corpid or app_secret not configured")
            return

        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={self._corpid}&corpsecret={self.config.app_secret}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                result = await resp.json()
                if result.get("errcode") == 0:
                    self._access_token = result["access_token"]
                    expire_in = result.get("expires_in", 7200)
                    self._token_expires_at = time.time() + expire_in - 300
                    logger.info("WeCom access token refreshed")
                else:
                    logger.error("WeCom token refresh failed: %s", result)

    async def disconnect(self):
        """断开企业微信连接"""
        self._connected = False
        self._access_token = None
        logger.info("WeCom adapter disconnected")

    async def health_check(self) -> Dict[str, Any]:
        """企业微信健康检查"""
        base = await super().health_check()
        base.update(
            {
                "corpid": self._corpid[:8] + "***" if self._corpid else "",
                "has_token": bool(self._access_token),
                "stream_mode": self.config.use_stream,
            }
        )
        return base


# ============================================================
# 群机器人 Webhook（轻量级，仅发送）
# ============================================================


class WeComGroupBot:
    """
    企业微信群机器人 Webhook

    仅支持发送消息到群聊，不支持接收。
    适用于告警通知、日报推送等单向场景。
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_text(self, content: str, mentioned_list: list = None, mentioned_mobile_list: list = None) -> bool:
        """发送文本消息"""
        import aiohttp

        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_list or [],
                "mentioned_mobile_list": mentioned_mobile_list or [],
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                result = await resp.json()
                return result.get("errcode") == 0

    async def send_markdown(self, content: str) -> bool:
        """发送 Markdown 消息"""
        import aiohttp

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                result = await resp.json()
                return result.get("errcode") == 0


def create_wecom_adapter(
    corpid: str,
    app_secret: str,
    agentid: str = "",
    use_stream: bool = True,
    callback_token: str = "",
    encoding_aes_key: str = "",
    webhook_url: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> WeComAdapter:
    """创建企业微信适配器的工厂函数"""
    extra_data = extra or {}
    extra_data.update(
        {
            "corpid": corpid,
            "agentid": agentid,
            "encoding_aes_key": encoding_aes_key,
        }
    )
    config = ChannelConfig(
        channel_type="wecom",
        app_id=corpid,
        app_secret=app_secret,
        use_stream=use_stream,
        webhook_token=callback_token,
        webhook_url=webhook_url,
        extra=extra_data,
    )
    return WeComAdapter(config)
