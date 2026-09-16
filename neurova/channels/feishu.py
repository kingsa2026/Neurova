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
import hmac
import inspect
import json
from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

from neurova.channels.feishu_auth import AuthMixin
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

# 'feishu'（国内）/'lark'
# （国际）或完整 http 网关 URL。此前前端有 region 字段而后端从不消费
# ——Lark 国际租户恒认证失败（摆设字段根修）
        _domain = str(_cfg_meta.get("domain", "feishu") or "feishu")
        if _domain in ("feishu", "lark"):
            _open_base = "https://open.larksuite.com" if _domain == "lark" else "https://open.feishu.cn"
        elif _domain.startswith(("http://", "https://")):
            _open_base = _domain.rstrip("/")
        else:
            _open_base = "https://open.feishu.cn"
        self.domain = "lark" if _open_base == "https://open.larksuite.com" else _domain
        self.open_base = _open_base
        self.api_base = f"{_open_base}/open-apis"

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
        """Stream 模式: 通过 WebSocket 长连接接收事件

        启动慢根修（2026-09-16）：旧实现在协程体内 `import lark_oapi`（全套 protobuf
        生成代码，热缓存实测 3.5s+/冷盘更久）并同步构造 handler/ws.Client——协程在
        main loop 线程上没有让出点，把 /health 就绪饿死 6.7s（bootstrap 的"后台化"
        只是 create_task，仍在同一 loop 上）。现在 import/构造/ws 循环全部搬进长连接
        专属线程，connect 只在线程外 await 构造结果；构造失败仍如实返回 False，
        错误语义不降级。
        """
        import threading

        setup_done = threading.Event()
        setup_ok: list = []
        # 构造窗口（秒级）内 disconnect/restart 的取消位：旧实现构造同步完成、
        # 无并发窗口；线程化后必须显式取消，否则 disconnect 置空 _ws_client 后
        # 线程仍可能 start() 出无人引用的僵尸长连接。
        cancel = self._setup_cancel = threading.Event()

        def _stream_session():
            # 历史教训（飞书收不到消息根因，保持）：lark_oapi.ws.client 在模块导入期
            # 就把全局 `loop` 绑成 asyncio.get_event_loop()，若在 main loop 里先导入，
            # client.start() 用 run_until_complete 落到已运行的主循环 → 线程秒崩。
            # 本函数先建独立循环设为当前，lark 导入在本线程内发生；重绑保留，
            # 防 lark 已被他人提前导入的情况。
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                try:
                    import lark_oapi as lark
                    import lark_oapi.ws.client as _lark_ws

                    _lark_ws.loop = loop
                    # 创建事件处理器
                    self._event_handler = lark.EventDispatcherHandler.builder(
                        self.config.encrypt_key,
                        self.config.verification_token,
                    )
                    # 注册消息接收事件
                    self._event_handler.register_p2_im_message_receive_v1(
                        self._handle_message_event)
                    # 注册"机器人被移出群"事件 → CHAT_BOT_REMOVED（会话归档，阶段4）
                    try:
                        self._event_handler.register_p2_im_chat_member_bot_deleted_v1(
                            self._handle_bot_removed_event)
                    except (AttributeError, Exception) as e:  # noqa: BLE001 - 老 SDK 无此注册器则跳过
                        logger.debug("飞书未支持 bot_deleted 事件注册: %s", e)
                    # 创建长连接客户端（domain 随 feishu/lark 切换——官方多站点要求）
                    self._ws_client = lark.ws.Client(
                        self.config.app_id,
                        self.config.app_secret,
                        event_handler=self._event_handler.build(),
                        log_level=lark.LogLevel.DEBUG,
                        domain=self.open_base,
                    )
                except ImportError:
                    logger.error("lark-oapi not installed. Run: pip install lark-oapi")
                except Exception as e:  # noqa: BLE001 - 构造失败 = 连接失败，如实上报
                    logger.exception("Feishu Stream connect error: %s", e)
                else:
                    setup_ok.append(True)
                    self._connected = True
                    logger.info("Feishu Stream connected")
            finally:
                setup_done.set()
            if cancel.is_set():  # 构造期间 disconnect/restart 已发生：本次构造作废
                setup_ok.clear()
                self._connected = False
                return
            try:
                self._ws_client.start()  # 阻塞式跑 ws 循环（start 内部用本线程 loop）
            except Exception as e:  # noqa: BLE001 - 线程内失败仅记日志
                logger.exception("Feishu ws thread failed: %s", e)

        self._ws_thread = threading.Thread(
            target=_stream_session,
            daemon=True,
        )
        self._ws_thread.start()
        # 线程外等待构造结果：等待窗口内 main loop 空闲（/health 可正常服务）
        await asyncio.to_thread(setup_done.wait, 30)
        return bool(setup_ok)

    async def _connect_webhook(self) -> bool:
        """Webhook 模式: 需要公网 URL，在 FastAPI 中注册路由"""
        self._connected = True
        logger.info("Feishu Webhook mode configured. " f"Register webhook at: %s", self.config.webhook_url)
        return True

    def _handle_message_event(self, event):
        """处理飞书消息事件（Stream 模式回调）。

        lark-oapi 的 P2ImMessageReceiveV1Processor.do 以 self.f(data) 单参数调用
        （data: P2ImMessageReceiveV1，其 .event 为 P2ImMessageReceiveV1Data）。
        此前签名多一个 ctx 形参 → data 绑到 ctx、event 缺参 TypeError 被 SDK 吞掉，
        收消息静默丢弃（"飞书发消息无响应"根因）。
        """
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

            # 外部用户 user_id 常为 null（只有 open_id/union_id）——回退取，否则
            # sender_id 空 → ChannelRouter 的 user_id 落到带冒号的回退值，且记忆隔离失效。
            _sid = sender.sender_id if sender else None
            _sender_id = ((_sid.user_id or _sid.open_id or _sid.union_id) if _sid else "") or ""

            # 解析 @提及：msg.mentions=[{key:"@_user_1", id:{open_id..}, name}]。
            # 1) 结构化进 metadata.mentions 供 ChannelRouter require_mention 判定；
            # 2) 把正文里的 "@_user_N" 占位符替换为可读 "@昵称"，避免污染 agent 输入。
            mentions: list = []
            for m in (getattr(msg, "mentions", None) or []):
                mid = getattr(m, "id", None)
                mentions.append({
                    "key": getattr(m, "key", "") or "",
                    "name": getattr(m, "name", "") or "",
                    "open_id": getattr(mid, "open_id", "") if mid else "",
                    "user_id": getattr(mid, "user_id", "") if mid else "",
                })
            content_out = content.strip()
            for mm in mentions:
                if mm["key"]:
                    content_out = content_out.replace(mm["key"], f"@{mm['name'] or mm['key']}")
            if mentions:
                audio_metadata["mentions"] = mentions

            channel_msg = self._make_message(
                message_id=msg.message_id or "",
                sender_id=_sender_id,
                sender_name=_sender_id,
                content=content_out,
                chat_id=msg.chat_id or "",
                chat_type=msg.chat_type or "p2p",
                message_type=msg.message_type or "text",
                metadata=audio_metadata,
                raw_event={
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

    def _handle_bot_removed_event(self, event):
        """机器人被移出群 → 发 CHAT_BOT_REMOVED（manager/ChannelRouter 据此归档会话）。"""
        try:
            chat_id = ""
            ev = getattr(event, "event", None)
            if ev is not None:
                chat_id = getattr(ev, "chat_id", "") or ""
            if not chat_id:
                return
            channel_msg = self._make_message(
                message_id="", sender_id="", sender_name="", content="",
                chat_id=chat_id, chat_type="group", message_type="event",
            )
            if self._main_loop and self._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._emit_event(ChannelEventType.CHAT_BOT_REMOVED, channel_msg),
                    self._main_loop,
                )
        except Exception as e:  # noqa: BLE001 - 事件旁路失败不影响主链路
            logger.warning("飞书 bot_removed 事件处理异常: %s", e)

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
                f"{self.api_base}/im/v1/messages/{message_id}/resources/{file_key}",
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
                    lark.Client.builder().app_id(self.config.app_id).app_secret(self.config.app_secret).domain(self.open_base).build()
                )

            # 构造消息内容
            if message_type == "text":
                # 群聊回复@提问者（飞书 text 内联 <at user_id="ou_x"></at>）；
                # at_user_id/chat_type 由 manager._dispatch_message 回发注入。
                at_uid = kwargs.get("at_user_id") or ""
                if kwargs.get("chat_type") == "group" and at_uid:
                    content = f'<at user_id="{at_uid}"></at> {content}'
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

            # P1-6: lark 默认同步 Client（requests 实现），直调会阻塞事件循环
            # 一次 HTTPS 往返——下沉到工作线程执行
            response = await asyncio.to_thread(self._client.im.v1.message.create, request)

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
        """断开飞书连接（幂等）"""
        # 构造窗口内到达的 disconnect：先置取消位，让 _stream_session 线程
        # 放弃 start()（防僵尸长连接），再走常规停连接路径
        c = getattr(self, "_setup_cancel", None)
        if c is not None:
            c.set()
        # C-13: 真正关闭长连接——SDK 版本差异安全探测 stop/close
        # （当前 lark-oapi ws Client 无公开 stop API，探测到即调用，
        # awaitable 结果在主 loop 上等待）
        client = self._ws_client
        if client is not None:
            stopper = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stopper):
                try:
                    result = stopper()
                    if inspect.isawaitable(result):
                        await result
                except Exception as e:
                    logger.warning("Feishu disconnect stop warning: %s", e)

        # C-13: join 长连接线程（daemon 线程，超时不强杀）
        thread = getattr(self, "_ws_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("Feishu ws thread alive after 5s (daemon, not force-killed)")
        self._ws_thread = None
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

    def verify_url_challenge(self, challenge: str, token: str) -> Dict[str, str]:
        """
        Webhook URL 验证

        飞书在配置 Webhook 时会发送 challenge 请求进行验证。

        C-23: 必须与配置的 verification_token 比对（恒定时间比较）；
        未配置 token 时 fail-closed（拒绝挑战，与 wecom/telegram 口径一致）。
        """
        expected = self.config.verification_token or ""
        if not expected or not token or not hmac.compare_digest(token, expected):
            raise ValueError(
                "Feishu URL verification rejected: token missing or mismatched (fail-closed)"
            )
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
