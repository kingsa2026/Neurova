"""
QQ Bot 渠道适配器

支持QQ个人号机器人协议 (OneBot标准)

API 文档: https://12.onebot.dev/

功能特性:
1. 消息发送和接收
2. 媒体消息支持 (图片、语音、视频、文件)
3. CQ码解析和构建
4. 私聊/群聊策略控制
5. 白名单和提及控制
"""

import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import re

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    pass

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logging.warning("httpx 库未安装，部分AI生成功能可能不可用")

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage


class QQBotAdapter(ChannelAdapter):
    """
    QQ Bot 渠道适配器

    支持:
    - QQ个人号机器人 (基于OneBot协议)
    - 正向WebSocket连接
    - HTTP API调用
    - 消息发送和接收
    """

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.QQBOT

    def __init__(self):
        # 基础认证信息
        self.access_token = ""

        # API配置
        self.http_api_url = "http://127.0.0.1:3000"
        self.ws_api_url = "ws://127.0.0.1:3001"

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
        self._ws_connection = None

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证QQ Bot

        参数:
        config: {
            "access_token": "访问令牌",
            "http_api_url": "HTTP API地址",
            "ws_api_url": "WebSocket API地址",
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
        self.access_token = config.get("access_token", "")
        self.http_api_url = config.get("http_api_url", "http://127.0.0.1:3000")
        self.ws_api_url = config.get("ws_api_url", "ws://127.0.0.1:3001")

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

        if not self.access_token:
            logging.error("QQ Bot认证失败: access_token 不能为空")
            return False

        return self._verify_connection()

    def _verify_connection(self) -> bool:
        """验证QQ Bot连接"""
        if not REQUESTS_AVAILABLE:
            self._initialized = True
            return True

        try:
            # 测试获取机器人信息
            headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

            resp = requests.post(f"{self.http_api_url}/get_login_info", headers=headers, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode") == 0:
                    user_info = data.get("data", {})
                    nickname = user_info.get("nickname", "Unknown")
                    user_id = user_info.get("user_id", "Unknown")
                    logging.info("QQ Bot认证成功 - 用户: %s(%s)", nickname, user_id)
                    self._initialized = True
                    return True
                else:
                    logging.error("QQ Bot认证失败: %s", data)
                    return False
            else:
                logging.error("QQ Bot连接失败: HTTP %s", resp.status_code)
                return False
        except Exception as e:
            logging.error("QQ Bot连接异常: %s", e)
            return False

    def _ensure_authenticated(self) -> bool:
        """确保已认证"""
        if not self._initialized:
            return self._verify_connection()
        return True

    def _api_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        统一的 OneBot API 请求方法

        参数:
        method: HTTP 方法 (GET/POST)
        endpoint: API 端点 (如 /send_group_msg)
        **kwargs: requests 的其他参数

        返回:
        API 响应数据
        """
        if not REQUESTS_AVAILABLE:
            return {"retcode": 1, "data": {}, "message": "requests 库未安装"}

        url = f"{self.http_api_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        kwargs.setdefault("timeout", 30)

        try:
            resp = requests.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logging.error("QQ Bot API 请求超时: %s", url)
            return {"retcode": 1, "data": {}, "message": "请求超时"}
        except requests.exceptions.HTTPError as e:
            logging.error("QQ Bot API HTTP 错误: %s", e)
            return {"retcode": 1, "data": {}, "message": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            logging.error("QQ Bot API 请求异常: %s", e)
            return {"retcode": 1, "data": {}, "message": str(e)}

    def send_message(self, message: UnifiedMessage) -> bool:
        """
        发送QQ Bot消息

        支持文本、图片、语音、视频、文件等消息类型

        参数:
        message: 统一消息对象

        返回:
        发送成功返回 True
        """
        if not self._ensure_authenticated():
            return False

        if not REQUESTS_AVAILABLE:
            logging.info("[QQ Bot模拟] 发送消息到 %s: %s", message.chat_id, message.content[:50])
            return True

        try:
            # 根据chat_id判断是私聊还是群聊
            try:
                int(message.chat_id)
                is_group = True
            except ValueError:
                is_group = False

            # 构建消息内容
            message_content = self._build_cq_message(message)

            # 构建API请求
            if is_group:
                payload = {"group_id": message.chat_id, "message": message_content, "auto_escape": False}
                api_endpoint = "/send_group_msg"
            else:
                payload = {"user_id": message.chat_id, "message": message_content, "auto_escape": False}
                api_endpoint = "/send_private_msg"

            # 发送请求
            data = self._api_request("POST", api_endpoint, json=payload)

            if data.get("retcode") == 0:
                return True
            else:
                logging.error("QQ Bot消息发送失败: %s", data)
                return False
        except Exception as e:
            logging.error("QQ Bot消息发送异常: %s", e)
            return False

    def _build_cq_message(self, message: UnifiedMessage) -> str:
        """
        构建CQ码消息

        参数:
        message: 统一消息对象

        返回:
        CQ码格式的消息字符串
        """
        content = message.content

        # 根据内容类型添加CQ码
        if message.content_type == ContentType.IMAGE:
            if message.file_url:
                return f"[CQ:image,file={message.file_url}]"
            elif content and not content.startswith("[CQ:"):
                return f"[CQ:image,file={content}]"
            return content
        elif message.content_type == ContentType.VOICE:
            if message.file_url:
                return f"[CQ:record,file={message.file_url}]"
            elif content and not content.startswith("[CQ:"):
                return f"[CQ:record,file={content}]"
            return content
        elif message.content_type == ContentType.VIDEO:
            if message.file_url:
                return f"[CQ:video,file={message.file_url}]"
            elif content and not content.startswith("[CQ:"):
                return f"[CQ:video,file={content}]"
            return content
        elif message.content_type == ContentType.FILE:
            if message.file_url:
                return f"[CQ:file,file={message.file_url}]"
            elif content and not content.startswith("[CQ:"):
                return f"[CQ:file,file={content}]"
            return content

        return content

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收消息 (通过WebSocket事件)"""
        logging.warning("QQ Bot消息接收请使用 WebSocket 事件模式")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析QQ Bot原始消息

        OneBot消息格式:
        {
            "time": 1234567890,
            "self_id": 123456,
            "post_type": "message",
            "message_type": "private/group",
            "sub_type": "friend/normal",
            "message_id": 123456,
            "user_id": 123456789,
            "target_id": 987654321,
            "message": "消息内容",
            "raw_message": "原始消息",
            "font": 0,
            "sender": {
                "user_id": 123456789,
                "nickname": "昵称",
                "sex": "male/female/unknown",
                "age": 0
            },
            "group_id": 987654321  # 仅群消息有
        }
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                logging.error("解析QQ Bot消息失败: 无效JSON格式")
                return None

        # 提取消息信息
        message_id = str(raw_data.get("message_id", int(time.time())))
        message_type = raw_data.get("message_type", "private")
        user_id = str(raw_data.get("user_id", ""))
        content = raw_data.get("message", "")

        # 解析CQ码并确定内容类型
        content_type, file_url = self._parse_cq_code(content)

        # 根据消息类型确定chat_id
        if message_type == "group":
            chat_id = str(raw_data.get("group_id", user_id))
        else:
            chat_id = user_id

        # 获取时间戳
        timestamp_int = raw_data.get("time", int(time.time()))
        timestamp = datetime.fromtimestamp(timestamp_int)

        # 获取发送者信息
        sender = raw_data.get("sender", {})
        nickname = sender.get("nickname", f"QQ用户{user_id}")

        # 检查是否需要 @提及 (仅群消息需要)
        if message_type == "group" and self.require_mention:
            bot_at_pattern = f"[CQ:at,qq="
            if bot_at_pattern in content:
                pass
            else:
                logging.debug("群消息未@机器人，忽略")
                return None

        # 检查私聊/群聊策略
        if message_type == "private":
            if self.private_chat_strategy == "closed":
                logging.debug("私聊已关闭，忽略消息")
                return None
            elif self.private_chat_strategy == "whitelist":
                if user_id not in self.whitelist_users:
                    logging.debug("用户 %s 不在白名单中", user_id)
                    return None
        elif message_type == "group":
            if self.group_chat_strategy == "closed":
                logging.debug("群聊已关闭，忽略消息")
                return None
            elif self.group_chat_strategy == "whitelist":
                if user_id not in self.whitelist_users:
                    logging.debug("用户 %s 不在白名单中", user_id)
                    return None

        return UnifiedMessage(
            message_id=message_id,
            channel=MessageChannel.QQBOT,
            chat_id=chat_id,
            user_id=user_id,
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            global_user_id=f"qqbot:{user_id}",
            session_id=f"qqbot:{chat_id}:{user_id}",
            raw_message=raw_data,
            file_url=file_url,
            metadata={
                "message_type": message_type,
                "user_nickname": nickname,
                "group_id": raw_data.get("group_id"),
                "sender": sender,
            },
        )

    def _parse_cq_code(self, message: str) -> tuple:
        """
        解析CQ码消息，提取内容类型和文件URL

        支持的CQ码类型:
        - [CQ:image,file=xxx] - 图片
        - [CQ:record,file=xxx] - 录音/语音
        - [CQ:voice,file=xxx] - 语音
        - [CQ:video,file=xxx] - 视频
        - [CQ:file,file=xxx] - 文件

        参数:
        message: 消息内容

        返回:
        (content_type, file_url) 元组
        """
        # CQ码正则表达式
        cq_pattern = r"\[CQ:([^,\]]+)(?:,([^\]]+))?\]"
        matches = re.findall(cq_pattern, message)

        content_type = ContentType.TEXT
        file_url = ""

        for cq_type, params in matches:
            cq_type = cq_type.lower()

            # 提取 file 参数
            file_param = ""
            if params:
                param_pairs = params.split(",")
                for pair in param_pairs:
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        if key.strip() == "file":
                            file_param = value.strip()
                            break

            # 根据CQ码类型设置内容类型
            if cq_type == "image":
                content_type = ContentType.IMAGE
                file_url = file_param
                logging.debug("解析到图片消息: %s", file_url)
            elif cq_type == "record":
                content_type = ContentType.VOICE
                file_url = file_param
                logging.debug("解析到录音消息: %s", file_url)
            elif cq_type == "voice":
                content_type = ContentType.VOICE
                file_url = file_param
                logging.debug("解析到语音消息: %s", file_url)
            elif cq_type == "video":
                content_type = ContentType.VIDEO
                file_url = file_param
                logging.debug("解析到视频消息: %s", file_url)
            elif cq_type == "file":
                content_type = ContentType.FILE
                file_url = file_param
                logging.debug("解析到文件消息: %s", file_url)

        return content_type, file_url

    def upload_file(self, file_path: str, name: str = "") -> Optional[str]:
        """
        上传文件到QQ (OneBot标准)

        参数:
        file_path: 文件路径
        name: 文件名 (可选)

        返回:
        成功返回 file_id，失败返回 None
        """
        if not self._ensure_authenticated():
            return None

        if not REQUESTS_AVAILABLE:
            logging.info("[QQ Bot模拟] 上传文件: %s", file_path)
            return f"模拟_file_id_{file_path}"

        try:
            with open(file_path, "rb") as f:
                files = {"file": (name or file_path, f)}
                data = {"name": name} if name else {}

                resp = requests.post(
                    f"{self.http_api_url}/upload_file",
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    files=files,
                    data=data,
                    timeout=60,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("retcode") == 0:
                        file_id = result.get("data", {}).get("file_id")
                        logging.info("文件上传成功: %s -> %s", file_path, file_id)
                        return file_id
                    else:
                        logging.error("文件上传失败: %s", result)
                        return None
                else:
                    logging.error("文件上传失败: HTTP %s", resp.status_code)
                    return None
        except FileNotFoundError:
            logging.error("文件不存在: %s", file_path)
            return None
        except Exception as e:
            logging.error("文件上传异常: %s", e)
            return None

    def send_image(self, chat_id: str, file_path: str = "", file_id: str = "", url: str = "") -> bool:
        """
        发送图片

        参数:
        chat_id: 聊天ID
        file_path: 本地文件路径 (优先使用)
        file_id: 文件ID
        url: 网络图片URL

        返回:
        发送成功返回 True
        """
        if not self._ensure_authenticated():
            return False

        try:
            int(chat_id)
            is_group = True
        except ValueError:
            is_group = False

        if file_path:
            file_id = self.upload_file(file_path)
            if not file_id:
                return False
            cq_message = f"[CQ:image,file={file_id}]"
        elif file_id:
            cq_message = f"[CQ:image,file={file_id}]"
        elif url:
            cq_message = f"[CQ:image,file={url}]"
        else:
            logging.error("send_image: 未提供文件路径、file_id 或 URL")
            return False

        if is_group:
            data = self._api_request(
                "POST", "/send_group_msg", json={"group_id": chat_id, "message": cq_message, "auto_escape": False}
            )
        else:
            data = self._api_request(
                "POST", "/send_private_msg", json={"user_id": chat_id, "message": cq_message, "auto_escape": False}
            )

        return data.get("retcode") == 0

    def send_voice(self, chat_id: str, file_path: str = "", file_id: str = "", url: str = "") -> bool:
        """
        发送语音

        参数:
        chat_id: 聊天ID
        file_path: 本地文件路径 (优先使用)
        file_id: 文件ID
        url: 网络语音URL

        返回:
        发送成功返回 True
        """
        if not self._ensure_authenticated():
            return False

        try:
            int(chat_id)
            is_group = True
        except ValueError:
            is_group = False

        if file_path:
            file_id = self.upload_file(file_path)
            if not file_id:
                return False
            cq_message = f"[CQ:record,file={file_id}]"
        elif file_id:
            cq_message = f"[CQ:record,file={file_id}]"
        elif url:
            cq_message = f"[CQ:record,file={url}]"
        else:
            logging.error("send_voice: 未提供文件路径、file_id 或 URL")
            return False

        if is_group:
            data = self._api_request(
                "POST", "/send_group_msg", json={"group_id": chat_id, "message": cq_message, "auto_escape": False}
            )
        else:
            data = self._api_request(
                "POST", "/send_private_msg", json={"user_id": chat_id, "message": cq_message, "auto_escape": False}
            )

        return data.get("retcode") == 0

    def send_video(self, chat_id: str, file_path: str = "", file_id: str = "", url: str = "") -> bool:
        """
        发送视频

        参数:
        chat_id: 聊天ID
        file_path: 本地文件路径 (优先使用)
        file_id: 文件ID
        url: 网络视频URL

        返回:
        发送成功返回 True
        """
        if not self._ensure_authenticated():
            return False

        try:
            int(chat_id)
            is_group = True
        except ValueError:
            is_group = False

        if file_path:
            file_id = self.upload_file(file_path)
            if not file_id:
                return False
            cq_message = f"[CQ:video,file={file_id}]"
        elif file_id:
            cq_message = f"[CQ:video,file={file_id}]"
        elif url:
            cq_message = f"[CQ:video,file={url}]"
        else:
            logging.error("send_video: 未提供文件路径、file_id 或 URL")
            return False

        if is_group:
            data = self._api_request(
                "POST", "/send_group_msg", json={"group_id": chat_id, "message": cq_message, "auto_escape": False}
            )
        else:
            data = self._api_request(
                "POST", "/send_private_msg", json={"user_id": chat_id, "message": cq_message, "auto_escape": False}
            )

        return data.get("retcode") == 0

    def send_file(self, chat_id: str, file_path: str = "", file_id: str = "", url: str = "", name: str = "") -> bool:
        """
        发送文件

        参数:
        chat_id: 聊天ID
        file_path: 本地文件路径 (优先使用)
        file_id: 文件ID
        url: 网络文件URL
        name: 文件名 (发送给接收方的文件名)

        返回:
        发送成功返回 True
        """
        if not self._ensure_authenticated():
            return False

        try:
            int(chat_id)
            is_group = True
        except ValueError:
            is_group = False

        if file_path:
            file_id = self.upload_file(file_path, name)
            if not file_id:
                return False
            cq_message = f"[CQ:file,file={file_id}]"
            if name:
                cq_message = f"[CQ:file,file={file_id},name={name}]"
        elif file_id:
            cq_message = f"[CQ:file,file={file_id}]"
            if name:
                cq_message = f"[CQ:file,file={file_id},name={name}]"
        elif url:
            cq_message = f"[CQ:file,file={url}]"
            if name:
                cq_message = f"[CQ:file,file={url},name={name}]"
        else:
            logging.error("send_file: 未提供文件路径、file_id 或 URL")
            return False

        if is_group:
            data = self._api_request(
                "POST", "/send_group_msg", json={"group_id": chat_id, "message": cq_message, "auto_escape": False}
            )
        else:
            data = self._api_request(
                "POST", "/send_private_msg", json={"user_id": chat_id, "message": cq_message, "auto_escape": False}
            )

        return data.get("retcode") == 0

    def get_channel_config(self) -> Dict[str, Any]:
        return {
            "channel": self.channel.value,
            "access_token": self.access_token,
            "http_api_url": self.http_api_url,
            "ws_api_url": self.ws_api_url,
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

        message_type = raw_data.get("message_type", "private")
        user_id = str(raw_data.get("user_id", ""))

        # 检查是否需要 @提及 (仅群消息需要)
        if message_type == "group" and self.require_mention:
            bot_at_pattern = f"[CQ:at,qq="
            if bot_at_pattern not in raw_data.get("message", ""):
                return False

        # 检查私聊/群聊策略
        if message_type == "private":
            if self.private_chat_strategy == "closed":
                return False
            elif self.private_chat_strategy == "whitelist":
                return user_id in self.whitelist_users
        elif message_type == "group":
            if self.group_chat_strategy == "closed":
                return False
            elif self.group_chat_strategy == "whitelist":
                return user_id in self.whitelist_users

        return True


def create_qqbot_adapter(access_token: str = "", http_url: str = "http://127.0.0.1:3000") -> QQBotAdapter:
    """创建QQ Bot适配器"""
    adapter = QQBotAdapter()
    if access_token:
        adapter.authenticate(
            {
                "access_token": access_token,
                "http_api_url": http_url,
            }
        )
    return adapter


# ============================================================
# QQBotAdapter AI 生成能力
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

    image_url = message.file_url
    video_url = message.file_url

    if "生成图片" in content or "画一张" in content or "生成一张图片" in content:
        if has_image:
            prompt = _extract_prompt(self, message.content) or ""
            if image_url:
                _send_typing(self, message, "正在生成图片，请稍候...")
                gen_image_data = await generate_image_to_image(self, image_url, prompt)
                if gen_image_data:
                    temp_path = await _save_temp_file(self, gen_image_data, "png")
                    if temp_path:
                        if self.send_image(message.chat_id, file_path=temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                _send_typing(self, message, "图片生成失败")
                return False
        else:
            prompt = _extract_prompt(self, message.content)
            if prompt:
                _send_typing(self, message, "正在生成图片，请稍候...")
                image_data = await generate_text_to_image(self, prompt)
                if image_data:
                    temp_path = await _save_temp_file(self, image_data, "png")
                    if temp_path:
                        if self.send_image(message.chat_id, file_path=temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                _send_typing(self, message, "图片生成失败")
                return False

    elif has_image and (
        "图生图" in content or "以图生图" in content or "生成相似图片" in content or "生成新图片" in content
    ):
        prompt = _extract_prompt(self, message.content) or ""
        if image_url:
            _send_typing(self, message, "正在生成图片，请稍候...")
            image_data = await generate_image_to_image(self, image_url, prompt)
            if image_data:
                temp_path = await _save_temp_file(self, image_data, "png")
                if temp_path:
                    if self.send_image(message.chat_id, file_path=temp_path):
                        os.unlink(temp_path)
                        return True
                    os.unlink(temp_path)
            _send_typing(self, message, "图片生成失败")
            return False

    elif has_image and (
        "图生视频" in content or "图片转视频" in content or "让图片动起来" in content or "图片生成视频" in content
    ):
        prompt = _extract_prompt(self, message.content) or ""
        if image_url:
            _send_typing(self, message, "正在生成视频，请稍候...")
            video_data = await generate_image_to_video(self, image_url, prompt)
            if video_data:
                temp_path = await _save_temp_file(self, video_data, "mp4")
                if temp_path:
                    if self.send_video(message.chat_id, file_path=temp_path):
                        os.unlink(temp_path)
                        return True
                    os.unlink(temp_path)
            _send_typing(self, message, "视频生成失败")
            return False

    elif ("首尾帧" in content or "首帧到尾帧" in content or "首尾帧生成视频" in content) and message.metadata.get(
        "images_count", 0
    ) >= 2:
        start_url = message.metadata.get("first_image_url", "")
        end_url = message.metadata.get("last_image_url", "")
        if start_url and end_url:
            _send_typing(self, message, "正在生成视频，请稍候...")
            video_data = await generate_keyframe_to_video(self, start_url, end_url)
            if video_data:
                temp_path = await _save_temp_file(self, video_data, "mp4")
                if temp_path:
                    if self.send_video(message.chat_id, file_path=temp_path):
                        os.unlink(temp_path)
                        return True
                    os.unlink(temp_path)
            _send_typing(self, message, "视频生成失败")
            return False

    elif has_video and (
        "视频生成" in content or "视频风格" in content or "修改视频" in content or "视频转视频" in content
    ):
        prompt = _extract_prompt(self, message.content) or ""
        if video_url:
            _send_typing(self, message, "正在生成视频，请稍候...")
            video_data = await generate_video_to_video(self, video_url, prompt)
            if video_data:
                temp_path = await _save_temp_file(self, video_data, "mp4")
                if temp_path:
                    if self.send_video(message.chat_id, file_path=temp_path):
                        os.unlink(temp_path)
                        return True
                    os.unlink(temp_path)
            _send_typing(self, message, "视频生成失败")
            return False

    elif "生成视频" in content or "生成一段视频" in content:
        prompt = _extract_prompt(self, message.content)
        if prompt:
            _send_typing(self, message, "正在生成视频，请稍候...")
            video_data = await generate_text_to_video(self, prompt)
            if video_data:
                temp_path = await _save_temp_file(self, video_data, "mp4")
                if temp_path:
                    if self.send_video(message.chat_id, file_path=temp_path):
                        os.unlink(temp_path)
                        return True
                    os.unlink(temp_path)
            _send_typing(self, message, "视频生成失败")
            return False

    return False


def _send_typing(self, message: UnifiedMessage, content: str):
    """发送临时消息提示"""
    self.send_message(
        UnifiedMessage(
            message_id="temp",
            channel=MessageChannel.QQBOT,
            chat_id=message.chat_id,
            user_id=message.user_id,
            agent_id="",
            content=content,
            content_type=ContentType.TEXT,
            timestamp=datetime.now(),
        )
    )


QQBotAdapter.generate_text_to_image = generate_text_to_image
QQBotAdapter.generate_image_to_image = generate_image_to_image
QQBotAdapter.generate_text_to_video = generate_text_to_video
QQBotAdapter.generate_image_to_video = generate_image_to_video
QQBotAdapter.generate_keyframe_to_video = generate_keyframe_to_video
QQBotAdapter.generate_video_to_video = generate_video_to_video
QQBotAdapter._download_url = _download_url
QQBotAdapter._save_temp_file = _save_temp_file
QQBotAdapter._extract_prompt = _extract_prompt
QQBotAdapter._send_typing = _send_typing
QQBotAdapter.handle_ai_generation = handle_ai_generation
