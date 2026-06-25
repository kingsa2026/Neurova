"""
微信消息渠道适配器

支持三种模式:
1. 企业微信 (Work WeChat) - 基于企业微信API
2. 微信个人账号 (iLink协议) - 基于扫码登录的个人微信Bot
3. 微信公众号 (Official Account) - 基于公众号API

iLink 协议说明:
- 微信个人账号 Bot 协议
- 首次启动若未配置 Bot Token，系统将打印二维码链接，请扫码登录
- Token 将自动保存到本地文件供后续使用
- iLink 平台限制: 每条用户消息对应的 context_token 最多只能回复 10 条消息

API 文档:
- 企业微信: https://developer.work.weixin.qq.com/document/path
- 微信公众号: https://developers.weixin.qq.com/doc/offiaccount/Getting_Started/Overview.html
"""
from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

from neurova.channels.base import ChannelAdapter, MessageChannel
from neurova.channels.models import ContentType, UnifiedMessage

from neurova.channels.wechat_auth import WeChatAuthMixin
from neurova.channels.wechat_parsing import WeChatParsingMixin
from neurova.channels.wechat_messaging import WeChatMessagingMixin
from neurova.channels.wechat_media import WeChatMediaMixin
from neurova.channels.wechat_ai_generation import WeChatAIGenerationMixin
from neurova.channels.wechat_ai_handler import WeChatAIHandlerMixin

logger = get_logger(__name__)


class WeChatAdapter(
    ChannelAdapter,
    WeChatAuthMixin,
    WeChatParsingMixin,
    WeChatMessagingMixin,
    WeChatMediaMixin,
    WeChatAIGenerationMixin,
    WeChatAIHandlerMixin,
):
    """
    微信消息渠道适配器

    支持模式:
    1. 企业微信应用消息 (wecom)
    2. 微信客服消息 (wecom + kf_mode)
    3. 微信个人账号 (iLink协议)
    4. 微信公众号 (official)

    Mixins:
    - WeChatAuthMixin: 认证逻辑 (企微/iLink/公众号)
    - WeChatParsingMixin: 消息解析
    - WeChatMessagingMixin: 消息发送与策略检查
    - WeChatMediaMixin: 媒体上传/下载
    - WeChatAIGenerationMixin: AI 生图/生视频
    - WeChatAIHandlerMixin: AI 生成请求处理
    """

    # 企业微信 API
    WECOM_API_BASE = "https://qyapi.weixin.qq.com"

    # 微信公众号 API
    WECHAT_OA_API_BASE = "https://api.weixin.qq.com"

    # iLink 协议 API (假设的端点，实际根据具体实现)
    ILINK_API_BASE = "https://ilink.wechat.bot"

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.WECHAT

    async def connect(self) -> bool:
        return True

    async def disconnect(self):
        pass

    async def send_message(self, chat_id: str, content: str, message_type: str = "text", **kwargs) -> Optional[str]:
        msg = UnifiedMessage(
            message_id="",
            channel=MessageChannel.WECHAT,
            content_type=ContentType.TEXT,
            content=content,
            user_id=chat_id,
            chat_id=chat_id,
            agent_id="",
            **kwargs,
        )
        WeChatMessagingMixin.send_message(self, msg)
        return ""

    def __init__(self):
        # 模式选择: wecom / ilink / official
        self.mode = "wecom"

        # ========== 企业微信配置 ==========
        self.corpid = ""
        self.corpsecret = ""
        self.agentid = ""
        self.access_token = ""
        self.token_expire_time = 0
        self._wecom_initialized = False

        # 微信客服模式
        self.kf_mode = False
        self.open_kfid = ""

        # 企业微信回调配置
        self.callback_token = ""
        self.encoding_aes_key = ""

        # ========== iLink 协议配置 ==========
        self.ilink_bot_token = ""
        self.ilink_token_file = ""
        self.ilink_media_dir = ""
        self.ilink_message_merge = False
        self.ilink_private_strategy = "open"
        self.ilink_group_strategy = "open"
        self.ilink_require_mention = False
        self.ilink_whitelist_users: List[str] = []
        self._ilink_initialized = False

        # ========== 微信公众号配置 ==========
        self.official_appid = ""
        self.official_secret = ""
        self.official_access_token = ""
        self.official_token_expire_time = 0
        self.official_token = ""  # 服务器配置Token
        self.official_encoding_aes_key = ""  # 消息加解密密钥
        self._official_initialized = False

        # 通用配置
        self.bot_prefix = "Kai"
        self.show_tool_messages = True
        self.show_thinking = True
        self.media_directory = ""
        self.private_chat_strategy = "open"
        self.group_chat_strategy = "open"
        self.require_mention = False
        self.whitelist_users: List[str] = []

        # 消息回复计数器 (iLink 限制)
        self._reply_counts: Dict[str, int] = {}

        # 初始化所有 Mixin 实例
        WeChatAuthMixin.__init__(self, self)
        WeChatParsingMixin.__init__(self, self)
        WeChatMessagingMixin.__init__(self, self)
        WeChatMediaMixin.__init__(self, self)
        WeChatAIGenerationMixin.__init__(self, self)
        WeChatAIHandlerMixin.__init__(self, self)

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证微信渠道

        参数:
        config: 配置字典，根据 mode 不同包含不同字段

        企业微信模式:
        {
            "mode": "wecom",
            "corpid": "企业ID",
            "corpsecret": "应用密钥",
            "agentid": "应用ID",
            "kf_mode": "true/false",
            "open_kfid": "客服账号ID",
            "token": "回调Token",
            "encoding_aes_key": "回调密钥",
        }

        iLink 模式:
        {
            "mode": "ilink",
            "bot_token": "Bot Token (可选，首次扫码后自动生成)",
            "token_file": "Token 文件路径",
            "media_directory": "媒体文件目录",
            "message_merge": "true/false",
            "private_strategy": "open/closed/whitelist",
            "group_strategy": "open/closed/whitelist",
            "require_mention": "true/false",
            "whitelist_users": "逗号分隔的用户ID",
        }

        公众号模式:
        {
            "mode": "official",
            "appid": "公众号AppID",
            "secret": "公众号AppSecret",
            "token": "服务器Token",
            "encoding_aes_key": "消息加解密密钥",
        }

        返回:
        认证成功返回 True
        """
        self.mode = config.get("mode", "wecom")

        # 解析通用配置
        self.bot_prefix = config.get("bot_prefix", self.bot_prefix)
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"
        self.media_directory = config.get("media_directory", "")
        self.private_chat_strategy = config.get("private_chat_strategy", "open")
        self.group_chat_strategy = config.get("group_chat_strategy", "open")
        self.require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist = config.get("whitelist_users", "")
        if whitelist:
            self.whitelist_users = [u.strip() for u in whitelist.split(",") if u.strip()]

        if self.mode == "ilink":
            return self._authenticate_ilink(config)
        elif self.mode == "official":
            return self._authenticate_official(config)
        else:
            return self._authenticate_wecom(config)

    # ============================================================
    # 用户管理 (企业微信/公众号)
    # ============================================================

    def get_user_info(self, user_id: str) -> Optional[Dict]:
        """
        获取用户信息

        参数:
        user_id: 用户 ID

        返回:
        用户信息字典
        """
        if self.mode == "wecom":
            return self._get_wecom_user_info(user_id)
        elif self.mode == "official":
            return self._get_official_user_info(user_id)
        return None

    def _get_wecom_user_info(self, user_id: str) -> Optional[Dict]:
        """获取企业微信用户信息"""
        if not self._ensure_wecom_token():
            return None

        data = self._api_request(
            self.WECOM_API_BASE,
            "GET",
            "/cgi-bin/user/get",
            params={"access_token": self.access_token, "userid": user_id},
        )

        if data.get("errcode") == 0:
            return data
        return None

    def _get_official_user_info(self, openid: str) -> Optional[Dict]:
        """获取微信公众号用户信息"""
        if not self._ensure_official_token():
            return None

        data = self._api_request(
            self.WECHAT_OA_API_BASE,
            "GET",
            "/cgi-bin/user/info",
            params={"access_token": self.official_access_token, "openid": openid, "lang": "zh_CN"},
        )

        if "openid" in data:
            return data
        return None

    # ============================================================
    # 配置管理
    # ============================================================

    def update_config(self, config_updates: Dict):
        """更新配置"""
        if self.mode == "ilink":
            if "bot_token" in config_updates:
                self.ilink_bot_token = config_updates["bot_token"]
            if "token_file" in config_updates:
                self.ilink_token_file = config_updates["token_file"]
            if "media_directory" in config_updates:
                self.ilink_media_dir = config_updates["media_directory"]
            if "message_merge" in config_updates:
                self.ilink_message_merge = config_updates["message_merge"]
            if "private_strategy" in config_updates:
                self.ilink_private_strategy = config_updates["private_strategy"]
            if "group_strategy" in config_updates:
                self.ilink_group_strategy = config_updates["group_strategy"]
            if "require_mention" in config_updates:
                self.ilink_require_mention = config_updates["require_mention"]
            if "whitelist_users" in config_updates:
                whitelist = config_updates["whitelist_users"]
                self.ilink_whitelist_users = (
                    [u.strip() for u in str(whitelist).split(",") if u.strip()] if whitelist else []
                )
        elif self.mode == "wecom":
            if "corpid" in config_updates:
                self.corpid = config_updates["corpid"]
            if "corpsecret" in config_updates:
                self.corpsecret = config_updates["corpsecret"]
            if "agentid" in config_updates:
                self.agentid = config_updates["agentid"]
            if "kf_mode" in config_updates:
                self.kf_mode = config_updates["kf_mode"]
            if "open_kfid" in config_updates:
                self.open_kfid = config_updates["open_kfid"]
        elif self.mode == "official":
            if "appid" in config_updates:
                self.official_appid = config_updates["appid"]
            if "secret" in config_updates:
                self.official_secret = config_updates["secret"]

        # 通用配置
        if "bot_prefix" in config_updates:
            self.bot_prefix = config_updates["bot_prefix"]
        if "show_tool_messages" in config_updates:
            self.show_tool_messages = config_updates["show_tool_messages"]
        if "show_thinking" in config_updates:
            self.show_thinking = config_updates["show_thinking"]
        if "private_chat_strategy" in config_updates:
            self.private_chat_strategy = config_updates["private_chat_strategy"]
        if "group_chat_strategy" in config_updates:
            self.group_chat_strategy = config_updates["group_chat_strategy"]
        if "require_mention" in config_updates:
            self.require_mention = config_updates["require_mention"]
        if "whitelist_users" in config_updates:
            whitelist = config_updates["whitelist_users"]
            self.whitelist_users = [u.strip() for u in str(whitelist).split(",") if u.strip()] if whitelist else []

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置信息"""
        base_config = {
            "channel": self.channel.value,
            "mode": self.mode,
            "bot_prefix": self.bot_prefix,
            "show_tool_messages": self.show_tool_messages,
            "show_thinking": self.show_thinking,
            "private_chat_strategy": self.private_chat_strategy,
            "group_chat_strategy": self.group_chat_strategy,
            "require_mention": self.require_mention,
            "whitelist_users": self.whitelist_users,
            "media_directory": self.media_directory,
        }

        if self.mode == "ilink":
            base_config.update(
                {
                    "token_file": self.ilink_token_file,
                    "message_merge": self.ilink_message_merge,
                    "authenticated": self._ilink_initialized,
                }
            )
        elif self.mode == "wecom":
            base_config.update(
                {
                    "corpid": self.corpid,
                    "agentid": self.agentid,
                    "kf_mode": self.kf_mode,
                    "authenticated": self._wecom_initialized,
                }
            )
        elif self.mode == "official":
            base_config.update(
                {
                    "appid": self.official_appid,
                    "authenticated": self._official_initialized,
                }
            )

        return base_config


def create_wechat_adapter(
    corpid: str = "", corpsecret: str = "", agentid: str = "", mode: str = "wecom", **kwargs
) -> WeChatAdapter:
    """
    创建微信适配器

    参数:
    corpid: 企业ID (企业微信模式)
    corpsecret: 应用密钥 (企业微信模式)
    agentid: 应用ID (企业微信模式)
    mode: 模式 (wecom / ilink / official)
    **kwargs: 其他配置项

    返回:
    微信适配器实例
    """
    adapter = WeChatAdapter()
    adapter.mode = mode

    if mode == "ilink":
        # iLink 模式使用配置文件认证
        if kwargs:
            adapter.authenticate({"mode": "ilink", **kwargs})
    elif mode == "official":
        # 公众号模式
        if kwargs:
            adapter.authenticate({"mode": "official", **kwargs})
    elif corpid and corpsecret:
        adapter.authenticate(
            {
                "mode": "wecom",
                "corpid": corpid,
                "corpsecret": corpsecret,
                "agentid": agentid,
                **kwargs,
            }
        )

    return adapter
