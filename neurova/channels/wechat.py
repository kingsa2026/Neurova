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

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

try:
    import re

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("requests 库未安装，微信适配器将使用模拟模式")

try:
    pass

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logging.warning("httpx 库未安装，部分AI生成功能可能不可用")

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage


class WeChatAdapter(ChannelAdapter):
    """
    微信消息渠道适配器

    支持模式:
    1. 企业微信应用消息 (wecom)
    2. 微信客服消息 (wecom + kf_mode)
    3. 微信个人账号 (iLink协议)
    4. 微信公众号 (official)
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
    # 企业微信认证
    # ============================================================

    def _authenticate_wecom(self, config: Dict[str, str]) -> bool:
        """认证企业微信"""
        self.corpid = config.get("corpid", "")
        self.corpsecret = config.get("corpsecret", "")
        self.agentid = config.get("agentid", "")
        self.kf_mode = config.get("kf_mode", "false").lower() == "true"
        self.open_kfid = config.get("open_kfid", "")
        self.callback_token = config.get("token", "")
        self.encoding_aes_key = config.get("encoding_aes_key", "")

        if not self.corpid or not self.corpsecret:
            logging.error("企业微信认证失败: corpid 和 corpsecret 不能为空")
            return False

        if self.kf_mode and not self.open_kfid:
            logging.error("微信客服模式需要提供 open_kfid")
            return False

        return self._refresh_wecom_token()

    def _refresh_wecom_token(self) -> bool:
        """刷新企业微信 access_token"""
        if not REQUESTS_AVAILABLE:
            self._wecom_initialized = True
            return True

        try:
            url = f"{self.WECOM_API_BASE}/cgi-bin/gettoken"
            params = {
                "corpid": self.corpid,
                "corpsecret": self.corpsecret,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if data.get("errcode") == 0:
                self.access_token = data["access_token"]
                self.token_expire_time = int(time.time()) + data.get("expires_in", 7200) - 60
                self._wecom_initialized = True
                logging.info("企业微信认证成功")
                return True
            else:
                logging.error("企业微信认证失败: %s", data)
                return False
        except (requests.RequestException, json.JSONDecodeError) as e:
            logging.error("企业微信认证异常: %s", e)
            return False

    def _ensure_wecom_token(self) -> bool:
        """确保企业微信 token 有效"""
        if not self._wecom_initialized:
            return self._refresh_wecom_token()
        if int(time.time()) >= self.token_expire_time:
            return self._refresh_wecom_token()
        return True

    # ============================================================
    # iLink 协议认证
    # ============================================================

    def _authenticate_ilink(self, config: Dict[str, str]) -> bool:
        """
        认证 iLink 协议

        流程:
        1. 如果提供了 bot_token，直接使用
        2. 如果没有 token，生成二维码URL，等待扫码
        3. 扫码成功后，token 保存到本地文件
        """
        self.ilink_bot_token = config.get("bot_token", "")
        self.ilink_token_file = config.get("token_file", "~/.Neurova/weixin_bot_token")
        self.ilink_media_dir = config.get("media_directory", "")
        self.ilink_message_merge = config.get("message_merge", "false").lower() == "true"
        self.ilink_private_strategy = config.get("private_strategy", "open")
        self.ilink_group_strategy = config.get("group_strategy", "open")
        self.ilink_require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist = config.get("whitelist_users", "")
        self.ilink_whitelist_users = [u.strip() for u in whitelist.split(",") if u.strip()] if whitelist else []

        # 扩展 token_file 路径
        if self.ilink_token_file.startswith("~"):
            self.ilink_token_file = str(Path(self.ilink_token_file).expanduser())

        # 如果已有 token，直接验证
        if self.ilink_bot_token:
            return self._verify_ilink_token()

        # 尝试从文件加载 token
        token_path = Path(self.ilink_token_file)
        if token_path.exists():
            try:
                with open(token_path, "r") as f:
                    self.ilink_bot_token = f.read().strip()
                if self.ilink_bot_token:
                    logging.info("从文件加载 iLink Token: %s", self.ilink_token_file)
                    return self._verify_ilink_token()
            except (OSError, IOError) as e:
                logging.warning("加载 Token 文件失败: %s", e)

        # 首次启动，需要扫码登录
        logging.info("iLink 协议首次启动，需要扫码登录")
        return self._generate_qr_code()

    def _generate_qr_code(self) -> bool:
        """
        生成登录二维码

        返回:
        如果请求成功返回 True (需要用户扫码)
        """
        if not REQUESTS_AVAILABLE:
            logging.info("[iLink 模拟] 生成二维码链接: https://ilink.wechat.bot/qr/xxxxx")
            self._ilink_initialized = True
            return True

        try:
            url = f"{self.ILINK_API_BASE}/auth/qrcode"
            resp = requests.post(url, timeout=10)
            data = resp.json()

            if data.get("success"):
                qr_url = data.get("qr_code_url", "")
                qr_id = data.get("qr_id", "")
                logging.info("iLink 登录二维码: %s", qr_url)
                logging.info("请扫码登录，QR ID: %s", qr_id)

                # 轮询等待扫码
                return self._wait_for_scan(qr_id)
            else:
                logging.error("生成二维码失败: %s", data)
                return False
        except (requests.RequestException, json.JSONDecodeError) as e:
            logging.error("生成二维码异常: %s", e)
            return False

    def _wait_for_scan(self, qr_id: str, timeout: int = 300) -> bool:
        """
        等待用户扫码登录

        参数:
        qr_id: 二维码ID
        timeout: 超时时间 (秒)
        """
        if not REQUESTS_AVAILABLE:
            self._ilink_initialized = True
            return True

        start_time = time.time()
        poll_interval = 3

        while time.time() - start_time < timeout:
            try:
                url = f"{self.ILINK_API_BASE}/auth/status"
                resp = requests.get(url, params={"qr_id": qr_id}, timeout=10)
                data = resp.json()

                status = data.get("status", "")
                if status == "scanned":
                    logging.info("二维码已扫描，等待确认...")
                elif status == "confirmed":
                    self.ilink_bot_token = data.get("bot_token", "")
                    self._save_ilink_token()
                    self._ilink_initialized = True
                    logging.info("iLink 登录成功!")
                    return True
                elif status == "expired":
                    logging.error("二维码已过期，请重新生成")
                    return False

                time.sleep(poll_interval)
            except (requests.RequestException, json.JSONDecodeError) as e:
                logging.error("轮询扫码状态异常: %s", e)
                time.sleep(poll_interval)

        logging.error("扫码登录超时")
        return False

    def _verify_ilink_token(self) -> bool:
        """验证 iLink Token 是否有效"""
        if not REQUESTS_AVAILABLE:
            self._ilink_initialized = True
            return True

        try:
            url = f"{self.ILINK_API_BASE}/auth/verify"
            headers = {"Authorization": f"Bearer {self.ilink_bot_token}"}
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()

            if data.get("valid", False):
                self._ilink_initialized = True
                logging.info("iLink Token 验证成功")
                return True
            else:
                logging.error("iLink Token 无效，需要重新登录")
                self.ilink_bot_token = ""
                return False
        except (requests.RequestException, json.JSONDecodeError) as e:
            logging.error("验证 Token 异常: %s", e)
            return False

    def _save_ilink_token(self):
        """保存 iLink Token 到本地文件"""
        if not self.ilink_token_file:
            return

        try:
            token_path = Path(self.ilink_token_file)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as f:
                f.write(self.ilink_bot_token)
            logging.info("iLink Token 已保存到: %s", self.ilink_token_file)
        except (OSError, IOError) as e:
            logging.error("保存 Token 失败: %s", e)

    # ============================================================
    # 微信公众号认证
    # ============================================================

    def _authenticate_official(self, config: Dict[str, str]) -> bool:
        """认证微信公众号"""
        self.official_appid = config.get("appid", "")
        self.official_secret = config.get("secret", "")
        self.official_token = config.get("token", "")
        self.official_encoding_aes_key = config.get("encoding_aes_key", "")

        if not self.official_appid or not self.official_secret:
            logging.error("微信公众号认证失败: appid 和 secret 不能为空")
            return False

        return self._refresh_official_token()

    def _refresh_official_token(self) -> bool:
        """刷新微信公众号 access_token"""
        if not REQUESTS_AVAILABLE:
            self._official_initialized = True
            return True

        try:
            url = f"{self.WECHAT_OA_API_BASE}/cgi-bin/token"
            params = {
                "grant_type": "client_credential",
                "appid": self.official_appid,
                "secret": self.official_secret,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if "access_token" in data:
                self.official_access_token = data["access_token"]
                self.official_token_expire_time = int(time.time()) + data.get("expires_in", 7200) - 60
                self._official_initialized = True
                logging.info("微信公众号认证成功")
                return True
            else:
                logging.error("微信公众号认证失败: %s", data)
                return False
        except Exception as e:
            logging.error("微信公众号认证异常: %s", e)
            return False

    def _ensure_official_token(self) -> bool:
        """确保微信公众号 token 有效"""
        if not self._official_initialized:
            return self._refresh_official_token()
        if int(time.time()) >= self.official_token_expire_time:
            return self._refresh_official_token()
        return True

    # ============================================================
    # 统一 API 请求方法
    # ============================================================

    def _api_request(self, base_url: str, method: str, path: str, params: Dict = None, **kwargs) -> Dict[str, Any]:
        """
        统一的 API 请求方法

        参数:
        base_url: API 基础 URL
        method: HTTP 方法
        path: API 路径
        params: URL 参数
        **kwargs: requests 的其他参数

        返回:
        API 响应数据
        """
        if not REQUESTS_AVAILABLE:
            return {"errcode": -1, "errmsg": "requests 库未安装"}

        url = f"{base_url}{path}"
        kwargs.setdefault("timeout", 10)

        try:
            resp = requests.request(method, url, params=params, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logging.error("微信 API 请求超时: %s", url)
            return {"errcode": -1, "errmsg": "请求超时"}
        except requests.exceptions.HTTPError as e:
            logging.error("微信 API HTTP 错误: %s", e)
            return {"errcode": -1, "errmsg": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            logging.error("微信 API 请求异常: %s", e)
            return {"errcode": -1, "errmsg": str(e)}

    # ============================================================
    # 消息发送
    # ============================================================

    def send_message(self, message: UnifiedMessage) -> bool:
        """
        发送微信消息

        参数:
        message: 统一消息对象

        返回:
        发送成功返回 True
        """
        if self.mode == "ilink":
            return self._send_ilink_message(message)
        elif self.mode == "official":
            return self._send_official_message(message)
        else:
            return self._send_wecom_message(message)

    def _send_wecom_message(self, message: UnifiedMessage) -> bool:
        """发送企业微信消息"""
        if not self._ensure_wecom_token():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[企微模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            if self.kf_mode:
                return self._send_kf_message(message)
            else:
                return self._send_app_message(message)
        except Exception as e:
            logging.error("企业微信消息发送异常: %s", e)
            return False

    def _send_app_message(self, message: UnifiedMessage) -> bool:
        """发送企业微信应用消息"""
        url = f"{self.WECOM_API_BASE}/cgi-bin/message/send"
        params = {"access_token": self.access_token}

        payload = {
            "touser": message.chat_id,
            "msgtype": "text",
            "agentid": int(self.agentid) if self.agentid else 0,
            "text": {"content": message.content},
        }

        if message.content_type == ContentType.IMAGE:
            payload["msgtype"] = "image"
            payload["image"] = {"media_id": message.file_url}
        elif message.content_type == ContentType.VOICE:
            payload["msgtype"] = "voice"
            payload["voice"] = {"media_id": message.file_url}
        elif message.content_type == ContentType.VIDEO:
            payload["msgtype"] = "video"
            payload["video"] = {
                "media_id": message.file_url,
                "title": message.file_name or "视频",
                "description": message.content or "",
            }
        elif message.content_type == ContentType.FILE:
            payload["msgtype"] = "file"
            payload["file"] = {"media_id": message.file_url}

        resp = requests.post(url, params=params, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode") == 0:
            logging.info("企业微信消息发送成功: %s", message.chat_id)
            return True
        else:
            logging.error("企业微信消息发送失败: %s", data)
            return False

    def _send_kf_message(self, message: UnifiedMessage) -> bool:
        """发送微信客服消息"""
        url = f"{self.WECOM_API_BASE}/cgi-bin/kf/send_msg"
        params = {"access_token": self.access_token}

        payload = {
            "touser": message.chat_id,
            "open_kfid": self.open_kfid,
            "msgtype": "text",
            "text": {"content": message.content},
        }

        resp = requests.post(url, params=params, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode") == 0:
            logging.info("微信客服消息发送成功: %s", message.chat_id)
            return True
        else:
            logging.error("微信客服消息发送失败: %s", data)
            return False

    def _send_ilink_message(self, message: UnifiedMessage) -> bool:
        """
        发送 iLink 协议消息

        iLink 限制: context_token 最多回复 10 条消息
        建议关闭思考及工具输出，或使用消息合并功能
        """
        if not self._ilink_initialized:
            logging.error("iLink 未初始化，请先扫码登录")
            return False

        # 检查回复次数限制
        session_key = f"{message.chat_id}:{message.session_id}"
        reply_count = self._reply_counts.get(session_key, 0)
        if reply_count >= 10:
            logging.warning("iLink 回复次数已达上限 (10次): %s", session_key)
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[iLink 模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            self._reply_counts[session_key] = reply_count + 1
            return True

        try:
            url = f"{self.ILINK_API_BASE}/message/send"
            headers = {"Authorization": f"Bearer {self.ilink_bot_token}"}

            payload = {
                "to_user": message.chat_id,
                "content": message.content,
                "msg_type": message.content_type.value,
            }

            # 如果启用消息合并，添加合并标识
            if self.ilink_message_merge:
                payload["merge"] = True

            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()

            if data.get("success"):
                self._reply_counts[session_key] = reply_count + 1
                return True
            else:
                logging.error("iLink 消息发送失败: %s", data)
                return False
        except Exception as e:
            logging.error("iLink 消息发送异常: %s", e)
            return False

    def _send_official_message(self, message: UnifiedMessage) -> bool:
        """发送微信公众号客服消息"""
        if not self._ensure_official_token():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[公众号模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            url = f"{self.WECHAT_OA_API_BASE}/cgi-bin/message/custom/send"
            params = {"access_token": self.official_access_token}

            payload = {
                "touser": message.chat_id,
                "msgtype": "text",
                "text": {"content": message.content},
            }

            if message.content_type == ContentType.IMAGE:
                payload["msgtype"] = "image"
                payload["image"] = {"media_id": message.file_url}
            elif message.content_type == ContentType.VOICE:
                payload["msgtype"] = "voice"
                payload["voice"] = {"media_id": message.file_url}
            elif message.content_type == ContentType.VIDEO:
                payload["msgtype"] = "video"
                payload["video"] = {
                    "media_id": message.file_url,
                    "title": message.file_name or "视频",
                    "description": message.content or "",
                }
            elif message.content_type == ContentType.CARD:
                payload["msgtype"] = "news"
                payload["news"] = {
                    "articles": [
                        {
                            "title": message.card_data.get("title", ""),
                            "description": message.card_data.get("description", ""),
                            "url": message.card_data.get("url", ""),
                            "picurl": message.card_data.get("picurl", ""),
                        }
                    ]
                }

            resp = requests.post(url, params=params, json=payload, timeout=10)
            data = resp.json()

            if data.get("errcode", 0) == 0:
                logging.info("微信公众号客服消息发送成功: %s", message.chat_id)
                return True
            else:
                logging.error("微信公众号客服消息发送失败: %s", data)
                return False
        except Exception as e:
            logging.error("微信公众号消息发送异常: %s", e)
            return False

    # ============================================================
    # 消息接收与解析
    # ============================================================

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收消息 (需通过 Webhook 回调)"""
        logging.warning("微信消息接收请使用 Webhook 模式")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析微信原始消息

        参数:
        raw_data: 微信原始消息数据 (dict/XML字符串/iLink JSON)

        返回:
        统一消息对象
        """
        if self.mode == "ilink":
            return self._parse_ilink_message(raw_data)
        elif self.mode == "official":
            return self._parse_official_message(raw_data)
        else:
            return self._parse_wecom_message(raw_data)

    def _parse_wecom_message(self, raw_data: Any) -> UnifiedMessage:
        """解析企业微信原始消息"""
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                return self._parse_xml_message(raw_data)

        if self.kf_mode:
            return self._parse_kf_message(raw_data)

        msg_type = raw_data.get("MsgType", "text")
        from_user = raw_data.get("FromUserName", "")
        content = ""
        content_type = ContentType.TEXT
        timestamp = None

        # 解析时间戳
        if "CreateTime" in raw_data:
            try:
                timestamp = datetime.fromtimestamp(int(raw_data["CreateTime"]))
            except (ValueError, TypeError):
                timestamp = datetime.now()

        # 解析消息内容
        if msg_type == "text":
            content = raw_data.get("Content", "")
        elif msg_type == "image":
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg_type == "voice":
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg_type == "video":
            content_type = ContentType.VIDEO
            content = "[视频]"
        elif msg_type == "file":
            content_type = ContentType.FILE
            content = "[文件]"
        elif msg_type == "location":
            content_type = ContentType.LOCATION
            content = f"[位置] Lat:{raw_data.get('Location_X', '')}, Lng:{raw_data.get('Location_Y', '')}"
        elif msg_type == "event":
            event = raw_data.get("Event", "")
            if event == "subscribe":
                content = "[关注事件]"
            elif event == "unsubscribe":
                content = "[取消关注事件]"
            elif event == "CLICK":
                content = f"[菜单点击: {raw_data.get('EventKey', '')}]"
            else:
                content = f"[事件: {event}]"
            content_type = ContentType.SYSTEM

        return UnifiedMessage(
            message_id=raw_data.get("MsgId", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=from_user,
            user_id=from_user,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            raw_message=raw_data,
            metadata={
                "msg_type": msg_type,
                "agent_id": raw_data.get("AgentID", ""),
                "pic_url": raw_data.get("PicUrl", ""),
                "media_id": raw_data.get("MediaId", ""),
                "event": raw_data.get("Event", ""),
                "event_key": raw_data.get("EventKey", ""),
            },
        )

    def _parse_ilink_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析 iLink 协议消息

        iLink 消息格式 (假设):
        {
            "msg_id": "xxx",
            "from_user": "wxid_xxx",
            "to_user": "bot_wxid",
            "content": "消息内容",
            "msg_type": "text",
            "chat_type": "single/group",
            "chat_id": "群ID或个人ID",
            "timestamp": 1234567890,
            "mention_list": ["@bot_wxid"],
            "is_group": false,
        }
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                raw_data = {}

        msg_type = raw_data.get("msg_type", "text")
        from_user = raw_data.get("from_user", "")
        content = raw_data.get("content", "")
        chat_type = raw_data.get("chat_type", "single")
        chat_id = raw_data.get("chat_id", from_user)
        timestamp_raw = raw_data.get("timestamp")

        # 从 datetime 转换
        ts = None
        if timestamp_raw:
            try:
                ts = datetime.fromtimestamp(timestamp_raw)
            except (ValueError, TypeError):
                ts = datetime.now()
        else:
            ts = datetime.now()

        # 确定内容类型
        content_type = ContentType.TEXT
        if msg_type == "image":
            content_type = ContentType.IMAGE
        elif msg_type == "voice":
            content_type = ContentType.VOICE
        elif msg_type == "video":
            content_type = ContentType.VIDEO
        elif msg_type == "file":
            content_type = ContentType.FILE
        elif msg_type == "location":
            content_type = ContentType.LOCATION

        # 检查是否需要 @提及
        if self.ilink_require_mention and chat_type == "group":
            mention_list = raw_data.get("mention_list", [])
            bot_id = raw_data.get("to_user", "")
            if bot_id not in mention_list:
                logging.debug("群消息未@机器人，忽略")

        # 检查策略
        if not self.should_process_message(raw_data):
            logging.debug("消息被策略过滤: %s, user=%s", chat_type, from_user)

        return UnifiedMessage(
            message_id=raw_data.get("msg_id", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=chat_id,
            user_id=from_user,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=ts,
            raw_message=raw_data,
            metadata={
                "msg_type": msg_type,
                "chat_type": chat_type,
                "is_group": raw_data.get("is_group", False),
                "mention_list": raw_data.get("mention_list", []),
                "to_user": raw_data.get("to_user", ""),
                "file_url": raw_data.get("file_url", ""),
                "file_name": raw_data.get("file_name", ""),
            },
        )

    def _parse_official_message(self, raw_data: Any) -> UnifiedMessage:
        """解析微信公众号原始消息"""
        # 公众号消息通常是 XML 格式
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                return self._parse_xml_message(raw_data)

        msg_type = raw_data.get("MsgType", "text")
        from_user = raw_data.get("FromUserName", "")
        content = ""
        content_type = ContentType.TEXT
        timestamp = None

        if "CreateTime" in raw_data:
            try:
                timestamp = datetime.fromtimestamp(int(raw_data["CreateTime"]))
            except (ValueError, TypeError):
                timestamp = datetime.now()

        if msg_type == "text":
            content = raw_data.get("Content", "")
        elif msg_type == "image":
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg_type == "voice":
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg_type == "video":
            content_type = ContentType.VIDEO
            content = "[视频]"
        elif msg_type == "location":
            content_type = ContentType.LOCATION
            content = f"[位置] Lat:{raw_data.get('Location_X', '')}, Lng:{raw_data.get('Location_Y', '')}"
        elif msg_type == "event":
            event = raw_data.get("Event", "")
            if event == "subscribe":
                content = "[关注事件]"
            elif event == "unsubscribe":
                content = "[取消关注事件]"
            elif event == "CLICK":
                content = f"[菜单点击: {raw_data.get('EventKey', '')}]"
            else:
                content = f"[事件: {event}]"
            content_type = ContentType.SYSTEM

        return UnifiedMessage(
            message_id=raw_data.get("MsgId", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=from_user,
            user_id=from_user,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            raw_message=raw_data,
            metadata={
                "msg_type": msg_type,
                "event": raw_data.get("Event", ""),
                "event_key": raw_data.get("EventKey", ""),
                "pic_url": raw_data.get("PicUrl", ""),
                "media_id": raw_data.get("MediaId", ""),
            },
        )

    def _parse_xml_message(self, xml_data: str) -> UnifiedMessage:
        """解析 XML 格式消息"""
        try:
            root = ET.fromstring(xml_data)

            def get_text(tag):
                elem = root.find(tag)
                return elem.text if elem is not None else ""

            msg_type = get_text("MsgType")
            from_user = get_text("FromUserName")
            content = get_text("Content") if msg_type == "text" else ""
            msg_id = get_text("MsgId") or str(int(time.time()))

            create_time = get_text("CreateTime")
            timestamp = None
            if create_time:
                try:
                    timestamp = datetime.fromtimestamp(int(create_time))
                except (ValueError, TypeError):
                    timestamp = datetime.now()

            content_type = ContentType.TEXT
            if msg_type == "image":
                content_type = ContentType.IMAGE
                content = "[图片]"
            elif msg_type == "voice":
                content_type = ContentType.VOICE
                content = "[语音]"
            elif msg_type == "video":
                content_type = ContentType.VIDEO
                content = "[视频]"
            elif msg_type == "location":
                content_type = ContentType.LOCATION
                content = f"[位置] Lat:{get_text('Location_X')}, Lng:{get_text('Location_Y')}"
            elif msg_type == "event":
                content_type = ContentType.SYSTEM
                event = get_text("Event")
                content = f"[事件: {event}]"

            return UnifiedMessage(
                message_id=msg_id,
                channel=MessageChannel.WECHAT,
                chat_id=from_user,
                user_id=from_user,
                agent_id="",
                content=content,
                content_type=content_type,
                timestamp=timestamp,
                raw_message=xml_data,
                metadata={
                    "msg_type": msg_type,
                    "event": get_text("Event"),
                    "event_key": get_text("EventKey"),
                    "pic_url": get_text("PicUrl"),
                    "media_id": get_text("MediaId"),
                },
            )
        except ET.ParseError as e:
            logging.error("XML 解析失败: %s", e)
            return UnifiedMessage(
                message_id=str(int(time.time())),
                channel=MessageChannel.WECHAT,
                chat_id="",
                user_id="",
                agent_id="",
                content="",
                content_type=ContentType.TEXT,
                timestamp=datetime.now(),
                raw_message=xml_data,
                metadata={"error": f"XML 解析失败: {e}"},
            )

    def _parse_kf_message(self, data: Dict) -> UnifiedMessage:
        """解析微信客服消息"""
        msg_list = data.get("msg_list", [])
        if not msg_list:
            return UnifiedMessage(
                message_id=str(int(time.time())),
                channel=MessageChannel.WECHAT,
                chat_id="",
                user_id="",
                agent_id="",
                content="",
                content_type=ContentType.TEXT,
                timestamp=datetime.now(),
                raw_message=data,
                metadata={"error": "空消息列表"},
            )

        msg = msg_list[0]
        msg_type = msg.get("msgtype", "text")
        external_userid = msg.get("external_userid", "")

        content = ""
        content_type = ContentType.TEXT

        if msg_type == "text":
            content = msg.get("text", {}).get("content", "")
        elif msg_type == "image":
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg_type == "voice":
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg_type == "video":
            content_type = ContentType.VIDEO
            content = "[视频]"

        return UnifiedMessage(
            message_id=msg.get("msgid", str(int(time.time()))),
            channel=MessageChannel.WECHAT,
            chat_id=external_userid,
            user_id=external_userid,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=datetime.now(),
            raw_message=data,
            metadata={
                "msg_type": msg_type,
                "open_kfid": msg.get("open_kfid", ""),
            },
        )

    # ============================================================
    # 策略检查
    # ============================================================

    def should_process_message(self, raw_data: Dict) -> bool:
        """
        判断是否应该处理消息 (策略检查)

        主要用于 iLink 模式的群聊策略和白名单检查
        """
        if self.mode != "ilink":
            return True

        chat_type = raw_data.get("chat_type", "single")
        from_user = raw_data.get("from_user", "")

        # 私聊策略
        if chat_type == "single":
            if self.ilink_private_strategy == "closed":
                return False
            if self.ilink_private_strategy == "whitelist":
                return from_user in self.ilink_whitelist_users

        # 群聊策略
        if chat_type == "group":
            if self.ilink_group_strategy == "closed":
                return False
            if self.ilink_group_strategy == "whitelist":
                return from_user in self.ilink_whitelist_users
            if self.ilink_require_mention:
                mention_list = raw_data.get("mention_list", [])
                bot_id = raw_data.get("to_user", "")
                return bot_id in mention_list

        return True

    # ============================================================
    # 签名验证 (企业微信/公众号回调)
    # ============================================================

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, echostr: str = "") -> Optional[str]:
        """
        验证企业微信/公众号回调签名

        返回 echostr 表示验证通过
        """
        if not self.callback_token and not self.official_token:
            return None

        token = self.callback_token or self.official_token
        params = sorted([token, timestamp, nonce])
        sign_str = "".join(params)
        signature = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

        if signature == msg_signature:
            return echostr
        return None

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
    # 媒体上传与下载
    # ============================================================

    def upload_media(
        self, file_path: str, media_type: str = "image", title: str = "", description: str = ""
    ) -> Optional[str]:
        """
        上传媒体文件到微信服务器

        参数:
        file_path: 媒体文件路径
        media_type: 媒体类型 (image/voice/video/file)
        title: 视频标题 (仅视频类型需要)
        description: 视频描述 (仅视频类型需要)

        返回:
        成功返回 media_id，失败返回 None
        """
        if self.mode == "official":
            return self._upload_official_media(file_path, media_type)
        elif self.mode == "ilink":
            return self._upload_ilink_media(file_path, media_type)
        else:
            return self._upload_wecom_media(file_path, media_type, title, description)

    def _upload_wecom_media(
        self, file_path: str, media_type: str, title: str = "", description: str = ""
    ) -> Optional[str]:
        """上传媒体文件到企业微信"""
        if not self._ensure_wecom_token():
            logging.error("企业微信 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[企微模拟] 上传媒体: %s, 类型: %s", file_path, media_type)
            return f"mock_media_id_{int(time.time())}"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logging.error("媒体文件不存在: %s", file_path)
            return None

        try:
            url = f"{self.WECOM_API_BASE}/cgi-bin/media/upload"
            params = {
                "access_token": self.access_token,
                "type": media_type,
            }

            with open(file_path_obj, "rb") as f:
                files = {"media": (file_path_obj.name, f)}

                if media_type == "video":
                    data = {
                        "description": json.dumps(
                            {
                                "title": title or file_path_obj.stem,
                                "introduction": description or "",
                            }
                        )
                    }
                    resp = requests.post(url, params=params, files=files, data=data, timeout=30)
                else:
                    resp = requests.post(url, params=params, files=files, timeout=30)

            result = resp.json()

            if result.get("errcode") == 0:
                media_id = result.get("media_id")
                logging.info("企业微信媒体上传成功: %s", media_id)
                return media_id
            else:
                logging.error("企业微信媒体上传失败: %s", result)
                return None
        except requests.exceptions.Timeout:
            logging.error("媒体上传超时: %s", file_path)
            return None
        except requests.exceptions.HTTPError as e:
            logging.error("媒体上传 HTTP 错误: %s", e)
            return None
        except IOError as e:
            logging.error("读取媒体文件失败: %s", e)
            return None
        except Exception as e:
            logging.error("媒体上传异常: %s", e)
            return None

    def _upload_official_media(self, file_path: str, media_type: str) -> Optional[str]:
        """上传媒体文件到微信公众号"""
        if not self._ensure_official_token():
            logging.error("微信公众号 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[公众号模拟] 上传媒体: %s, 类型: %s", file_path, media_type)
            return f"mock_official_media_id_{int(time.time())}"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logging.error("媒体文件不存在: %s", file_path)
            return None

        try:
            url = f"{self.WECHAT_OA_API_BASE}/cgi-bin/media/upload"
            params = {
                "access_token": self.official_access_token,
                "type": media_type,
            }

            with open(file_path_obj, "rb") as f:
                files = {"media": (file_path_obj.name, f)}
                resp = requests.post(url, params=params, files=files, timeout=30)

            result = resp.json()

            if result.get("errcode") == 0:
                media_id = result.get("media_id")
                logging.info("微信公众号媒体上传成功: %s", media_id)
                return media_id
            else:
                logging.error("微信公众号媒体上传失败: %s", result)
                return None
        except Exception as e:
            logging.error("微信公众号媒体上传异常: %s", e)
            return None

    def _upload_ilink_media(self, file_path: str, media_type: str) -> Optional[str]:
        """上传媒体文件到 iLink"""
        if not self._ilink_initialized:
            logging.error("iLink 未初始化")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[iLink 模拟] 上传媒体: %s, 类型: %s", file_path, media_type)
            return f"mock_ilink_media_id_{int(time.time())}"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logging.error("媒体文件不存在: %s", file_path)
            return None

        try:
            url = f"{self.ILINK_API_BASE}/media/upload"
            headers = {"Authorization": f"Bearer {self.ilink_bot_token}"}

            with open(file_path_obj, "rb") as f:
                files = {"file": (file_path_obj.name, f)}
                data = {"type": media_type}
                resp = requests.post(url, headers=headers, data=data, files=files, timeout=30)

            result = resp.json()

            if result.get("success"):
                media_id = result.get("media_id")
                logging.info("iLink 媒体上传成功: %s", media_id)
                return media_id
            else:
                logging.error("iLink 媒体上传失败: %s", result)
                return None
        except Exception as e:
            logging.error("iLink 媒体上传异常: %s", e)
            return None

    def download_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """
        从微信服务器下载媒体文件

        参数:
        media_id: 媒体文件 ID
        save_path: 保存路径 (为空则返回二进制数据)

        返回:
        成功返回二进制数据 (或保存后返回数据)，失败返回 None
        """
        if self.mode == "official":
            return self._download_official_media(media_id, save_path)
        elif self.mode == "ilink":
            return self._download_ilink_media(media_id, save_path)
        else:
            return self._download_wecom_media(media_id, save_path)

    def _download_wecom_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """从企业微信下载媒体文件"""
        if not self._ensure_wecom_token():
            logging.error("企业微信 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[企微模拟] 下载媒体: %s", media_id)
            return b"mock_media_data"

        try:
            url = f"{self.WECOM_API_BASE}/cgi-bin/media/get"
            params = {
                "access_token": self.access_token,
                "media_id": media_id,
            }

            resp = requests.get(url, params=params, timeout=30, stream=True)

            content_type = resp.headers.get("Content-Type", "")

            if "application/json" in content_type:
                result = resp.json()
                logging.error("企业微信媒体下载失败: %s", result)
                return None

            media_data = resp.content

            if save_path:
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path_obj, "wb") as f:
                    f.write(media_data)
                logging.info("企业微信媒体已保存: %s", save_path)

            return media_data
        except requests.exceptions.Timeout:
            logging.error("媒体下载超时: %s", media_id)
            return None
        except requests.exceptions.HTTPError as e:
            logging.error("媒体下载 HTTP 错误: %s", e)
            return None
        except IOError as e:
            logging.error("保存媒体文件失败: %s", e)
            return None
        except Exception as e:
            logging.error("媒体下载异常: %s", e)
            return None

    def _download_official_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """从微信公众号下载媒体文件"""
        if not self._ensure_official_token():
            logging.error("微信公众号 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[公众号模拟] 下载媒体: %s", media_id)
            return b"mock_official_media_data"

        try:
            url = f"{self.WECHAT_OA_API_BASE}/cgi-bin/media/get"
            params = {
                "access_token": self.official_access_token,
                "media_id": media_id,
            }

            resp = requests.get(url, params=params, timeout=30, stream=True)

            content_type = resp.headers.get("Content-Type", "")

            if "application/json" in content_type:
                result = resp.json()
                logging.error("微信公众号媒体下载失败: %s", result)
                return None

            media_data = resp.content

            if save_path:
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path_obj, "wb") as f:
                    f.write(media_data)
                logging.info("微信公众号媒体已保存: %s", save_path)

            return media_data
        except Exception as e:
            logging.error("微信公众号媒体下载异常: %s", e)
            return None

    def _download_ilink_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """从 iLink 下载媒体文件"""
        if not self._ilink_initialized:
            logging.error("iLink 未初始化")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[iLink 模拟] 下载媒体: %s", media_id)
            return b"mock_ilink_media_data"

        try:
            url = f"{self.ILINK_API_BASE}/media/get"
            headers = {"Authorization": f"Bearer {self.ilink_bot_token}"}
            params = {"media_id": media_id}

            resp = requests.get(url, headers=headers, params=params, timeout=30, stream=True)
            result = resp.json()

            if not result.get("success"):
                logging.error("iLink 媒体下载失败: %s", result)
                return None

            media_url = result.get("url")
            if not media_url:
                logging.error("iLink 媒体 URL 为空")
                return None

            media_resp = requests.get(media_url, timeout=30, stream=True)
            media_data = media_resp.content

            if save_path:
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path_obj, "wb") as f:
                    f.write(media_data)
                logging.info("iLink 媒体已保存: %s", save_path)

            return media_data
        except Exception as e:
            logging.error("iLink 媒体下载异常: %s", e)
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

    def reset_reply_counts(self, session_key: str = None):
        """
        重置 iLink 回复计数器

        参数:
        session_key: 特定会话 key，如果为 None 则重置所有
        """
        if session_key:
            self._reply_counts.pop(session_key, None)
        else:
            self._reply_counts.clear()

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
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

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
                logger.error(
                    f"图片生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("AI图片生成异常: %s", e)
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
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("image_to_image", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生图的生成器")
                return None

            image_data = await self._download_url(image_url)
            if not image_data:
                logger.error("下载参考图片失败: %s", image_url)
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
                logger.error(
                    f"图生图生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("图生图生成异常: %s", e)
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
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

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
                logger.error(
                    f"视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("AI视频生成异常: %s", e)
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
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("image_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生视频的生成器")
                return None

            image_data = await self._download_url(image_url)
            if not image_data:
                logger.error("下载参考图片失败: %s", image_url)
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
                logger.error(
                    f"图生视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("图生视频生成异常: %s", e)
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
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

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
                logger.error(
                    f"首尾帧生成视频失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("首尾帧生成视频异常: %s", e)
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
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("video_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到视频生成视频的生成器")
                return None

            video_data = await self._download_url(video_url)
            if not video_data:
                logger.error("下载参考视频失败: %s", video_url)
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
                logger.error(
                    f"视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("视频生成异常: %s", e)
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
                        logging.error("下载失败 HTTP %s: %s", response.status_code, url)
                        return None
            except Exception as e:
                logging.error("httpx下载异常: %s", e)
                return None
        elif REQUESTS_AVAILABLE:
            try:
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    return response.content
                else:
                    logging.error("下载失败 HTTP %s: %s", response.status_code, url)
                    return None
            except Exception as e:
                logging.error("requests下载异常: %s", e)
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
            logging.info("临时文件已保存: %s", temp_path)
            return temp_path
        except Exception as e:
            logging.error("保存临时文件失败: %s", e)
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

        image_url = message.metadata.get("file_url", "") or message.metadata.get("pic_url", "")
        video_url = message.metadata.get("file_url", "")

        if "生成图片" in content or "画一张" in content or "生成一张图片" in content:
            if has_image:
                prompt = self._extract_prompt(message.content) or ""
                if image_url:
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="正在生成图片，请稍候...",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    image_data = await self.generate_image_to_image(image_url, prompt)
                    if image_data:
                        temp_path = await self._save_temp_file(image_data, "png")
                        if temp_path:
                            media_id = self.upload_media(temp_path, "image")
                            if media_id:
                                if self.mode == "wecom":
                                    self._send_app_message(
                                        UnifiedMessage(
                                            message_id="temp",
                                            channel=MessageChannel.WECHAT,
                                            chat_id=message.chat_id,
                                            user_id=message.user_id,
                                            agent_id="",
                                            content="",
                                            content_type=ContentType.IMAGE,
                                            timestamp=datetime.now(),
                                            file_url=media_id,
                                        )
                                    )
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                        if self.mode == "wecom":
                            self._send_app_message(
                                UnifiedMessage(
                                    message_id="temp",
                                    channel=MessageChannel.WECHAT,
                                    chat_id=message.chat_id,
                                    user_id=message.user_id,
                                    agent_id="",
                                    content="图片生成失败",
                                    content_type=ContentType.TEXT,
                                    timestamp=datetime.now(),
                                )
                            )
                        return False
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="图片生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
            else:
                prompt = self._extract_prompt(message.content)
                if prompt:
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="正在生成图片，请稍候...",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    image_data = await self.generate_text_to_image(prompt)
                    if image_data:
                        temp_path = await self._save_temp_file(image_data, "png")
                        if temp_path:
                            media_id = self.upload_media(temp_path, "image")
                            if media_id:
                                if self.mode == "wecom":
                                    self._send_app_message(
                                        UnifiedMessage(
                                            message_id="temp",
                                            channel=MessageChannel.WECHAT,
                                            chat_id=message.chat_id,
                                            user_id=message.user_id,
                                            agent_id="",
                                            content="",
                                            content_type=ContentType.IMAGE,
                                            timestamp=datetime.now(),
                                            file_url=media_id,
                                        )
                                    )
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                        if self.mode == "wecom":
                            self._send_app_message(
                                UnifiedMessage(
                                    message_id="temp",
                                    channel=MessageChannel.WECHAT,
                                    chat_id=message.chat_id,
                                    user_id=message.user_id,
                                    agent_id="",
                                    content="图片生成失败",
                                    content_type=ContentType.TEXT,
                                    timestamp=datetime.now(),
                                )
                            )
                        return False
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="图片生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False

        elif has_image and (
            "图生图" in content or "以图生图" in content or "生成相似图片" in content or "生成新图片" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成图片，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                image_data = await self.generate_image_to_image(image_url, prompt)
                if image_data:
                    temp_path = await self._save_temp_file(image_data, "png")
                    if temp_path:
                        media_id = self.upload_media(temp_path, "image")
                        if media_id:
                            if self.mode == "wecom":
                                self._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.IMAGE,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="图片生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="图片生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif has_image and (
            "图生视频" in content or "图片转视频" in content or "让图片动起来" in content or "图片生成视频" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await self.generate_image_to_video(image_url, prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = self.upload_media(temp_path, "video")
                        if media_id:
                            if self.mode == "wecom":
                                self._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif ("首尾帧" in content or "首帧到尾帧" in content or "首尾帧生成视频" in content) and message.metadata.get(
            "images_count", 0
        ) >= 2:
            start_url = message.metadata.get("first_image_url", "")
            end_url = message.metadata.get("last_image_url", "")
            if start_url and end_url:
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await self.generate_keyframe_to_video(start_url, end_url)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = self.upload_media(temp_path, "video")
                        if media_id:
                            if self.mode == "wecom":
                                self._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif has_video and (
            "视频生成" in content or "视频风格" in content or "修改视频" in content or "视频转视频" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if video_url:
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await self.generate_video_to_video(video_url, prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = self.upload_media(temp_path, "video")
                        if media_id:
                            if self.mode == "wecom":
                                self._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif "生成视频" in content or "生成一段视频" in content:
            prompt = self._extract_prompt(message.content)
            if prompt:
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await self.generate_text_to_video(prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = self.upload_media(temp_path, "video")
                        if media_id:
                            if self.mode == "wecom":
                                self._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if self.mode == "wecom":
                        self._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if self.mode == "wecom":
                    self._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        return False


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
