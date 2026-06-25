"""
Discord 消息渠道适配器

API 文档: https://discord.com/developers/docs/intro
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage


class DiscordAdapter(ChannelAdapter):
    """
    Discord 消息渠道适配器

    支持:
    - Discord 服务器消息收发
    - 私聊消息处理
    - Webhook 回调处理
    - 代理配置
    """

    API_BASE = "https://discord.com/api/v10"

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.DISCORD

    def __init__(self):
        # 基础认证信息
        self.bot_token = ""

        # 配置选项
        self.bot_prefix = "kingsa"
        self.show_tool_messages = True
        self.show_thinking = True

        # 代理配置
        self.http_proxy = ""
        self.http_proxy_auth = ""
        self._proxies = None

        # 消息策略
        self.receive_bot_messages = False  # 是否接收其他机器人的消息
        self.private_chat_strategy = "open"  # open/closed/whitelist
        self.group_chat_strategy = "open"  # open/closed/whitelist
        self.require_mention = False
        self.whitelist_users = []

        # 内部状态
        self._initialized = False
        self.session = None
        self._auth_lock = threading.Lock()  # BUG-43: 认证锁

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

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证Discord Bot

        参数:
        config: {
            "bot_token": "Bot Token",
            "bot_prefix": "机器人前缀",
            "show_tool_messages": "true/false",
            "show_thinking": "true/false",
            "http_proxy": "HTTP代理地址",
            "http_proxy_auth": "HTTP代理认证 (user:password)",
            "receive_bot_messages": "true/false",
            "private_chat_strategy": "open/closed/whitelist",
            "group_chat_strategy": "open/closed/whitelist",
            "require_mention": "true/false",
            "whitelist_users": "用户ID列表 (逗号分隔)",
        }
        """
        self.bot_token = config.get("bot_token", "")

        if not self.bot_token:
            logging.error("Discord认证失败: bot_token 不能为空")
            return False

        # 配置选项
        self.bot_prefix = config.get("bot_prefix", "kingsa")
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"

        # 代理配置
        self.http_proxy = config.get("http_proxy", "")
        self.http_proxy_auth = config.get("http_proxy_auth", "")
        self._setup_proxy()

        # 消息策略
        self.receive_bot_messages = config.get("receive_bot_messages", "false").lower() == "true"
        self.private_chat_strategy = config.get("private_chat_strategy", "open")
        self.group_chat_strategy = config.get("group_chat_strategy", "open")
        self.require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist_str = config.get("whitelist_users", "")
        if whitelist_str:
            self.whitelist_users = [uid.strip() for uid in whitelist_str.split(",") if uid.strip()]
        else:
            self.whitelist_users = []

        # 创建会话
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()
            if self._proxies:
                self.session.proxies.update(self._proxies)

        return self._verify_token()

    def _verify_token(self) -> bool:
        """验证 Bot Token 是否有效"""
        if not REQUESTS_AVAILABLE:
            self._initialized = True
            return True

        try:
            url = f"{self.API_BASE}/users/@me"
            headers = {
                "Authorization": f"Bot {self.bot_token}",
                "User-Agent": "DiscordBot (https://github.com/neurova, 1.0)",
            }

            resp = self.session.get(url, headers=headers, timeout=10)
            data = resp.json()

            if resp.status_code == 200:
                logging.info(
                    f"Discord认证成功 - 用户: {data.get('username', 'Unknown')}#{data.get('discriminator', '0000')}"
                )
                self._initialized = True
                return True
            else:
                logging.error("Discord认证失败: %s", data)
                return False
        except Exception as e:
            logging.error("Discord认证异常: %s", e)
            return False

    def _ensure_authenticated(self) -> bool:
        """确保已认证 (BUG-43: 添加锁防止并发重复认证)"""
        if not self._initialized:
            with self._auth_lock:
                if not self._initialized:  # 双重检查
                    return self._verify_token()
        return True

    def send_message(self, message: UnifiedMessage) -> bool:
        """发送Discord消息"""
        if not self._ensure_authenticated():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[Discord模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            # 根据chat_id判断是私聊还是频道消息
            # Discord中私聊是DM channel，频道消息是Guild channel
            url = f"{self.API_BASE}/channels/{message.chat_id}/messages"

            headers = {
                "Authorization": f"Bot {self.bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/neurova, 1.0)",
            }

            payload = {
                "content": message.content,
            }

            # 如果是回复消息，携带消息引用
            if hasattr(message, "reply_to_message_id"):
                payload["message_reference"] = {"message_id": message.reply_to_message_id}

            resp = self.session.post(url, headers=headers, json=payload, timeout=10)

            if resp.status_code in [200, 202]:
                return True
            else:
                data = resp.json()
                logging.error("Discord消息发送失败: %s", data)
                return False
        except requests.exceptions.Timeout as e:
            logging.error("Discord消息发送超时: %s", e)
            return False
        except requests.exceptions.RequestException as e:
            logging.error("Discord消息发送请求异常: %s", e)
            return False
        except Exception as e:
            logging.error("Discord消息发送异常: %s", e)
            return False

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收消息 (需通过 Webhook 回调)"""
        logging.warning("Discord消息接收请使用 Webhook 模式")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析Discord原始消息

        Discord消息格式:
        {
            "id": "消息ID",
            "channel_id": "频道ID",
            "author": {
                "id": "用户ID",
                "username": "用户名",
                "discriminator": "用户标识符",
                "bot": false,
                "system": false
            },
            "content": "消息内容",
            "timestamp": "ISO8601时间戳",
            "mentions": [{"id": "用户ID", ...}],
            "mention_everyone": false,
            "mention_roles": [],
            "pinned": false,
            "type": 0
        }
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                logging.error("解析Discord消息失败: 无效JSON格式")
                return None

        # 提取消息信息
        message_id = raw_data.get("id", str(int(time.time())))
        channel_id = raw_data.get("channel_id", "")
        content = raw_data.get("content", "")
        timestamp_str = raw_data.get("timestamp", "")
        author = raw_data.get("author", {})
        user_id = author.get("id", "")
        username = author.get("username", "")
        discriminator = author.get("discriminator", "0000")
        is_bot = author.get("bot", False)

        # 解析时间戳
        timestamp = None
        if timestamp_str:
            try:
                # Discord使用ISO 8601格式
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()

        # 检查是否为机器人消息 (如果配置不允许接收)
        if is_bot and not self.receive_bot_messages:
            logging.debug("忽略其他机器人消息")
            return None

        # 检查是否需要 @提及
        # Discord中 @机器人通常是 <@机器人ID> 或 <@!机器人ID>
        if self.require_mention:
            bot_mentioned = False
            if f"<@{self.bot_token.split('.')[0]}>" in content or f"<@!{self.bot_token.split('.')[0]}>" in content:
                bot_mentioned = True

            if not bot_mentioned:
                logging.debug("消息未@机器人，忽略")
                return None

        # 判断是私聊还是群聊
        # Discord中私聊的channel_id通常对应DM channel，而频道消息的channel_id对应Guild channel
        is_dm = raw_data.get("type", 0) == 1  # DM channel type is 1

        # 检查私聊/群聊策略
        if is_dm:
            if self.private_chat_strategy == "closed":
                logging.debug("私聊已关闭，忽略消息")
                return None
            elif self.private_chat_strategy == "whitelist":
                if user_id not in self.whitelist_users:
                    logging.debug("用户 %s 不在白名单中", user_id)
                    return None
        else:
            if self.group_chat_strategy == "closed":
                logging.debug("群聊已关闭，忽略消息")
                return None
            elif self.group_chat_strategy == "whitelist":
                if user_id not in self.whitelist_users:
                    logging.debug("用户 %s 不在白名单中", user_id)
                    return None

        return UnifiedMessage(
            message_id=message_id,
            channel=MessageChannel.DISCORD,
            chat_id=channel_id,  # 使用频道ID作为chat_id
            user_id=user_id,
            agent_id="",
            content=content,
            content_type=ContentType.TEXT,
            timestamp=timestamp,
            global_user_id=f"discord:{user_id}",  # 生成全局用户ID
            session_id=f"discord:{channel_id}:{user_id}",  # 生成会话ID
            raw_message=raw_data,
            metadata={
                "username": f"{username}#{discriminator}",
                "is_bot": is_bot,
                "channel_id": channel_id,
                "guild_id": raw_data.get("guild_id"),  # 可能为空（私聊）
                "mentions": [m.get("id") for m in raw_data.get("mentions", [])],
                "mention_everyone": raw_data.get("mention_everyone", False),
                "message_type": raw_data.get("type", 0),
            },
        )

    def get_channel_config(self) -> Dict[str, Any]:
        return {
            "channel": self.channel.value,
            "bot_prefix": self.bot_prefix,
            "show_tool_messages": self.show_tool_messages,
            "show_thinking": self.show_thinking,
            "http_proxy": self.http_proxy,
            "http_proxy_auth": self.http_proxy_auth,
            "receive_bot_messages": self.receive_bot_messages,
            "private_chat_strategy": self.private_chat_strategy,
            "group_chat_strategy": self.group_chat_strategy,
            "require_mention": self.require_mention,
            "whitelist_users": self.whitelist_users,
            "authenticated": self._initialized,
        }

    def should_process_message(self, raw_data: Dict) -> bool:
        """
        判断是否应该处理消息 (策略检查)
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                return False

        author = raw_data.get("author", {})
        user_id = author.get("id", "")
        is_bot = author.get("bot", False)

        # 检查是否为机器人消息
        if is_bot and not self.receive_bot_messages:
            return False

        # 检查是否需要 @提及
        if self.require_mention:
            content = raw_data.get("content", "")
            bot_id = self.bot_token.split(".")[0]  # 从token中提取bot id
            bot_mentioned = f"<@{bot_id}>" in content or f"<@!{bot_id}>" in content
            if not bot_mentioned:
                return False

        # 判断是私聊还是群聊
        is_dm = raw_data.get("type", 0) == 1

        # 检查私聊/群聊策略
        if is_dm:
            if self.private_chat_strategy == "closed":
                return False
            elif self.private_chat_strategy == "whitelist":
                return user_id in self.whitelist_users
        else:
            if self.group_chat_strategy == "closed":
                return False
            elif self.group_chat_strategy == "whitelist":
                return user_id in self.whitelist_users

        return True


def create_discord_adapter(bot_token: str = "") -> DiscordAdapter:
    """创建Discord适配器"""
    adapter = DiscordAdapter()
    if bot_token:
        adapter.authenticate({"bot_token": bot_token})
    return adapter
