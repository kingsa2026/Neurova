from __future__ import annotations

import asyncio
import threading

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

from neurova.channels import ChannelAdapter, ChannelConfig, MessageChannel
from neurova.channels.base import ChannelEventType, ChannelMessage

from neurova.channels.telegram_api_client import TelegramAPIMixin
from neurova.channels.telegram_sender import TelegramSenderMixin
from neurova.channels.telegram_parser import TelegramParserMixin
from neurova.channels.telegram_commands import TelegramCommandMixin
from neurova.channels.telegram_webhook import TelegramWebhookMixin
from neurova.channels.telegram_chat_management import TelegramChatManagementMixin
from neurova.channels.telegram_message_management import TelegramMessageManagementMixin
from neurova.channels.telegram_ai_generation import TelegramAIGenerationMixin

logger = get_logger(__name__)

try:
    import requests  # type: ignore[import-not-found]
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class TelegramAdapter(
    TelegramAPIMixin,
    TelegramSenderMixin,
    TelegramParserMixin,
    TelegramCommandMixin,
    TelegramWebhookMixin,
    TelegramChatManagementMixin,
    TelegramMessageManagementMixin,
    TelegramAIGenerationMixin,
    ChannelAdapter,
):
    """Telegram channel adapter — slim core composing 8 mixins."""

    API_BASE = "https://api.telegram.org"

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.TELEGRAM

    def __init__(self):
        # BUG AUDIT C-03: 此前未调用 super().__init__(config)，导致
        # register_adapter() 读取 adapter.channel_type / adapter.config 时
        # AttributeError: 'TelegramAdapter' object has no attribute 'config'。
        super().__init__(ChannelConfig(channel_type="telegram"))
        self.bot_token = ""
        self._initialized = False

        self.bot_prefix = "kingsa"
        self.show_tool_messages = True
        self.share_session_in_group = True
        self.show_thinking = True
        self.http_proxy = ""
        self.http_proxy_auth = ""
        self.show_typing = False
        # Bot API 10.x: MarkdownV2/HTML 为完整支持模式，"Markdown" 为官方
        # 保留的向后兼容 legacy 模式（解析失败时自动回退纯文本重发）
        self.parse_mode = "Markdown"
        self.private_chat_strategy = "open"
        self.group_chat_strategy = "open"
        self.require_mention = False
        self.whitelist_users: list = []
        self._proxies = None

        self._last_update_id = 0
        self._polling_timeout = 30
        self._polling_limit = 100
        # getUpdates 长轮询后台线程状态（connect 时启动）
        self._poll_thread: Optional[Any] = None
        self._stop_event = threading.Event()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        self._webhook_url = ""
        self._webhook_secret = ""

        self._bot_info: Dict[str, Any] = {}
        self._bot_username = ""

        self._command_handlers: Dict[str, Any] = {}

        self._register_default_commands()

    def authenticate(self, config: Dict[str, str]) -> bool:
        self.bot_token = config.get("bot_token", "")
        if not self.bot_token:
            logger.error("Telegram 认证失败: bot_token 不能为空")
            return False

        self.bot_prefix = config.get("bot_prefix", "kingsa")
        # B4-b（#7208/#7001 对齐）：群聊会话共享开关（manager 消费）
        self.share_session_in_group = str(
            config.get("share_session_in_group", config.get("group_share_session", "true"))
        ).lower() == "true"
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"
        self.http_proxy = config.get("http_proxy", "")
        self.http_proxy_auth = config.get("http_proxy_auth", "")
        self.show_typing = config.get("show_typing", "false").lower() == "true"
        self.parse_mode = config.get("parse_mode", self.parse_mode)
        self.private_chat_strategy = config.get("private_chat_strategy", "open")
        self.group_chat_strategy = config.get("group_chat_strategy", "open")
        self.require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist = config.get("whitelist_users", "")
        if whitelist:
            self.whitelist_users = [u.strip() for u in whitelist.split(",") if u.strip()]

        self._setup_proxy()
        return self._verify_token()

    def _setup_proxy(self):
        if not self.http_proxy:
            self._proxies = None
            return

        if self.http_proxy_auth:
            parts = self.http_proxy.split("://", 1)
            if len(parts) == 2:
                protocol, url = parts
                self._proxies = {
                    "http": f"{protocol}://{self.http_proxy_auth}@{url}",
                    "https": f"{protocol}://{self.http_proxy_auth}@{url}",
                }
        else:
            self._proxies = {
                "http": self.http_proxy,
                "https": self.http_proxy,
            }
        logger.info("Telegram 代理已设置: %s", self.http_proxy)

    def _verify_token(self) -> bool:
        if not REQUESTS_AVAILABLE:
            self._initialized = True
            return True

        try:
            data = self._api_request("GET", f"/bot{self.bot_token}/getMe")
            if data.get("ok"):
                self._initialized = True
                bot_info = data.get("result", {})
                self._bot_info = bot_info
                self._bot_username = bot_info.get("username", "")
                logger.info("Telegram 认证成功: @%s", self._bot_username)
                return True
            logger.error("Telegram 认证失败: %s", data)
            return False
        except Exception as e:
            logger.error("Telegram 认证异常: %s", e)
            return False

    def _ensure_initialized(self) -> bool:
        if not self._initialized:
            return self._verify_token()
        return True

    def get_bot_info(self) -> Dict:
        return self._bot_info

    def get_channel_config(self) -> Dict[str, Any]:
        return {
            "channel": self.channel.value,
            "bot_prefix": self.bot_prefix,
            "bot_username": self._bot_username,
            "show_tool_messages": self.show_tool_messages,
            "show_thinking": self.show_thinking,
            "http_proxy": self.http_proxy,
            "show_typing": self.show_typing,
            "private_chat_strategy": self.private_chat_strategy,
            "group_chat_strategy": self.group_chat_strategy,
            "require_mention": self.require_mention,
            "whitelist_users": self.whitelist_users,
            "webhook_url": self._webhook_url,
            "authenticated": self._initialized,
        }

    def update_config(self, config: Dict[str, Any]) -> None:
        if "bot_prefix" in config:
            self.bot_prefix = config["bot_prefix"]
        if "show_tool_messages" in config:
            self.show_tool_messages = config["show_tool_messages"]
        if "show_thinking" in config:
            self.show_thinking = config["show_thinking"]
        if "http_proxy" in config:
            self.http_proxy = config["http_proxy"]
            self._setup_proxy()
        if "http_proxy_auth" in config:
            self.http_proxy_auth = config["http_proxy_auth"]
            self._setup_proxy()
        if "show_typing" in config:
            self.show_typing = config["show_typing"]
        if "parse_mode" in config:
            self.parse_mode = config["parse_mode"]
        if "private_chat_strategy" in config:
            self.private_chat_strategy = config["private_chat_strategy"]
        if "group_chat_strategy" in config:
            self.group_chat_strategy = config["group_chat_strategy"]
        if "require_mention" in config:
            self.require_mention = config["require_mention"]
        if "whitelist_users" in config:
            self.whitelist_users = config["whitelist_users"]

    def reset_polling_offset(self):
        self._last_update_id = 0

    async def connect(self) -> bool:
        """getMe 校验 + 启动 getUpdates 长轮询后台线程（此前只 getMe、无接收回路
        → Telegram 收不到任何消息）。"""
        if not self._ensure_initialized():
            return False
        self._main_loop = asyncio.get_running_loop()
        self._stop_event = threading.Event()
        if not (self._poll_thread and self._poll_thread.is_alive()):
            self._poll_thread = threading.Thread(target=self._run_poll_forever, daemon=True,
                                                 name="telegram-poll")
            self._poll_thread.start()
        self._connected = True
        logger.info("Telegram 已连接，getUpdates 轮询启动")
        return True

    async def disconnect(self):
        self._connected = False
        ev = getattr(self, "_stop_event", None)
        if ev is not None:
            ev.set()
        t = getattr(self, "_poll_thread", None)
        if t is not None and t.is_alive():
            t.join(timeout=5)
        self._poll_thread = None
        self._initialized = False
        self.bot_token = ""

    def _run_poll_forever(self) -> None:
        """后台线程：同步 requests.getUpdates 长轮询，逐条解析回投主事件循环。"""
        offset = self._last_update_id
        while not getattr(self, "_stop_event", threading.Event()).is_set():
            try:
                resp = self._api_request(
                    "GET", f"/bot{self.bot_token}/getUpdates",
                    params={"offset": offset, "timeout": self._polling_timeout,
                            "limit": self._polling_limit,
                            "allowed_updates": ["message", "edited_message",
                                                 "my_chat_member", "channel_post"]},
                )
                if not resp.get("ok"):
                    threading.Event().wait(3)  # 退避（不持有 GIL 长时）
                    continue
                for upd in resp.get("result") or []:
                    uid = upd.get("update_id")
                    if isinstance(uid, int):
                        offset = max(offset, uid + 1)
                        self._last_update_id = offset
                    self._process_update(upd)
            except Exception as e:  # noqa: BLE001 - 轮询异常退避重试，绝不退出线程
                logger.warning("Telegram 轮询异常，3s 后重试: %s", e)
                threading.Event().wait(3)

    def _process_update(self, upd: Dict[str, Any]) -> None:
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post")
        if not msg:
            # my_chat_member：机器人被移出群 → CHAT_BOT_REMOVED
            mcm = upd.get("my_chat_member")
            if mcm:
                self._handle_my_chat_member(mcm)
            return
        if not self.should_process_message(upd):
            return
        chat = msg.get("chat", {})
        sender = msg.get("from", {}) or {}
        chat_id = str(chat.get("id", ""))
        ctype = chat.get("type", "")
        chat_type = "p2p" if ctype == "private" else "group"
        text = msg.get("text") or msg.get("caption") or ""
        mentions = [e for e in (msg.get("entities") or []) if e.get("type") == "mention"]
        channel_msg = self._make_message(
            message_id=str(msg.get("message_id", "")),
            sender_id=str(sender.get("id", "")),
            sender_name=sender.get("username") or sender.get("first_name", "") or str(sender.get("id", "")),
            content=text.strip(),
            chat_id=chat_id,
            chat_type=chat_type,
            message_type="text",
            metadata={"mentions": mentions} if mentions else {},
            raw_event=msg,
        )
        if self._main_loop is not None and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg), self._main_loop)

    def _handle_my_chat_member(self, mcm: Dict[str, Any]) -> None:
        """机器人被移出群（my_chat_member new_status=kicked/left）→ CHAT_BOT_REMOVED。"""
        new = (mcm.get("new_chat_member") or {})
        if new.get("status") not in ("kicked", "left"):
            return
        chat_id = str((mcm.get("chat") or {}).get("id", ""))
        if not chat_id:
            return
        msg = self._make_message(message_id="", sender_id="", sender_name="", content="",
                                 chat_id=chat_id, chat_type="group", message_type="event")
        if self._main_loop is not None and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._emit_event(ChannelEventType.CHAT_BOT_REMOVED, msg), self._main_loop)

    async def send_message(self, chat_id: str, content: str,
                           message_type: str = "text", **kwargs) -> Optional[str]:
        """base 契约异步发送（覆盖 TelegramSenderMixin 的旧 sync(UnifiedMessage) 签名，
        此前 manager 按 base 契约调用 → 不可 await/TypeError 被吞 → 无法回发）。"""
        if not self._ensure_initialized():
            return None
        try:
            if message_type == "image" and kwargs.get("image_path"):
                ok = self._send_photo(str(chat_id), kwargs["image_path"])
                return "sent" if ok else None
            resp = self._send_text_message(str(chat_id), content)
            if isinstance(resp, dict) and resp.get("ok"):
                mid = (resp.get("result") or {}).get("message_id")
                return str(mid) if mid else "sent"
            if resp is True:
                return "sent"
            logger.warning("Telegram 发送失败: %s", resp)
            return None
        except Exception as e:  # noqa: BLE001
            logger.exception("Telegram 发送异常: %s", e)
            return None


    def should_process_message(self, raw_data: Dict) -> bool:
        msg = raw_data.get("message") or raw_data.get("edited_message") or {}
        if not msg:
            return False

        chat = msg.get("chat", {})
        chat_type = chat.get("type", "")
        sender_id = str(msg.get("from", {}).get("id", ""))

        if chat_type == "private":
            if self.private_chat_strategy == "closed":
                return False
            elif self.private_chat_strategy == "whitelist":
                return sender_id in self.whitelist_users
            return True

        if chat_type in ("group", "supergroup"):
            if self.group_chat_strategy == "closed":
                return False
            elif self.group_chat_strategy == "whitelist":
                return sender_id in self.whitelist_users
            if self.require_mention:
                text = msg.get("text", "")
                entities = msg.get("entities", [])
                return self._check_mention(text, entities)
            return True

        return True


def create_telegram_adapter(bot_token: str = "", **kwargs) -> TelegramAdapter:
    adapter = TelegramAdapter()
    if bot_token:
        config = {"bot_token": bot_token, **kwargs}
        adapter.authenticate(config)
    return adapter
