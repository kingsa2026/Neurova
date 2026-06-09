"""
Telegram 消息渠道适配器

API 文档: https://core.telegram.org/bots/api

功能特性:
1. 完整 Bot API 身份验证
2. Webhook 和长轮询两种消息接收模式
3. 消息发送 (文本、图片、语音、视频、文件、位置、卡片)
4. 命令处理 (自动解析 /command)
5. 用户信息获取和管理
6. 完整的错误处理与日志
7. 群聊策略和白名单控制
"""

import json
import logging
import time
import tempfile
import os
import re
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime

try:
    import requests  # type: ignore[import-not-found]
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("requests 库未安装，Telegram 适配器将使用模拟模式")

try:
    import httpx  # type: ignore[import-not-found]
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logging.warning("httpx 库未安装，部分AI生成功能可能不可用")

from neurova.channels import (
    ChannelAdapter, MessageChannel, UnifiedMessage, ContentType
)

class TelegramAdapter(ChannelAdapter):
    """
    Telegram 消息渠道适配器

    配置项:
    - bot_token: Bot Token (必填)
    - bot_prefix: 机器人前缀 (默认 kingsa)
    - show_tool_messages: 显示工具消息
    - show_thinking: 显示思考过程
    - http_proxy: HTTP 代理地址
    - http_proxy_auth: HTTP 代理认证 (user:password)
    - show_typing: 显示正在输入状态
    - private_chat_strategy: 私聊策略 (open/closed/whitelist)
    - group_chat_strategy: 群聊策略 (open/closed/whitelist)
    - require_mention: 需要@提及
    - whitelist_users: 白名单用户列表
    """

    API_BASE = "https://api.telegram.org"

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.TELEGRAM

    def __init__(self):
        self.bot_token = ""
        self._initialized = False

        # 渠道配置
        self.bot_prefix = "kingsa"
        self.show_tool_messages = True
        self.show_thinking = True
        self.http_proxy = ""
        self.http_proxy_auth = ""
        self.show_typing = False
        self.private_chat_strategy = "open"
        self.group_chat_strategy = "open"
        self.require_mention = False
        self.whitelist_users: list = []
        self._proxies = None

        # 长轮询配置
        self._last_update_id = 0
        self._polling_timeout = 30
        self._polling_limit = 100

        # Webhook 配置
        self._webhook_url = ""
        self._webhook_secret = ""

        # Bot 信息缓存
        self._bot_info: Dict[str, Any] = {}
        self._bot_username = ""

        # 命令处理器注册表
        self._command_handlers: Dict[str, Callable] = {}

        # 注册默认命令
        self._register_default_commands()

    def _register_default_commands(self):
        """注册默认命令处理器"""
        self._command_handlers["start"] = self._handle_start
        self._command_handlers["help"] = self._handle_help

    def register_command_handler(self, command: str, handler: Callable):
        """
        注册命令处理器

        参数:
        command: 命令名称 (不带 /)
        handler: 处理函数 (message: UnifiedMessage) -> str
        """
        self._command_handlers[command.lower()] = handler
        logging.info(f"注册 Telegram 命令处理器: /{command}")

    def _handle_start(self, message: UnifiedMessage) -> str:
        """处理 /start 命令"""
        display_name = message.metadata.get("display_name", "用户")
        return f"欢迎 {display_name}! 我是 {self.bot_prefix} 机器人，有什么可以帮你的？"

    def _handle_help(self, message: UnifiedMessage) -> str:
        """处理 /help 命令"""
        commands = ", ".join([f"/{cmd}" for cmd in self._command_handlers.keys()])
        return f"可用命令: {commands}\n\n直接发送消息即可与我对话。"

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证 Telegram Bot

        参数:
        config: {
            "bot_token": "123456:ABC-DEF...",
            "bot_prefix": "kingsa" (可选),
            "show_tool_messages": "true" (可选),
            "show_thinking": "true" (可选),
            "http_proxy": "http://127.0.0.1:18118" (可选),
            "http_proxy_auth": "user:password" (可选),
            "show_typing": "false" (可选),
            "private_chat_strategy": "open" (可选),
            "group_chat_strategy": "open" (可选),
            "require_mention": "false" (可选),
            "whitelist_users": "123456,789012" (可选),
        }

        返回:
        认证成功返回 True
        """
        self.bot_token = config.get("bot_token", "")

        if not self.bot_token:
            logging.error("Telegram 认证失败: bot_token 不能为空")
            return False

        # 解析可选配置
        self.bot_prefix = config.get("bot_prefix", "kingsa")
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"
        self.http_proxy = config.get("http_proxy", "")
        self.http_proxy_auth = config.get("http_proxy_auth", "")
        self.show_typing = config.get("show_typing", "false").lower() == "true"
        self.private_chat_strategy = config.get("private_chat_strategy", "open")
        self.group_chat_strategy = config.get("group_chat_strategy", "open")
        self.require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist = config.get("whitelist_users", "")
        if whitelist:
            self.whitelist_users = [u.strip() for u in whitelist.split(",") if u.strip()]

        # 设置代理
        self._setup_proxy()

        # 验证 token
        return self._verify_token()

    def _setup_proxy(self):
        """设置 HTTP 代理"""
        if not self.http_proxy:
            self._proxies = None
            return

        proxies = {
            "http": self.http_proxy,
            "https": self.http_proxy,
        }

        if self.http_proxy_auth:
            # 将认证信息加入 URL
            parts = self.http_proxy.split("://", 1)
            if len(parts) == 2:
                protocol, url = parts
                self._proxies = {
                    "http": f"{protocol}://{self.http_proxy_auth}@{url}",
                    "https": f"{protocol}://{self.http_proxy_auth}@{url}",
                }
        else:
            self._proxies = proxies

        logging.info(f"Telegram 代理已设置: {self.http_proxy}")

    def _api_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        统一的 Telegram API 请求方法

        参数:
        method: HTTP 方法 (GET/POST)
        path: API 路径 (如 /botTOKEN/getMe)
        **kwargs: requests 的其他参数

        返回:
        API 响应数据
        """
        if not REQUESTS_AVAILABLE:
            return {"ok": False, "description": "requests 库未安装"}

        url = f"{self.API_BASE}{path}"
        kwargs.setdefault("timeout", 10)
        if self._proxies:
            kwargs["proxies"] = self._proxies

        try:
            resp = requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logging.error(f"Telegram API 请求超时: {url}")
            return {"ok": False, "description": "请求超时"}
        except requests.exceptions.HTTPError as e:
            logging.error(f"Telegram API HTTP 错误: {e}")
            return {"ok": False, "description": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            logging.error(f"Telegram API 请求异常: {e}")
            return {"ok": False, "description": str(e)}

    def _verify_token(self) -> bool:
        """验证 Bot Token"""
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
                logging.info(f"Telegram 认证成功: @{self._bot_username}")
                return True
            else:
                logging.error(f"Telegram 认证失败: {data}")
                return False
        except Exception as e:
            logging.error(f"Telegram 认证异常: {e}")
            return False

    def _ensure_initialized(self) -> bool:
        """确保 Bot 已初始化"""
        if not self._initialized:
            return self._verify_token()
        return True

    # ============================================================
    # 消息发送
    # ============================================================

    def send_message(self, message: UnifiedMessage) -> bool:
        """
        发送 Telegram 消息

        参数:
        message: 统一消息对象

        返回:
        发送成功返回 True
        """
        if not self._ensure_initialized():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info(f"[Telegram模拟] 发送消息到 {message.chat_id}: {message.content[:50]}")
            return True

        try:
            # 显示正在输入状态
            if self.show_typing:
                self._send_chat_action(message.chat_id, "typing")

            # 根据内容类型发送不同消息
            if message.content_type == ContentType.TEXT:
                return self._send_text_message(message.chat_id, message.content)
            elif message.content_type == ContentType.IMAGE:
                return self._send_photo(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.VOICE:
                return self._send_voice(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.VIDEO:
                return self._send_video(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.FILE:
                return self._send_document(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.LOCATION:
                return self._send_location(message.chat_id, message.content)
            elif message.content_type == ContentType.CARD:
                return self._send_text_message(message.chat_id, message.content)
            else:
                return self._send_text_message(message.chat_id, message.content)
        except Exception as e:
            logging.error(f"Telegram 消息发送异常: {e}")
            return False

    def _send_text_message(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
        """发送文本消息"""
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            },
        )

        if data.get("ok"):
            return True
        else:
            logging.error(f"Telegram 文本消息发送失败: {data}")
            return False

    def _send_photo(self, chat_id: str, photo: str, caption: str = "") -> bool:
        """发送图片"""
        payload = {
            "chat_id": chat_id,
            "photo": photo,
        }
        if caption:
            payload["caption"] = caption

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendPhoto",
            json=payload,
        )

        return data.get("ok", False)

    def _send_voice(self, chat_id: str, voice: str, caption: str = "") -> bool:
        """发送语音"""
        payload = {
            "chat_id": chat_id,
            "voice": voice,
        }
        if caption:
            payload["caption"] = caption

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendVoice",
            json=payload,
        )

        return data.get("ok", False)

    def _send_video(self, chat_id: str, video: str, caption: str = "") -> bool:
        """发送视频"""
        payload = {
            "chat_id": chat_id,
            "video": video,
        }
        if caption:
            payload["caption"] = caption

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendVideo",
            json=payload,
        )

        return data.get("ok", False)

    def _send_document(self, chat_id: str, document: str, caption: str = "") -> bool:
        """发送文件"""
        payload = {
            "chat_id": chat_id,
            "document": document,
        }
        if caption:
            payload["caption"] = caption

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendDocument",
            json=payload,
        )

        return data.get("ok", False)

    def _send_location(self, chat_id: str, location_data: str) -> bool:
        """发送位置"""
        try:
            # 解析位置数据 "Lat:xx, Lng:yy"
            parts = location_data.replace("[位置] ", "").split(",")
            lat = float(parts[0].replace("Lat:", "").strip())
            lng = float(parts[1].replace("Lng:", "").strip())

            data = self._api_request(
                "POST",
                f"/bot{self.bot_token}/sendLocation",
                json={
                    "chat_id": chat_id,
                    "latitude": lat,
                    "longitude": lng,
                },
            )
            return data.get("ok", False)
        except (ValueError, IndexError):
            logging.error(f"位置数据解析失败: {location_data}")
            return False

    def _send_chat_action(self, chat_id: str, action: str) -> bool:
        """发送聊天动作 (如正在输入)"""
        if not REQUESTS_AVAILABLE or not self.show_typing:
            return True

        self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
        )
        return True

    # ============================================================
    # 消息接收
    # ============================================================

    def receive_message(self) -> Optional[UnifiedMessage]:
        """
        使用 getUpdates 长轮询接收消息

        返回:
        统一消息对象，无消息返回 None
        """
        if not self._ensure_initialized():
            return None

        if not REQUESTS_AVAILABLE:
            return None

        try:
            data = self._api_request(
                "GET",
                f"/bot{self.bot_token}/getUpdates",
                params={
                    "offset": self._last_update_id + 1,
                    "limit": self._polling_limit,
                    "timeout": self._polling_timeout,
                },
                timeout=self._polling_timeout + 5,
            )

            if data.get("ok") and data.get("result"):
                updates = data["result"]
                for update in updates:
                    update_id = update.get("update_id", 0)
                    if update_id > self._last_update_id:
                        self._last_update_id = update_id

                    # 解析消息
                    message = self.parse_raw_message(update)
                    if message:
                        return message

            return None
        except Exception as e:
            logging.error(f"Telegram 接收消息异常: {e}")
            return None

    def parse_raw_message(self, raw_data: Any) -> Optional[UnifiedMessage]:
        """
        解析 Telegram 原始消息

        参数:
        raw_data: Telegram Update 对象 (dict 或 JSON 字符串)

        返回:
        统一消息对象，如果不是消息类型返回 None
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                logging.error(f"Telegram JSON 解析失败: {raw_data}")
                return None

        # 提取消息
        msg = raw_data.get("message") or raw_data.get("edited_message") or {}
        if not msg:
            return None

        chat = msg.get("chat", {})
        sender = msg.get("from", {})

        # 提取内容
        content = msg.get("text", "")
        content_type = ContentType.TEXT

        if msg.get("photo"):
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg.get("voice"):
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg.get("video"):
            content_type = ContentType.VIDEO
            content = "[视频]"
        elif msg.get("document"):
            content_type = ContentType.FILE
            content = "[文件]"
        elif msg.get("location"):
            content_type = ContentType.LOCATION
            loc = msg["location"]
            content = f"[位置] Lat:{loc.get('latitude', '')}, Lng:{loc.get('longitude', '')}"
        elif msg.get("audio"):
            content_type = ContentType.VOICE
            content = "[音频]"
        elif msg.get("sticker"):
            content_type = ContentType.IMAGE
            content = "[表情]"

        # 提取时间戳
        timestamp = None
        msg_date = msg.get("date")
        if msg_date:
            try:
                timestamp = datetime.fromtimestamp(msg_date)
            except (ValueError, TypeError):
                timestamp = datetime.now()

        # 检查@提及
        is_mentioned = self._check_mention(content, msg.get("entities", []))

        # 检查是否是命令
        command = None
        if content.startswith("/"):
            parts = content.split()
            command = parts[0][1:].lower()  # 去掉 / 并转小写

        # 处理命令
        if command and command in self._command_handlers:
            handler = self._command_handlers[command]
            temp_message = UnifiedMessage(
                message_id=str(msg.get("message_id", "")),
                channel=MessageChannel.TELEGRAM,
                chat_id=str(chat.get("id", "")),
                user_id=str(sender.get("id", "")),
                agent_id="",
                content=content,
                content_type=content_type,
                timestamp=timestamp,
                raw_message=raw_data,
                metadata={
                    "display_name": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
                    "username": sender.get("username", ""),
                    "chat_type": chat.get("type", ""),
                    "chat_title": chat.get("title", ""),
                    "is_mentioned": is_mentioned,
                    "command": command,
                },
            )
            try:
                response = handler(temp_message)
                self._send_text_message(str(chat.get("id", "")), response)
            except Exception as e:
                logging.error(f"命令处理异常 /{command}: {e}")

        return UnifiedMessage(
            message_id=str(msg.get("message_id", "")),
            channel=MessageChannel.TELEGRAM,
            chat_id=str(chat.get("id", "")),
            user_id=str(sender.get("id", "")),
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            raw_message=raw_data,
            metadata={
                "display_name": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
                "username": sender.get("username", ""),
                "chat_type": chat.get("type", ""),
                "chat_title": chat.get("title", ""),
                "is_mentioned": is_mentioned,
                "command": command,
                "message_thread_id": msg.get("message_thread_id"),
                "reply_to_message": msg.get("reply_to_message"),
            },
        )

    def _check_mention(self, text: str, entities: List[Dict]) -> bool:
        """检查消息是否@了机器人"""
        for entity in entities:
            if entity.get("type") == "mention":
                start = entity.get("offset", 0)
                length = entity.get("length", 0)
                mentioned_name = text[start:start+length]
                bot_names = [
                    f"@{self.bot_prefix}",
                    f"@{self.bot_prefix.lower()}",
                    f"@{self._bot_username}",
                ]
                if mentioned_name in bot_names:
                    return True
        return False

    # ============================================================
    # 策略检查
    # ============================================================

    def should_process_message(self, raw_data: Dict) -> bool:
        """
        检查是否应该处理该消息 (根据策略配置)

        参数:
        raw_data: Telegram Update 对象

        返回:
        应该处理返回 True
        """
        msg = raw_data.get("message") or raw_data.get("edited_message") or {}
        if not msg:
            return False

        chat = msg.get("chat", {})
        chat_type = chat.get("type", "")
        sender_id = str(msg.get("from", {}).get("id", ""))

        # 私聊策略
        if chat_type == "private":
            if self.private_chat_strategy == "closed":
                return False
            elif self.private_chat_strategy == "whitelist":
                return sender_id in self.whitelist_users
            return True  # open

        # 群聊策略
        if chat_type in ("group", "supergroup"):
            if self.group_chat_strategy == "closed":
                return False
            elif self.group_chat_strategy == "whitelist":
                return sender_id in self.whitelist_users

            # open 策略下，检查是否需要@
            if self.require_mention:
                text = msg.get("text", "")
                entities = msg.get("entities", [])
                return self._check_mention(text, entities)

            return True

        return True

    # ============================================================
    # Webhook 管理
    # ============================================================

    def set_webhook(self, webhook_url: str, secret_token: str = "") -> bool:
        """
        设置 Webhook

        参数:
        webhook_url: Webhook URL
        secret_token: Webhook 密钥 (可选)

        返回:
        设置成功返回 True
        """
        if not REQUESTS_AVAILABLE:
            return True

        self._webhook_url = webhook_url
        self._webhook_secret = secret_token

        payload = {"url": webhook_url}
        if secret_token:
            payload["secret_token"] = secret_token

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/setWebhook",
            json=payload,
        )

        if data.get("ok"):
            logging.info(f"Telegram Webhook 已设置: {webhook_url}")
            return True
        else:
            logging.error(f"Telegram Webhook 设置失败: {data}")
            return False

    def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """
        删除 Webhook

        返回:
        删除成功返回 True
        """
        if not REQUESTS_AVAILABLE:
            return True

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/deleteWebhook",
            json={"drop_pending_updates": drop_pending_updates},
        )

        if data.get("ok"):
            logging.info("Telegram Webhook 已删除")
            return True
        else:
            logging.error(f"Telegram Webhook 删除失败: {data}")
            return False

    def get_webhook_info(self) -> Optional[Dict]:
        """获取 Webhook 信息"""
        data = self._api_request(
            "GET",
            f"/bot{self.bot_token}/getWebhookInfo",
        )

        if data.get("ok"):
            return data.get("result")
        return None

    def verify_webhook_signature(self, headers: Dict) -> bool:
        """
        验证 Webhook 请求签名

        参数:
        headers: HTTP 请求头

        返回:
        签名验证是否通过
        """
        if not self._webhook_secret:
            return True  # 未设置密钥时不验证

        return headers.get("X-Telegram-Bot-Api-Secret-Token", "") == self._webhook_secret

    # ============================================================
    # 用户和群管理
    # ============================================================

    def get_user_info(self, user_id: str) -> Optional[Dict]:
        """
        获取用户信息 (通过聊天记录间接获取)

        参数:
        user_id: 用户 ID

        返回:
        用户信息字典
        """
        # Telegram Bot API 没有直接获取用户信息的接口
        # 只能通过接收到的消息获取用户信息
        return None

    def get_chat_info(self, chat_id: str) -> Optional[Dict]:
        """
        获取群/聊天信息

        参数:
        chat_id: 聊天 ID

        返回:
        聊天信息字典
        """
        if not self._ensure_initialized():
            return None

        data = self._api_request(
            "GET",
            f"/bot{self.bot_token}/getChat",
            params={"chat_id": chat_id},
        )

        if data.get("ok"):
            return data.get("result")
        return None

    def get_chat_administrators(self, chat_id: str) -> List[Dict]:
        """获取群管理员列表"""
        if not self._ensure_initialized():
            return []

        data = self._api_request(
            "GET",
            f"/bot{self.bot_token}/getChatAdministrators",
            params={"chat_id": chat_id},
        )

        if data.get("ok"):
            return data.get("result", [])
        return []

    def ban_chat_member(self, chat_id: str, user_id: str, until_date: int = 0) -> bool:
        """禁言群成员"""
        if not self._ensure_initialized():
            return False

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/banChatMember",
            json={
                "chat_id": chat_id,
                "user_id": user_id,
                "until_date": until_date,
            },
        )

        return data.get("ok", False)

    def unban_chat_member(self, chat_id: str, user_id: str, only_if_banned: bool = False) -> bool:
        """解除禁言"""
        if not self._ensure_initialized():
            return False

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/unbanChatMember",
            json={
                "chat_id": chat_id,
                "user_id": user_id,
                "only_if_banned": only_if_banned,
            },
        )

        return data.get("ok", False)

    # ============================================================
    # 消息管理
    # ============================================================

    def delete_message(self, chat_id: str, message_id: str) -> bool:
        """删除消息"""
        if not self._ensure_initialized():
            return False

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/deleteMessage",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )

        return data.get("ok", False)

    def pin_message(self, chat_id: str, message_id: str, disable_notification: bool = False) -> bool:
        """置顶消息"""
        if not self._ensure_initialized():
            return False

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/pinChatMessage",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": disable_notification,
            },
        )

        return data.get("ok", False)

    def unpin_message(self, chat_id: str, message_id: str = None) -> bool:
        """取消置顶"""
        if not self._ensure_initialized():
            return False

        payload = {"chat_id": chat_id}
        if message_id:
            payload["message_id"] = message_id

        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/unpinChatMessage",
            json=payload,
        )

        return data.get("ok", False)

    # ============================================================
    # 配置管理
    # ============================================================

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置"""
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
        """
        更新渠道配置

        参数:
        config: 配置字典
        """
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
        if "private_chat_strategy" in config:
            self.private_chat_strategy = config["private_chat_strategy"]
        if "group_chat_strategy" in config:
            self.group_chat_strategy = config["group_chat_strategy"]
        if "require_mention" in config:
            self.require_mention = config["require_mention"]
        if "whitelist_users" in config:
            self.whitelist_users = config["whitelist_users"]

    def get_bot_info(self) -> Dict:
        """获取 Bot 信息"""
        return self._bot_info

    def reset_polling_offset(self):
        """重置长轮询偏移量"""
        self._last_update_id = 0

    # ============================================================
    # AI 生成能力
    # ============================================================

    async def generate_text_to_image(self, prompt: str, **kwargs) -> Optional[bytes]:
        """生成AI图片

        参数:
            prompt: 图片描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回图片二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import get_generator_manager, GenerationConfig, GeneratorType

            manager = get_generator_manager()
            generator = manager.get_generator("text_to_image", kwargs.get("model"))
            if not generator:
                logger.error("未找到文本生成图片的生成器")
                return None

            config = GenerationConfig(
                type=GeneratorType.TEXT_TO_IMAGE,
                model=kwargs.get("model", "wanx-v1"),
                prompt=prompt,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 1024),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
                style=kwargs.get("style", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self._download_url(result.urls[0])
            else:
                logger.error(f"图片生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception(f"AI图片生成异常: {e}")
            return None

    async def generate_image_to_image(self, image_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        """图生图 - 基于参考图片生成新图片

        参数:
            image_url: 参考图片URL
            prompt: 图片描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回图片二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import get_generator_manager, GenerationConfig, GeneratorType

            manager = get_generator_manager()
            generator = manager.get_generator("image_to_image", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生图的生成器")
                return None

            image_data = await self._download_url(image_url)
            if not image_data:
                logger.error(f"下载参考图片失败: {image_url}")
                return None

            config = GenerationConfig(
                type=GeneratorType.IMAGE_TO_IMAGE,
                model=kwargs.get("model", "sd-img2img-xl"),
                prompt=prompt,
                image_url=image_url,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 1024),
                strength=kwargs.get("strength", 0.7),
                guidance_scale=kwargs.get("guidance_scale", 7.5),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
                style=kwargs.get("style", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self._download_url(result.urls[0])
            else:
                logger.error(f"图生图生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception(f"图生图生成异常: {e}")
            return None

    async def generate_text_to_video(self, prompt: str, **kwargs) -> Optional[bytes]:
        """生成AI视频

        参数:
            prompt: 视频描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import get_generator_manager, GenerationConfig, GeneratorType

            manager = get_generator_manager()
            generator = manager.get_generator("text_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到文本生成视频的生成器")
                return None

            config = GenerationConfig(
                type=GeneratorType.TEXT_TO_VIDEO,
                model=kwargs.get("model", "kling-v1"),
                prompt=prompt,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self._download_url(result.urls[0])
            else:
                logger.error(f"视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception(f"AI视频生成异常: {e}")
            return None

    async def generate_image_to_video(self, image_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        """图生视频 - 基于图片生成视频

        参数:
            image_url: 参考图片URL
            prompt: 视频描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import get_generator_manager, GenerationConfig, GeneratorType

            manager = get_generator_manager()
            generator = manager.get_generator("image_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生视频的生成器")
                return None

            image_data = await self._download_url(image_url)
            if not image_data:
                logger.error(f"下载参考图片失败: {image_url}")
                return None

            config = GenerationConfig(
                type=GeneratorType.IMAGE_TO_VIDEO,
                model=kwargs.get("model", "kling-v1-video"),
                prompt=prompt,
                image_url=image_url,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self._download_url(result.urls[0])
            else:
                logger.error(f"图生视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception(f"图生视频生成异常: {e}")
            return None

    async def generate_keyframe_to_video(self, start_url: str, end_url: str, **kwargs) -> Optional[bytes]:
        """首尾帧生视频 - 基于起始和结束帧生成视频

        参数:
            start_url: 起始帧图片URL
            end_url: 结束帧图片URL
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import get_generator_manager, GenerationConfig, GeneratorType

            manager = get_generator_manager()
            generator = manager.get_generator("keyframe_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到首尾帧生成视频的生成器")
                return None

            start_data = await self._download_url(start_url)
            end_data = await self._download_url(end_url)
            if not start_data or not end_data:
                logger.error("下载首尾帧失败")
                return None

            config = GenerationConfig(
                type=GeneratorType.KEYFRAME_TO_VIDEO,
                model=kwargs.get("model", "kling-v1-keyframe"),
                prompt=kwargs.get("prompt", ""),
                start_image_url=start_url,
                end_image_url=end_url,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self._download_url(result.urls[0])
            else:
                logger.error(f"首尾帧生成视频失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception(f"首尾帧生成视频异常: {e}")
            return None

    async def generate_video_to_video(self, video_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        """视频生视频 - 基于参考视频生成新视频

        参数:
            video_url: 参考视频URL
            prompt: 视频描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import get_generator_manager, GenerationConfig, GeneratorType

            manager = get_generator_manager()
            generator = manager.get_generator("video_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到视频生成视频的生成器")
                return None

            video_data = await self._download_url(video_url)
            if not video_data:
                logger.error(f"下载参考视频失败: {video_url}")
                return None

            config = GenerationConfig(
                type=GeneratorType.VIDEO_TO_VIDEO,
                model=kwargs.get("model", "kling-v1-v2v"),
                prompt=prompt,
                video_url=video_url,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                strength=kwargs.get("strength", 0.75),
                guidance_scale=kwargs.get("guidance_scale", 7.5),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
                style=kwargs.get("style", "realistic"),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self._download_url(result.urls[0])
            else:
                logger.error(f"视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception(f"视频生成异常: {e}")
            return None

    async def _download_url(self, url: str, timeout: int = 60) -> Optional[bytes]:
        """下载URL内容

        参数:
            url: 目标URL
            timeout: 超时时间（秒）

        返回:
            成功返回二进制数据，失败返回 None
        """
        if HTTPX_AVAILABLE:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return response.content
                    else:
                        logging.error(f"下载失败 HTTP {response.status_code}: {url}")
                        return None
            except Exception as e:
                logging.error(f"httpx下载异常: {e}")
                return None
        elif REQUESTS_AVAILABLE:
            try:
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    return response.content
                else:
                    logging.error(f"下载失败 HTTP {response.status_code}: {url}")
                    return None
            except Exception as e:
                logging.error(f"requests下载异常: {e}")
                return None
        else:
            logging.error("无可用的HTTP客户端")
            return None

    async def _save_temp_file(self, data: bytes, extension: str) -> Optional[str]:
        """保存临时文件

        参数:
            data: 文件数据
            extension: 文件扩展名

        返回:
            成功返回文件路径，失败返回 None
        """
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as f:
                f.write(data)
                temp_path = f.name
            logging.info(f"临时文件已保存: {temp_path}")
            return temp_path
        except Exception as e:
            logging.error(f"保存临时文件失败: {e}")
            return None

    def _extract_prompt(self, content: str) -> str:
        """从消息内容中提取AI生成提示词

        参数:
            content: 消息内容

        返回:
            提取的提示词
        """
        patterns = [
            r"生成?\s*(?:一张|个)?\s*(?:图片?|画).*?[:：]?\s*(.+)",
            r"画.*?[:：]?\s*(.+)",
            r"生成?\s*(?:一段|个)?\s*视频.*?[:：]?\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return content

    async def handle_ai_generation(self, message: UnifiedMessage) -> bool:
        """处理AI生成请求

        检测消息中的AI生成请求并执行生成

        参数:
            message: 统一消息对象

        返回:
            处理成功返回 True
        """
        content = message.content.lower()

        has_image = message.content_type == ContentType.IMAGE
        has_video = message.content_type == ContentType.VIDEO

        image_url = message.file_url or message.metadata.get("file_url", "")
        video_url = message.file_url or message.metadata.get("file_url", "")

        if "生成图片" in content or "画一张" in content or "生成一张图片" in content:
            if has_image:
                prompt = self._extract_prompt(message.content) or ""
                if image_url:
                    self._send_text_message(message.chat_id, "正在生成图片，请稍候...")
                    gen_image_data = await self.generate_image_to_image(image_url, prompt)
                    if gen_image_data:
                        temp_path = await self._save_temp_file(gen_image_data, "png")
                        if temp_path:
                            if self._send_photo(message.chat_id, temp_path):
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                    self._send_text_message(message.chat_id, "图片生成失败")
                    return False
            else:
                prompt = self._extract_prompt(message.content)
                if prompt:
                    self._send_text_message(message.chat_id, "正在生成图片，请稍候...")
                    image_data = await self.generate_text_to_image(prompt)
                    if image_data:
                        temp_path = await self._save_temp_file(image_data, "png")
                        if temp_path:
                            if self._send_photo(message.chat_id, temp_path):
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                    self._send_text_message(message.chat_id, "图片生成失败")
                    return False

        elif has_image and ("图生图" in content or "以图生图" in content or "生成相似图片" in content or "生成新图片" in content):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                self._send_text_message(message.chat_id, "正在生成图片，请稍候...")
                image_data = await self.generate_image_to_image(image_url, prompt)
                if image_data:
                    temp_path = await self._save_temp_file(image_data, "png")
                    if temp_path:
                        if self._send_photo(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "图片生成失败")
                return False

        elif has_image and ("图生视频" in content or "图片转视频" in content or "让图片动起来" in content or "图片生成视频" in content):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_image_to_video(image_url, prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        elif ("首尾帧" in content or "首帧到尾帧" in content or "首尾帧生成视频" in content) and message.metadata.get("images_count", 0) >= 2:
            start_url = message.metadata.get("first_image_url", "")
            end_url = message.metadata.get("last_image_url", "")
            if start_url and end_url:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_keyframe_to_video(start_url, end_url)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        elif has_video and ("视频生成" in content or "视频风格" in content or "修改视频" in content or "视频转视频" in content):
            prompt = self._extract_prompt(message.content) or ""
            if video_url:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_video_to_video(video_url, prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        elif "生成视频" in content or "生成一段视频" in content:
            prompt = self._extract_prompt(message.content)
            if prompt:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_text_to_video(prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        return False

# ============================================================
# 工厂函数
# ============================================================

def create_telegram_adapter(bot_token: str = "", **kwargs) -> TelegramAdapter:
    """
    创建 Telegram 适配器

    参数:
    bot_token: Bot Token
    **kwargs: 其他配置项

    返回:
    Telegram 适配器实例
    """
    adapter = TelegramAdapter()
    if bot_token:
        config = {
            "bot_token": bot_token,
            **kwargs,
        }
        adapter.authenticate(config)
    return adapter
