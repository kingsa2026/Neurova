"""
QQ频道消息渠道适配器

API 文档: https://bot.q.qq.com/wiki/
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    pass

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage


class QQAdapter(ChannelAdapter):
    """
    QQ频道消息渠道适配器

    支持:
    - QQ频道消息收发
    - 子频道消息处理
    - Webhook 回调处理
    - 群聊/私聊策略
    """

    API_BASE = "https://api.sgroup.qq.com"
    SANDBOX_API_BASE = "https://sandbox.api.sgroup.qq.com"

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.QQ

    def __init__(self):
        # 基础认证信息
        self.app_id = ""
        self.token = ""
        self.secret = ""

        # 频道信息
        self.guild_id = ""
        self.channel_ids = []  # 可以监听多个子频道

        # 配置选项
        self.bot_prefix = "kingsa"
        self.show_tool_messages = True
        self.show_thinking = True
        self.media_directory = ""

        # 消息策略
        self.private_chat_strategy = "open"  # open/closed/whitelist
        self.group_chat_strategy = "open"  # open/closed/whitelist
        self.require_mention = False
        self.whitelist_users = []
        self.message_merge = False
        self.group_share_session = True
        self.welcome_message = ""

        # 内部状态
        self._initialized = False
        self.access_token = ""
        self.token_expire_time = 0
        self.session_id = ""
        self._parse_lock = threading.Lock()  # BUG-42: 消息解析线程锁

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证QQ频道应用

        参数:
        config: {
            "app_id": "应用ID",
            "token": "Bot Token",
            "secret": "应用密钥",
            "guild_id": "频道ID (可选)",
            "channel_ids": "子频道ID列表 (逗号分隔)",
            "bot_prefix": "机器人前缀",
            "show_tool_messages": "true/false",
            "show_thinking": "true/false",
            "media_directory": "媒体文件目录",
            "private_chat_strategy": "open/closed/whitelist",
            "group_chat_strategy": "open/closed/whitelist",
            "require_mention": "true/false",
            "whitelist_users": "用户ID列表 (逗号分隔)",
            "message_merge": "true/false",
            "group_share_session": "true/false",
            "welcome_message": "欢迎消息",
        }
        """
        self.app_id = config.get("app_id", "")
        self.token = config.get("token", "")
        self.secret = config.get("secret", "")
        self.guild_id = config.get("guild_id", "")

        # 解析子频道ID列表
        channel_str = config.get("channel_ids", "")
        if channel_str:
            self.channel_ids = [cid.strip() for cid in channel_str.split(",") if cid.strip()]

        # 配置选项
        self.bot_prefix = config.get("bot_prefix", "kingsa")
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"
        self.media_directory = config.get("media_directory", "")

        # 消息策略
        self.private_chat_strategy = config.get("private_chat_strategy", "open")
        self.group_chat_strategy = config.get("group_chat_strategy", "open")
        self.require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist_str = config.get("whitelist_users", "")
        if whitelist_str:
            self.whitelist_users = [uid.strip() for uid in whitelist_str.split(",") if uid.strip()]
        else:
            self.whitelist_users = []

        self.message_merge = config.get("message_merge", "false").lower() == "true"
        self.group_share_session = config.get("group_share_session", "true").lower() == "true"
        self.welcome_message = config.get("welcome_message", "")

        if not self.app_id or not self.token or not self.secret:
            logging.error("QQ频道认证失败: app_id, token, secret 不能为空")
            return False

        return self._refresh_token()

    def _refresh_token(self) -> bool:
        """刷新 access_token"""
        if not REQUESTS_AVAILABLE:
            self._initialized = True
            return True

        try:
            url = f"{self.API_BASE}/gateway/bot"
            headers = {
                "Authorization": f"Bot {self.app_id}.{self.token}",
                "User-Agent": f"Bot/{self.app_id} Neurova-QQ-Adapter/1.0",
            }

            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()

            if resp.status_code == 200:
                self._initialized = True
                logging.info("QQ频道认证成功")
                return True
            else:
                logging.error("QQ频道认证失败: %s", data)
                return False
        except requests.exceptions.Timeout as e:
            logging.error("QQ频道认证超时: %s", e)
            return False
        except requests.exceptions.RequestException as e:
            logging.error("QQ频道认证请求异常: %s", e)
            return False
        except Exception as e:
            logging.error("QQ频道认证异常: %s", e)
            return False

    def _ensure_token(self) -> bool:
        """确保 token 有效"""
        if not self._initialized:
            return self._refresh_token()
        return True

    def send_message(self, message: UnifiedMessage) -> bool:
        """发送QQ频道消息"""
        if not self._ensure_token():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[QQ模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            # 根据消息类型构建API请求
            url = f"{self.API_BASE}/channels/{message.chat_id}/messages"

            headers = {"Authorization": f"Bot {self.app_id}.{self.token}", "Content-Type": "application/json"}

            payload = {"content": message.content, "msg_id": message.message_id}  # 回复时可携带原消息ID

            # 如果启用消息合并，添加合并标识
            if self.message_merge:
                payload["embed"] = {"title": "系统消息", "description": "此消息为合并发送"}

            resp = requests.post(url, headers=headers, json=payload, timeout=10)

            if resp.status_code in [200, 202]:
                return True
            else:
                data = resp.json()
                logging.error("QQ频道消息发送失败: %s", data)
                return False
        except Exception as e:
            logging.error("QQ频道消息发送异常: %s", e)
            return False

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收消息 (需通过 Webhook 回调)"""
        logging.warning("QQ频道消息接收请使用 Webhook 模式")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析QQ频道原始消息 (BUG-42: 线程锁保护)

        QQ频道回调消息格式:
        {
            "id": "消息ID",
            "channel_id": "子频道ID",
            "guild_id": "频道ID",
            "content": "消息内容",
            "timestamp": "YYYY-MM-DDTHH:mm:ss.SSSZ",
            "author": {
                "id": "用户ID",
                "username": "用户名",
                "bot": false
            },
            "mentions": ["用户ID列表"],
            "mention_all": false,
            "mention_roles": [],
            "mention_everyone": false
        }
        """
        with self._parse_lock:
            return self._parse_raw_message_locked(raw_data)

    def _parse_raw_message_locked(self, raw_data: Any) -> UnifiedMessage:
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                logging.error("解析QQ频道消息失败: 无效JSON格式")
                return None

        # 提取消息信息
        message_id = raw_data.get("id", str(int(time.time())))
        channel_id = raw_data.get("channel_id", "")
        guild_id = raw_data.get("guild_id", "")
        content = raw_data.get("content", "")
        timestamp_str = raw_data.get("timestamp", "")
        author = raw_data.get("author", {})
        user_id = author.get("id", "")
        username = author.get("username", "")

        # 解析时间戳
        timestamp = None
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()

        # 检查是否为机器人自己发的消息
        if author.get("bot", False):
            logging.debug("忽略机器人自己的消息")
            return None

        # 检查是否需要 @提及
        if self.require_mention:
            mentions = raw_data.get("mentions", [])
            # 在QQ频道中，@机器人的信息通常在mentions里
            # 或者content中包含 <@!机器人ID>
            bot_mentioned = False
            if mentions and self.app_id in mentions:
                bot_mentioned = True
            elif f"<@!{self.app_id}>" in content:
                bot_mentioned = True

            if not bot_mentioned:
                logging.debug("消息未@机器人，忽略")
                return None

        # 检查私聊/群聊策略
        # QQ频道都是群聊，所以检查群聊策略
        if self.group_chat_strategy == "closed":
            logging.debug("群聊已关闭，忽略消息")
            return None
        elif self.group_chat_strategy == "whitelist":
            if user_id not in self.whitelist_users:
                logging.debug("用户 %s 不在白名单中", user_id)
                return None

        return UnifiedMessage(
            message_id=message_id,
            channel=MessageChannel.QQ,
            chat_id=channel_id,  # 使用子频道ID作为chat_id
            user_id=user_id,
            agent_id="",
            content=content,
            content_type=ContentType.TEXT,
            timestamp=timestamp,
            global_user_id=f"qq:{user_id}",  # 生成全局用户ID
            session_id=f"qq:{channel_id}:{user_id}",  # 生成会话ID
            raw_message=raw_data,
            metadata={
                "guild_id": guild_id,
                "channel_id": channel_id,
                "username": username,
                "mentions": raw_data.get("mentions", []),
                "mention_all": raw_data.get("mention_all", False),
                "author": author,
            },
        )

    def verify_signature(self, timestamp: str, sign: str, body: str) -> bool:
        """
        验证回调签名 (QQ频道使用 HMAC-SHA256)

        参数:
        timestamp: 时间戳
        sign: 签名
        body: 请求体
        """
        if not self.secret:
            return False

        # 构造签名字符串: timestamp + body
        sign_str = timestamp + body
        expected_sign = hmac.new(
            self.secret.encode("utf-8"), sign_str.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_sign, sign)

    def get_channel_config(self) -> Dict[str, Any]:
        return {
            "channel": self.channel.value,
            "app_id": self.app_id,
            "guild_id": self.guild_id,
            "channel_ids": self.channel_ids,
            "bot_prefix": self.bot_prefix,
            "show_tool_messages": self.show_tool_messages,
            "show_thinking": self.show_thinking,
            "media_directory": self.media_directory,
            "private_chat_strategy": self.private_chat_strategy,
            "group_chat_strategy": self.group_chat_strategy,
            "require_mention": self.require_mention,
            "whitelist_users": self.whitelist_users,
            "message_merge": self.message_merge,
            "group_share_session": self.group_share_session,
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

        # 检查是否为机器人自己发的消息
        if author.get("bot", False):
            return False

        # 检查是否需要 @提及
        if self.require_mention:
            mentions = raw_data.get("mentions", [])
            bot_mentioned = False
            if mentions and self.app_id in mentions:
                bot_mentioned = True
            elif f"<@!{self.app_id}>" in raw_data.get("content", ""):
                bot_mentioned = True

            if not bot_mentioned:
                return False

        # 检查群聊策略 (QQ频道都是群聊)
        if self.group_chat_strategy == "closed":
            return False
        elif self.group_chat_strategy == "whitelist":
            return user_id in self.whitelist_users

        return True


def create_qq_adapter(app_id: str = "", token: str = "", secret: str = "") -> QQAdapter:
    """创建QQ频道适配器"""
    adapter = QQAdapter()
    if app_id and token and secret:
        adapter.authenticate(
            {
                "app_id": app_id,
                "token": token,
                "secret": secret,
            }
        )
    return adapter
