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
import hmac
from neurova.core.logger import get_logger
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.voice_ingress import (
    AUDIO_BYTES_KEY,
    INBOUND_VOICE_PLACEHOLDER,
    INBOUND_VOICE_TYPES,
    VOICE_DOWNLOAD_MAX_BYTES,
)

logger = get_logger(__name__)

# 回调 XML 请求体大小上限（防实体扩展/资源耗尽；企微消息体远小于此值）
_MAX_XML_BODY_SIZE = 64 * 1024

WECOM_API_BASE = "https://qyapi.weixin.qq.com"
#: 素材取回接口——全仓唯一实装在那份 `fetchWecomMediaBytes` 里（教义第 6 条）。
MEDIA_GET_PATH = "/cgi-bin/media/get"


def fetchWecomMediaBytes(accessToken: str, mediaId: str, *,
                         maxBytes: int = VOICE_DOWNLOAD_MAX_BYTES,
                         timeoutSeconds: int = 10):
    """按 `media_id` 取回企业微信素材字节；取不到就返回 None，绝不谎报有内容。

    两道大小上限（声明长度 + 实际字节）照 `voice_ingress.VOICE_DOWNLOAD_MAX_BYTES` 的口径：
    声明已超限就不再读 body，免得为一个注定拒收的大响应把整段读进来。
    平台出错时该接口回的是 JSON 错误体——那不能当音频字节交给预检去转写。

    这是同步 HTTP（`requests` 是可选依赖，缺了就点名不装、不静默成功）。在事件循环里调它的
    那一条路必须走线程池（见 `WeComAdapter.downloadVoiceBytes`）——§6-185 为同一件事踩过一次。
    """
    try:
        import requests
    except ImportError:
        logger.warning("企业微信素材未取: requests 未安装")
        return None

    if not accessToken or not mediaId:
        logger.warning("企业微信素材未取: 缺 access_token 或 media_id")
        return None

    try:
        resp = requests.get(
            f"{WECOM_API_BASE}{MEDIA_GET_PATH}",
            params={"access_token": accessToken, "media_id": mediaId},
            timeout=timeoutSeconds,
            stream=True,
        )
        if getattr(resp, "status_code", 200) >= 400:
            logger.warning("企业微信素材下载 HTTP %s: media_id=%s",
                           resp.status_code, mediaId)
            return None
        contentType = resp.headers.get("Content-Type", "") or ""
        if "application/json" in contentType:
            logger.error("企业微信素材下载失败（平台回的是 JSON 错误体）: media_id=%s", mediaId)
            return None
        declared = resp.headers.get("Content-Length")
        try:
            declaredBytes = int(declared) if declared else None
        except (TypeError, ValueError):
            declaredBytes = None
        if declaredBytes is not None and declaredBytes > maxBytes:
            logger.warning("企业微信素材超大小上限，拒收: declared=%s max=%s",
                           declaredBytes, maxBytes)
            return None
        data = resp.content
        if len(data) > maxBytes:
            logger.warning("企业微信素材实际字节超上限，拒收: %s > %s", len(data), maxBytes)
            return None
        return data
    except Exception as e:  # noqa: BLE001 - 取不到字节就退回占位，绝不阻断入站
        logger.warning("企业微信素材下载异常: media_id=%s err=%s", mediaId, e)
        return None



def _wecom_callback_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """企业微信官方回调签名公式（文档 90968 加解密方案）:

        msg_signature = SHA1(sort(token, timestamp, nonce, msg_encrypt))

    SHA1 为平台强制互操作算法（非本实现的安全选择）；
    明文模式回调体无 Encrypt 字段时，encrypt 传空串（等价于三元组拼接结果）。
    """
    raw = "".join(sorted([token, timestamp, nonce, encrypt]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


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
        # 修复 P0-6 (C5): 捕获主事件循环引用，供同步回调线程安全调度
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # B4-b（#7208/#7001 对齐）：群聊会话共享开关（manager.resolve_session_scope_id
        # 消费）；False=群内按发送者隔离会话。bool 或 "true"/"false" 字符串。
        _cfg_meta = getattr(config, "metadata", None) or getattr(config, "extra", {}) or {}
        # 双键兼容：旧前端写 group_share_session，新契约统一 share_session_in_group
        _share = _cfg_meta.get(
            "share_session_in_group",
            _cfg_meta.get("group_share_session", True),
        )
        self.share_session_in_group = (
            _share.strip().lower() not in ("false", "0", "no", "off")
            if isinstance(_share, str) else bool(_share)
        )

    async def connect(self) -> bool:
        """建立企业微信连接"""
        # 修复 P0-6 (C5): 捕获主 loop 引用，供 handle_callback 跨线程调度
        self._main_loop = asyncio.get_event_loop()
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
        WebSocket 长连接模式（智能机器人 AI Bot）

        官方接入规范（文档 101039/101463）:
        - 管理后台智能机器人配置页开启"API 模式-长连接"，获取 BotID + Secret
          （与回调模式的 Token/EncodingAESKey 是两套凭证，两种模式互斥）
        - 连接 wss://openws.work.weixin.qq.com 后发送 aibot_subscribe 订阅
        - 接收 aibot_msg_callback（消息）/ aibot_event_callback（事件），
          用 aibot_respond_msg 回复；每 30 秒心跳 ping；
          单机器人仅允许 1 条有效长连接
        - 官方 SDK: PyPI `wecom-aibot-python-sdk`（推荐直接使用）

        本适配器当前仅覆盖 token 获取与回调验签；长连接协议实现见官方 SDK。
        """
        try:
            # 获取 access_token 验证凭证有效性（长连接凭证为 BotID+Secret，
            # 若配置了 corpid/app_secret 则可先行验证自建应用凭证）
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
            # 解析 XML: 回调 URL 公网可达，需防实体扩展攻击（拒绝 DOCTYPE/ENTITY 并限制大小）
            if len(xml_data) > _MAX_XML_BODY_SIZE:
                logger.warning("WeCom callback rejected: body too large (%d bytes)", len(xml_data))
                return None
            if "<!doctype" in xml_data[:1024].lower() or "<!entity" in xml_data[:1024].lower():
                logger.warning("WeCom callback rejected: DOCTYPE/ENTITY not allowed")
                return None
            root = ET.fromstring(xml_data)
            encrypt = root.findtext("Encrypt", "") or ""

            # 签名核对只在 `verifyCallbackSignature` 一处（含"无回调密钥即拒"那条 fail-closed，
            # BUG AUDIT C-09）——这里只决定"拒了之后回什么"，不重复判一次。
            try:
                self.verifyCallbackSignature(msg_signature, timestamp, nonce, encrypt)
            except ValueError as e:
                logger.warning("%s", e)
                return None

            to_user_name = root.findtext("ToUserName", "")
            from_user = root.findtext("FromUserName", "")
            create_time = root.findtext("CreateTime", "")
            msg_type = root.findtext("MsgType", "text")
            content = root.findtext("Content", "").strip()
            # 语音的正文不在 `<Content>`：企业微信把平台侧转写结果放在 `<Recognition>`
            # （需企业在后台开通语音识别），按 `<Content>` 读恒得空串——用户发语音等于发了句
            # 不存在的话。取不到转写时退回共享占位，与 ilink/aibot 两条活路同一口径。
            recognition = ""
            mediaId = ""
            if msg_type in INBOUND_VOICE_TYPES:
                recognition = (root.findtext("Recognition", "") or "").strip()
                mediaId = (root.findtext("MediaId", "") or "").strip()
                content = recognition or INBOUND_VOICE_PLACEHOLDER
            msg_id = root.findtext("MsgId", "")
            # 群聊：企业微信回调群消息带 <ChatId>；此前硬编码 p2p → 群消息会话键
            # 退化成发送者、无法按群绑定/回复。
            chat_id = root.findtext("ChatId", "") or ""
            is_group = bool(chat_id)

            # 构造统一消息
            channel_msg = self._make_message(
                message_id=msg_id or f"wecom_{create_time}",
                sender_id=from_user,
                sender_name=from_user,  # 企业微信回调中没有发送者昵称
                content=content,
                chat_id=chat_id or from_user,  # 群用 ChatId，单聊以 user id 为会话 ID
                chat_type="group" if is_group else "p2p",
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
            # 修复 P0-6 (C5): 用 _main_loop 引用 + run_coroutine_threadsafe 调度到主 loop
            # 原代码用 asyncio.get_event_loop() 在子线程中不可靠，except 分支创建新 loop 破坏主 loop
            if self._main_loop and self._main_loop.is_running():
                # 平台没转写而只给了 `<MediaId>` 时，先把素材取回来再投——`voice_precheck` 读的
                # 就是 `metadata["audio_bytes"]`，不取这条语音在本仓没有任何东西能转写它。
                # 两条分支都**只投一次**（同一句话进两次回合是比迟一秒更坏的错误）。
                if mediaId and not recognition:
                    pending = self._deliverVoiceWithBytes(channel_msg, mediaId)
                else:
                    pending = self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
                asyncio.run_coroutine_threadsafe(pending, self._main_loop)
            else:
                logger.warning("WeCom: 主事件循环未运行，丢弃消息")

            # 被动回复（示例: 回复文本）
            return self._build_reply_xml(from_user, to_user_name, "收到您的消息，正在处理中...")

        except Exception as e:
            logger.exception("WeCom callback error: %s", e)
            return None

    async def downloadVoiceBytes(self, mediaId: str):
        """取一条语音素材的字节——同步 HTTP 走线程池，别在事件循环里阻塞全进程入站（§6-185 同形）。"""
        if not self._access_token or time.time() > self._token_expires_at:
            await self._refresh_access_token()
        if not self._access_token:
            logger.warning("WeCom 语音素材未取: access_token 不可用")
            return None
        return await asyncio.to_thread(fetchWecomMediaBytes, self._access_token, mediaId)

    async def _deliverVoiceWithBytes(self, message: ChannelMessage, mediaId: str) -> None:
        """取字节 → 挂进预检读的那个键 → 投递；取不到就带着共享占位照常投，绝不丢消息。"""
        audioBytes = await self.downloadVoiceBytes(mediaId)
        if audioBytes:
            if message.metadata is None:
                message.metadata = {}
            message.metadata[AUDIO_BYTES_KEY] = audioBytes
        else:
            logger.info("WeCom 语音素材没取到，按占位投递: media_id=%s", mediaId)
        await self._emit_event(ChannelEventType.MESSAGE_RECEIVED, message)

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

    def verifyCallbackSignature(self, msg_signature: str, timestamp: str, nonce: str,
                               encrypt: str) -> None:
        """企业微信回调签名的**唯一核对处**：不通过就抛 ValueError，未配密钥一律拒（fail-closed）。

        分成一个方法而不是埋在 `handle_callback` 里，是因为入站回调现在要拿它**选实例**
        （§6-197：同类型多只实例时，逐只问"这条回调在你自己的凭据下验得通吗"）——
        选实例与投递必须过同一道门，两处各写一遍公式就会在其中一处放宽。
        """
        if not self._callback_token:
            raise ValueError("WeCom callback rejected: callback token not configured (fail-closed)")
        expected = _wecom_callback_signature(self._callback_token, timestamp, nonce, encrypt)
        if not msg_signature or not hmac.compare_digest(expected, msg_signature):
            raise ValueError("WeCom callback rejected: msg_signature mismatch")

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """
        URL 验证（企业微信回调配置时使用）

        官方规范（文档 90968）: GET 验证请求的 msg_signature 为
        SHA1(sort(token, timestamp, nonce, echostr))，第 4 元为 URL 上
        的加密 echostr 密文。验证通过后完整实现应解密 echostr 并返回
        明文（需 EncodingAESKey 的 AES-CBC 解密）；当前返回密文原文。

        这一支在**未配 token 时按既有语义放行**（握手只把对方给的 echostr 原样回给它自己，
        不产生投递）——与事件回调那支的 fail-closed 不同，属另一次收紧的范围，记在 §6-197 本格。
        """
        if self._callback_token:
            self.verifyCallbackSignature(msg_signature, timestamp, nonce, echostr)
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
                # 群回复@提问者：官方 text.mentioned_list（成员 userid 列表，"@all" 全员）。
                # at_user_id/chat_type 由 manager._dispatch_message 回发注入。
                at_uid = kwargs.get("at_user_id") or ""
                if kwargs.get("chat_type") == "group" and at_uid:
                    payload["text"]["mentioned_list"] = [str(at_uid)]
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
