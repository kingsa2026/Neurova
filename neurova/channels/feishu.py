from __future__ import annotations

"""
飞书渠道适配器

支持两种接入模式:
1. Stream 模式（WebSocket 长连接）- 推荐，无需公网 IP
2. Webhook 模式 - 需要公网可访问的 URL

使用飞书官方 SDK: lark-oapi

API 参考:
- 飞书开放平台: https://open.feishu.cn
- lark-oapi PyPI: https://pypi.org/project/lark-oapi/
- 长连接文档: https://open.feishu.cn/document/event-subscription-guide/callback-subscription/step-1-choose-a-subscription-mode
"""

import asyncio
import json
from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

from neurova.channels.feishu_auth import AuthMixin, FEISHU_API_BASE
from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
)

logger = get_logger(__name__)

# 语音消息下载大小上限（P1-12 断点③）：防御异常大文件拖垮内存
_VOICE_DOWNLOAD_MAX_BYTES = 10 * 1024 * 1024


class FeishuAdapter(AuthMixin, ChannelAdapter):
    """
    飞书渠道适配器

    接入方式:
    1. 在飞书开放平台创建企业自建应用
    2. 添加机器人能力
    3. 配置权限: im:message, im:message.group_at_msg, im:message.p2p_msg
    4. 选择 Stream 模式或 Webhook 模式

    复审断链修复③: 补继承 AuthMixin——_download_media_bytes 依赖的
    tenant token 管理在此 Mixin（此前该 Mixin 与 MediaMixin 均为孤儿）。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "feishu"
        self._client = None
        self._ws_client = None
        self._event_handler = None
        # 修复 P0-4 (C3): 捕获主事件循环引用，供同步回调线程安全调度
        # 在 connect() 中捕获（此时主 loop 已运行），__init__ 中初始化为 None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self) -> bool:
        """建立飞书连接"""
        # 修复 P0-4 (C3): 捕获主 loop 引用，供 _handle_message_event 跨线程调度
        self._main_loop = asyncio.get_event_loop()
        try:
            if self.config.use_stream:
                return await self._connect_stream()
            else:
                return await self._connect_webhook()
        except Exception as e:
            logger.exception("Feishu connect error: %s", e)
            return False

    async def _connect_stream(self) -> bool:
        """Stream 模式: 通过 WebSocket 长连接接收事件"""
        try:
            import lark_oapi as lark

            # 创建事件处理器
            self._event_handler = lark.EventDispatcherHandler.builder(
                self.config.encrypt_key,
                self.config.verification_token,
            )

            # 注册消息接收事件
            self._event_handler.register_p2_im_message_receive_v1(self._handle_message_event)

            # 创建长连接客户端
            self._ws_client = lark.ws.Client(
                self.config.app_id,
                self.config.app_secret,
                event_handler=self._event_handler.build(),
                log_level=lark.LogLevel.DEBUG,
            )

            # 启动长连接（非阻塞）
            import threading

            self._ws_thread = threading.Thread(
                target=self._ws_client.start,
                daemon=True,
            )
            self._ws_thread.start()

            self._connected = True
            logger.info("Feishu Stream connected")
            return True

        except ImportError:
            logger.error("lark-oapi not installed. Run: pip install lark-oapi")
            return False
        except Exception as e:
            logger.exception("Feishu Stream connect error: %s", e)
            return False

    async def _connect_webhook(self) -> bool:
        """Webhook 模式: 需要公网 URL，在 FastAPI 中注册路由"""
        self._connected = True
        logger.info("Feishu Webhook mode configured. " f"Register webhook at: %s", self.config.webhook_url)
        return True

    def _handle_message_event(self, ctx, event):
        """处理飞书消息事件（Stream 模式回调）"""
        try:
            msg = event.event.message
            sender = event.event.sender

            # 解析消息内容
            content = ""
            if msg.message_type == "text":
                content_json = json.loads(msg.content)
                content = content_json.get("text", "")
            elif msg.message_type == "post":
                content_json = json.loads(msg.content)
                # 富文本: 提取所有 text 元素
                for lang_content in content_json.values():
                    if isinstance(lang_content, list):
                        for paragraph in lang_content:
                            if isinstance(paragraph, list):
                                for elem in paragraph:
                                    if elem.get("tag") == "text":
                                        content += elem.get("text", "")
            elif msg.message_type == "audio":
                content = "[语音]"

            # 构造统一消息
            audio_metadata: Dict[str, Any] = {}
            if msg.message_type == "audio":
                # P1-12 断点③: 下载语音字节供 voice_precheck 预转写。
                # file_key 在 content JSON；失败静默降级占位（绝不丢消息）。
                try:
                    content_json = json.loads(msg.content) if msg.content else {}
                    file_key = content_json.get("file_key", "")
                    if file_key and msg.message_id:
                        audio_data = self._download_media_bytes(msg.message_id, file_key)
                        if audio_data:
                            audio_metadata["audio_bytes"] = audio_data
                except Exception as dl_err:  # noqa: BLE001 - 下载失败降级占位
                    logger.warning("Feishu 语音下载失败，降级占位: %s", dl_err)

            channel_msg = self._make_message(
                message_id=msg.message_id or "",
                sender_id=sender.sender_id.user_id if sender.sender_id else "",
                sender_name=sender.sender_id.user_id if sender.sender_id else "",
                content=content.strip(),
                chat_id=msg.chat_id or "",
                chat_type=msg.chat_type or "p2p",
                message_type=msg.message_type or "text",
                metadata=audio_metadata,
                raw_event={
                    "header": ctx.__dict__ if hasattr(ctx, "__dict__") else {},
                    "event": event.__dict__ if hasattr(event, "__dict__") else {},
                },
            )

            # 触发事件（同步回调转异步）
            # 修复 P0-4 (C3): 用 _main_loop 引用 + run_coroutine_threadsafe 调度到主 loop
            # 原代码用 asyncio.get_event_loop() 在子线程中不可靠（Python 3.12+ 抛 RuntimeError），
            # except 分支创建新 loop 会破坏主 loop 状态且事件被调度到错误 loop
            if self._main_loop and self._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg),
                    self._main_loop,
                )
            else:
                logger.warning("Feishu: 主事件循环未运行，丢弃消息")

        except Exception as e:
            logger.exception("Feishu message handler error: %s", e)

    def _download_media_bytes(self, message_id: str, file_key: str) -> Optional[bytes]:
        """下载消息媒体文件的二进制内容（P1-12 断点③）。

        走 REST /im/v1/messages/{id}/resources/{key}（Bearer tenant token，
        响应为原始字节流——MediaMixin.download_media 的 JSON 解析版本拉不了
        二进制，故此处独立实现）。失败返回 None（调用方降级占位）。
        """
        try:
            import requests

            token = self._get_tenant_access_token()
            resp = requests.get(
                f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
                headers={"Authorization": f"Bearer {token}"},
                params={"type": "file"},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("Feishu 媒体下载 HTTP %s: msg=%s", resp.status_code, message_id)
                return None
            declared = resp.headers.get("Content-Length")
            if declared and int(declared) > _VOICE_DOWNLOAD_MAX_BYTES:
                logger.warning("Feishu 媒体超大小上限，拒收: %s bytes", declared)
                return None
            if len(resp.content) > _VOICE_DOWNLOAD_MAX_BYTES:
                logger.warning("Feishu 媒体实际字节超上限，拒收")
                return None
            return resp.content
        except Exception as e:  # noqa: BLE001 - 下载失败由调用方降级
            logger.warning("Feishu 媒体下载异常: %s", e)
            return None

    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """发送消息到飞书"""
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            if not self._client:
                self._client = (
                    lark.Client.builder().app_id(self.config.app_id).app_secret(self.config.app_secret).build()
                )

            # 构造消息内容
            if message_type == "text":
                msg_content = json.dumps({"text": content})
                receive_id_type = "chat_id"
            else:
                msg_content = content
                receive_id_type = kwargs.get("receive_id_type", "chat_id")

            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(message_type)
                .content(msg_content)
                .build()
            )

            request = CreateMessageRequest.builder().receive_id_type(receive_id_type).request_body(body).build()

            response = self._client.im.v1.message.create(request)

            if response.success():
                msg_id = response.data.message_id if response.data else None
                logger.info("Feishu message sent: %s", msg_id)
                return msg_id
            else:
                logger.error("Feishu send failed: code=%s, msg=%s", response.code, response.msg)
                return None

        except ImportError:
            logger.error("lark-oapi not installed")
            return None
        except Exception as e:
            logger.exception("Feishu send error: %s", e)
            return None

    async def disconnect(self):
        """断开飞书连接"""
        if self._ws_client:
            try:
                # lark-oapi ws client 没有显式 stop 方法
                # 线程是 daemon 的，主线程退出时自动终止
                pass
            except Exception as e:
                logger.warning("Feishu disconnect warning: %s", e)

        self._connected = False
        self._ws_client = None
        self._client = None
        logger.info("Feishu adapter disconnected")

    async def health_check(self) -> Dict[str, Any]:
        """飞书健康检查"""
        base = await super().health_check()
        base.update(
            {
                "app_id": self.config.app_id[:8] + "***" if self.config.app_id else "",
                "stream_mode": self.config.use_stream,
            }
        )
        return base

    # ============================================================
    # 验证辅助
    # ============================================================

    @staticmethod
    def verify_url_challenge(challenge: str, token: str) -> Dict[str, str]:
        """
        Webhook URL 验证

        飞书在配置 Webhook 时会发送 challenge 请求进行验证。
        """
        return {"challenge": challenge}


def create_feishu_adapter(
    app_id: str,
    app_secret: str,
    use_stream: bool = True,
    encrypt_key: str = "",
    verification_token: str = "",
    webhook_url: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> FeishuAdapter:
    """创建飞书适配器的工厂函数"""
    config = ChannelConfig(
        channel_type="feishu",
        app_id=app_id,
        app_secret=app_secret,
        use_stream=use_stream,
        encrypt_key=encrypt_key,
        verification_token=verification_token,
        webhook_url=webhook_url,
        extra=extra or {},
    )
    return FeishuAdapter(config)
