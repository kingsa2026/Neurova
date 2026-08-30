from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any, Dict

from neurova.channels import ChannelAdapter, MessageChannel

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
        self.bot_token = ""
        self._initialized = False

        self.bot_prefix = "kingsa"
        self.show_tool_messages = True
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
        return self._ensure_initialized()

    async def disconnect(self):
        self._initialized = False
        self.bot_token = ""

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
