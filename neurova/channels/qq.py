"""
QQ机器人消息渠道适配器（QQ开放平台: 频道 / 群聊 / 私聊）

API 文档: https://bot.q.qq.com/wiki/develop/api-v2/

鉴权规范（v2）:
- Bot {appid}.{token} 请求头已被官方废弃
- 现行为: POST https://bots.qq.com/app/getAppAccessToken（body: appId/clientSecret）
  获取 access_token，请求头 Authorization: QQBot {access_token}（有效期约 7200 秒）

消息接口:
- 频道:  POST /channels/{channel_id}/messages
- 群聊:  POST /v2/groups/{group_openid}/messages
- 私聊:  POST /v2/users/{openid}/messages
- 主动推送能力已于 2025-04-21 停止，消息发送以被动回复为主（携带 msg_id）

Webhook 验签规范（官方 sign.md）:
- Ed25519 签名，请求头 X-Signature-Ed25519 / X-Signature-Timestamp
- 密钥对由 Bot Secret 倍增至 >=32 字节后截取前 32 字节派生
- 签名体 = timestamp 原始字符串 + raw body
- 回调地址验证（op 13）需用派生私钥对 event_ts + plain_token 签名应答
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

try:
    from ecdsa import SigningKey as _Ed25519SigningKey
    from ecdsa.curves import Ed25519 as _Ed25519Curve

    ED25519_AVAILABLE = True
except ImportError:
    ED25519_AVAILABLE = False

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage

# access_token 换取接口（官方规范，Bot {appid}.{token} 头已废弃）
AUTH_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"


class QQAdapter(ChannelAdapter):
    """
    QQ机器人消息渠道适配器

    支持:
    - QQ频道消息收发（/channels/{id}/messages）
    - QQ群聊消息（v2: /v2/groups/{group_openid}/messages）
    - QQ私聊消息（v2: /v2/users/{openid}/messages）
    - Webhook 回调验签（Ed25519）与 op 13 地址验证
    - 群聊/私聊策略
    """

    API_BASE = "https://api.sgroup.qq.com"
    SANDBOX_API_BASE = "https://sandbox.api.sgroup.qq.com"

    # 官方成功状态码: 200 成功、204 成功无包体、202 异步成功（如消息进入审核）
    _OK_STATUS = (200, 202, 204)

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

        if not self.app_id or not self.secret:
            logging.error("QQ认证失败: app_id, secret 不能为空")
            return False

        if not self._fetch_access_token():
            return False

        return self._verify_connection()

    @staticmethod
    def _validate_resource_id(resource_id: str) -> bool:
        """校验 openid/channel_id 合法性。

        QQ 开放平台 ID 仅由字母数字与 -_@# 组成；校验同时防止
        ID 拼入 URL 路径时注入额外路径段或查询串。
        """
        if not resource_id or len(resource_id) > 128:
            return False
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_@#")
        return all(c in allowed for c in resource_id)

    def _auth_headers(self) -> Dict[str, str]:
        """构造官方规范请求头: Authorization: QQBot {access_token}"""
        return {
            "Authorization": "QQBot " + self.access_token,
            "User-Agent": "Bot/" + self.app_id + " Neurova-QQ-Adapter/1.0",
        }

    def _fetch_access_token(self) -> bool:
        """通过官方 getAppAccessToken 接口换取 access_token（有效期约 7200 秒）"""
        if not REQUESTS_AVAILABLE:
            self._initialized = True
            return True

        try:
            resp = requests.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={"appId": self.app_id, "clientSecret": self.secret},
                timeout=10,
            )
            data = resp.json()

            access_token = data.get("access_token", "")
            if resp.status_code == 200 and access_token:
                self.access_token = access_token
                expires_in = int(data.get("expires_in", 7200))
                # 官方说明: 过期前 60 秒内可获取新 token，旧 token 在此窗口内仍有效
                self.token_expire_time = time.time() + max(expires_in - 60, 60)
                self._initialized = True
                logging.info("QQ access_token 获取成功")
                return True

            logging.error("QQ access_token 获取失败: %s", data)
            return False
        except Exception as e:
            logging.error("QQ access_token 请求异常: %s", e)
            return False

    def _verify_connection(self) -> bool:
        """通过 GET /gateway/bot 验证凭证与连通性（官方 WebSocket 网关接口）"""
        if not REQUESTS_AVAILABLE:
            return True

        try:
            resp = requests.get(
                "https://api.sgroup.qq.com/gateway/bot", headers=self._auth_headers(), timeout=10
            )

            if resp.status_code == 200:
                logging.info("QQ频道认证成功")
                return True

            logging.error("QQ频道认证失败: %s", resp.text[:200])
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
        """确保 access_token 有效（官方: token 不自动续期，需自行刷新）"""
        if not self.access_token or time.time() >= self.token_expire_time:
            return self._fetch_access_token()
        return True

    async def connect(self) -> bool:
        """建立连接: 确保凭证有效且网关可达"""
        if not self._ensure_token():
            return False
        return self._verify_connection()

    async def disconnect(self):
        """断开连接并清理凭证"""
        self._initialized = False
        self.access_token = ""
        self.token_expire_time = 0
        logging.info("QQ adapter disconnected")

    def send_message(self, message: UnifiedMessage) -> bool:
        """发送QQ频道消息"""
        if not self._ensure_token():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[QQ模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        if not message.chat_id or not self._validate_resource_id(message.chat_id):
            logging.error("QQ消息发送失败: chat_id 缺失或含非法字符")
            return False

        try:
            headers = {**self._auth_headers(), "Content-Type": "application/json"}
            chat_type = (message.metadata or {}).get("chat_type", "")

            if chat_type == "group":
                # v2 群聊消息（主动推送已于 2025-04-21 停止，以被动回复为主）
                payload = self._build_v2_payload(message)
                resp = requests.post(
                    "https://api.sgroup.qq.com/v2/groups/" + message.chat_id + "/messages",
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
            elif chat_type in ("c2c", "single", "friend"):
                # v2 私聊（C2C）消息
                payload = self._build_v2_payload(message)
                resp = requests.post(
                    "https://api.sgroup.qq.com/v2/users/" + message.chat_id + "/messages",
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
            else:
                # 频道消息（默认）
                payload = {"content": message.content}
                if message.message_id:
                    payload["msg_id"] = message.message_id  # 回复时可携带原消息ID
                if self.message_merge:
                    payload["embed"] = {"title": "系统消息", "description": "此消息为合并发送"}
                resp = requests.post(
                    "https://api.sgroup.qq.com/channels/" + message.chat_id + "/messages",
                    headers=headers,
                    json=payload,
                    timeout=10,
                )

            if resp.status_code in self._OK_STATUS:
                return True

            logging.error("QQ消息发送失败 (HTTP %s): %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logging.error("QQ消息发送异常: %s", e)
            return False

    def _build_v2_payload(self, message: UnifiedMessage) -> Dict[str, Any]:
        """构造 v2 群聊/私聊消息体（content/msg_type/msg_id/msg_seq）"""
        metadata = message.metadata or {}
        payload: Dict[str, Any] = {
            "content": message.content,
            "msg_type": int(metadata.get("msg_type", 0)),  # 0 文本, 2 markdown, 3 ark, 4 embed
        }
        if message.message_id:
            payload["msg_id"] = message.message_id  # 被动回复标记（群 5 分钟/C2C 60 分钟有效）
            payload["msg_seq"] = int(metadata.get("msg_seq", 1))  # 同 msg_id 去重序号
        return payload

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

    # ============================================================
    # Webhook 验签（官方规范: Ed25519，见 wiki develop/api-v2 sign 页）
    # ============================================================

    def _derive_webhook_signing_key(self):
        """按官方规则派生 Ed25519 密钥对: Secret 倍增至 >=32 字节后截取前 32 字节作为 seed"""
        if not ED25519_AVAILABLE or not self.secret:
            return None
        seed = self.secret
        while len(seed) < 32:
            seed = seed * 2
        seed = seed[:32]
        return _Ed25519SigningKey.from_string(seed.encode("utf-8"), curve=_Ed25519Curve)

    def verify_webhook_signature(self, headers: Dict[str, str], body: str) -> bool:
        """验证 QQ 平台 Webhook 推送签名（官方 Ed25519 方案）

        - 签名值: 请求头 X-Signature-Ed25519（hex 编码的 64 字节 Ed25519 签名）
        - 签名输入: 请求头 X-Signature-Timestamp 原始字符串 + 原始请求体
        - 验签密钥: 由 Bot Secret 派生的公钥（平台侧持有同一 Secret，可派生相同密钥对）
        """
        if not self.secret or not ED25519_AVAILABLE:
            logging.error("QQ Webhook 验签不可用: 缺少 secret 或 ecdsa 库（pip install ecdsa）")
            return False

        signature_hex = (headers.get("X-Signature-Ed25519") or "").strip()
        timestamp = headers.get("X-Signature-Timestamp") or ""
        if not signature_hex or not timestamp:
            logging.warning("QQ Webhook 验签失败: 缺少签名请求头")
            return False

        try:
            signature = bytes.fromhex(signature_hex)
        except ValueError:
            logging.warning("QQ Webhook 验签失败: 签名不是合法 hex")
            return False

        # 官方校验: 64 字节定长且最高 3 bit 必须为 0（Ed25519 编码约束）
        if len(signature) != 64 or signature[63] & 224 != 0:
            logging.warning("QQ Webhook 验签失败: 签名长度或格式非法")
            return False

        signing_key = self._derive_webhook_signing_key()
        if signing_key is None:
            return False

        message = timestamp.encode("utf-8") + body.encode("utf-8")
        try:
            return signing_key.get_verifying_key().verify(signature, message)
        except Exception:
            logging.warning("QQ Webhook 验签失败: 签名不匹配")
            return False

    def build_webhook_validation_response(self, plain_token: str, event_ts: str) -> Dict[str, str]:
        """op 13 回调地址验证应答。

        平台配置回调地址时发送 op 13 验证请求（payload 含 plain_token/event_ts），
        需用 Bot Secret 派生的私钥对 event_ts + plain_token 签名并原样应答。
        """
        signing_key = self._derive_webhook_signing_key()
        if signing_key is None:
            raise RuntimeError("Ed25519 签名不可用: 缺少 secret 或 ecdsa 库（pip install ecdsa）")

        message = event_ts.encode("utf-8") + plain_token.encode("utf-8")
        signature = signing_key.sign(message)
        return {"plain_token": plain_token, "signature": signature.hex()}

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
