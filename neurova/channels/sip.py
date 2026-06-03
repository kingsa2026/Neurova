"""
SIP 语音通话渠道适配器

支持:
- SIP 协议语音通话
- TTS (文本转语音)
- STT (语音转文本)
- Dev 模式 (pyVoIP) / Production 模式 (LiveKit SIP Server)

依赖:
pip install pyvoip aiohttp
"""

import json
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

try:
    PYVOIP_AVAILABLE = True
except ImportError:
    PYVOIP_AVAILABLE = False

try:
    import re
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from neurova.channels import (
    ChannelAdapter, MessageChannel, UnifiedMessage, ContentType
)

class SIPAdapter(ChannelAdapter):
    """
    SIP 语音通话渠道适配器

    支持模式:
    1. Dev 模式 (pyVoIP) - 本地处理 SIP/RTP
    2. Production 模式 (LiveKit SIP Server) - 使用 LiveKit SIP 服务器
    """

    # DashScope API (阿里云)
    DASHSCOPE_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/text-to-speech/generation"
    DASHSCOPE_STT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.SIP

    def __init__(self):
        # 基础配置
        self.bot_prefix = "@bot"
        self.show_tool_messages = True
        self.show_thinking = True

        # SIP 配置
        self.sip_mode = "dev"  # dev / production
        self.sip_server = ""  # 留空使用内置注册服务器
        self.sip_username = "kingsa"
        self.sip_password = ""
        self.sip_port = 5061
        self.transport_protocol = "UDP"  # UDP / TCP / TLS

        # TTS/STT 配置
        self.dashscope_api_key = ""
        self.tts_provider = "aliyun"
        self.tts_voice = "longxiaochun"
        self.stt_provider = "aliyun"
        self.language = "zh-CN"
        self.welcome_message = "你好，我是Neurova"

        # 内部状态
        self._initialized = False
        self._voip_client = None
        self._call_session = None
        self._audio_buffer = []

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证 SIP 渠道

        参数:
        config: {
            "bot_prefix": "@bot",
            "show_tool_messages": "true/false",
            "show_thinking": "true/false",
            "sip_mode": "dev/production",
            "sip_server": "SIP服务器地址",
            "sip_username": "用户名",
            "sip_password": "密码",
            "sip_port": "5061",
            "transport_protocol": "UDP",
            "dashscope_api_key": "sk-...",
            "tts_provider": "aliyun",
            "tts_voice": "longxiaochun",
            "stt_provider": "aliyun",
            "language": "zh-CN",
            "welcome_message": "你好，我是Neurova",
        }
        """
        # 基础配置
        self.bot_prefix = config.get("bot_prefix", "@bot")
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"

        # SIP 配置
        self.sip_mode = config.get("sip_mode", "dev")
        self.sip_server = config.get("sip_server", "")
        self.sip_username = config.get("sip_username", "kingsa")
        self.sip_password = config.get("sip_password", "")
        self.sip_port = int(config.get("sip_port", "5061"))
        self.transport_protocol = config.get("transport_protocol", "UDP")

        # TTS/STT 配置
        self.dashscope_api_key = config.get("dashscope_api_key", "")
        self.tts_provider = config.get("tts_provider", "aliyun")
        self.tts_voice = config.get("tts_voice", "longxiaochun")
        self.stt_provider = config.get("stt_provider", "aliyun")
        self.language = config.get("language", "zh-CN")
        self.welcome_message = config.get("welcome_message", "你好，我是Neurova")

        if not self.sip_username or not self.sip_password:
            logging.error("SIP认证失败: 用户名和密码不能为空")
            return False

        if not self.dashscope_api_key:
            logging.warning("未配置 DashScope API Key, TTS/STT 功能不可用")

        return self._init_sip()

    def _init_sip(self) -> bool:
        """初始化 SIP 连接"""
        if self.sip_mode == "dev":
            return self._init_dev_mode()
        else:
            return self._init_production_mode()

    def _init_dev_mode(self) -> bool:
        """
        Dev 模式初始化 - 使用 pyVoIP

        Dev 模式在本地处理 SIP/RTP
        """
        if not PYVOIP_AVAILABLE:
            logging.warning("pyVoIP 未安装，Dev 模式不可用")
            logging.info("安装命令: pip install pyvoip")
            self._initialized = True  # 模拟初始化
            return True

        try:
            # 创建 SIP 客户端
            server = self.sip_server if self.sip_server else None
            self._voip_client = pyvoip.SIPClient(
                server=server,
                port=self.sip_port,
                username=self.sip_username,
                password=self.sip_password,
                transport=self.transport_protocol.lower()
            )

            # 注册 SIP 账户
            self._voip_client.register()
            logging.info(f"SIP Dev 模式初始化成功 - 用户: {self.sip_username}")

            self._initialized = True
            return True
        except (OSError, requests.RequestException, ValueError) as e:
            logging.error(f"SIP Dev 模式初始化失败: {e}")
            return False

    def _init_production_mode(self) -> bool:
        """
        Production 模式初始化 - 使用 LiveKit SIP Server

        Production 模式使用外部 SIP 服务器
        """
        if not self.sip_server:
            logging.info("SIP Production 模式: 使用内置注册服务器")

        logging.info(f"SIP Production 模式初始化 - 服务器: {self.sip_server or '内置'}")
        self._initialized = True
        return True

    def text_to_speech(self, text: str) -> Optional[bytes]:
        """
        文本转语音 (TTS)

        使用 DashScope API (阿里云)

        参数:
        text: 要转换的文本

        返回:
        音频数据 (bytes)
        """
        if not self.dashscope_api_key:
            logging.error("未配置 DashScope API Key，无法使用 TTS")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info(f"[TTS模拟] 文本: {text[:50]}")
            return b""

        try:
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable"
            }

            payload = {
                "model": "sambert-zhichu-v1",
                "input": {
                    "text": text
                },
                "parameters": {
                    "voice": self.tts_voice,
                    "format": "wav",
                    "sample_rate": 16000,
                }
            }

            resp = requests.post(
                self.DASHSCOPE_TTS_URL,
                headers=headers,
                json=payload,
                timeout=30
            )

            if resp.status_code == 200:
                result = resp.json()
                if "output" in result and "audio" in result["output"]:
                    # 返回音频 URL 或直接音频数据
                    audio_data = result["output"]["audio"]
                    logging.info("TTS 转换成功")
                    return audio_data

            logging.error(f"TTS 转换失败: {resp.json()}")
            return None
        except (requests.RequestException, json.JSONDecodeError) as e:
            logging.error(f"TTS 转换异常: {e}")
            return None

    def speech_to_text(self, audio_data: bytes) -> Optional[str]:
        """
        语音转文本 (STT)

        使用 DashScope API (阿里云)

        参数:
        audio_data: 音频数据 (bytes)

        返回:
        转换后的文本
        """
        if not self.dashscope_api_key:
            logging.error("未配置 DashScope API Key，无法使用 STT")
            return None

        if not REQUESTS_AVAILABLE:
            logging.info(f"[STT模拟] 音频数据长度: {len(audio_data)} bytes")
            return "用户语音内容"

        try:
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/octet-stream",
            }

            # 上传音频文件进行识别
            resp = requests.post(
                self.DASHSCOPE_STT_URL,
                headers=headers,
                data=audio_data,
                params={
                    "model": "paraformer-realtime-v1",
                    "format": "wav",
                    "sample_rate": "16000",
                },
                timeout=30
            )

            if resp.status_code == 200:
                result = resp.json()
                if "output" in result and "text" in result["output"]:
                    text = result["output"]["text"]
                    logging.info(f"STT 转换成功: {text[:50]}")
                    return text

            logging.error(f"STT 转换失败: {resp.json()}")
            return None
        except Exception as e:
            logging.error(f"STT 转换异常: {e}")
            return None

    def send_message(self, message: UnifiedMessage) -> bool:
        """
        发送 SIP 语音消息

        将文本转换为语音并发送
        """
        if not self._initialized:
            logging.error("SIP 未初始化")
            return False

        # 先将文本转换为语音
        audio_data = self.text_to_speech(message.content)
        if not audio_data:
            logging.error("TTS 转换失败")
            return False

        if self.sip_mode == "dev" and self._voip_client:
            return self._send_dev_audio(audio_data, message.chat_id)
        else:
            return self._send_production_audio(audio_data, message.chat_id)

    def _send_dev_audio(self, audio_data: bytes, chat_id: str) -> bool:
        """Dev 模式发送音频"""
        if not PYVOIP_AVAILABLE:
            logging.info(f"[SIP模拟] 发送音频到 {chat_id}")
            return True

        try:
            # 在现有通话中发送音频
            if self._call_session:
                self._call_session.send_rtp_audio(audio_data)
                return True
            else:
                logging.warning("没有活跃的通话会话")
                return False
        except Exception as e:
            logging.error(f"发送音频异常: {e}")
            return False

    def _send_production_audio(self, audio_data: bytes, chat_id: str) -> bool:
        """Production 模式发送音频"""
        # Production 模式下，音频通过 SIP 服务器转发
        logging.info(f"[SIP Production] 发送音频到 {chat_id}")
        return True

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收 SIP 语音消息"""
        if self.sip_mode == "dev" and self._voip_client:
            return self._receive_dev_message()
        else:
            return self._receive_production_message()

    def _receive_dev_message(self) -> Optional[UnifiedMessage]:
        """Dev 模式接收消息"""
        if not PYVOIP_AVAILABLE:
            return None

        try:
            # 等待来电
            call = self._voip_client.wait_for_call(timeout=1)
            if call:
                # 接受通话
                call.answer()
                self._call_session = call

                # 接收 RTP 音频数据
                audio_data = call.receive_rtp_audio()
                if audio_data:
                    # 将音频转换为文本
                    text = self.speech_to_text(audio_data)
                    if text:
                        return UnifiedMessage(
                            message_id=str(int(time.time())),
                            channel=MessageChannel.SIP,
                            chat_id=call.caller_id,
                            user_id=call.caller_id,
                            agent_id="",
                            content=text,
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                            global_user_id=f"sip:{call.caller_id}",
                            session_id=f"sip:{call.call_id}",
                            raw_message={"caller_id": call.caller_id, "call_id": call.call_id},
                            metadata={
                                "caller_id": call.caller_id,
                                "call_id": call.call_id,
                                "sip_mode": "dev",
                            },
                        )
        except pyvoip.NoCallError:
            logging.debug("没有当前来电")
        except Exception as e:
            logging.error(f"接收 SIP 消息异常: {e}")

        return None

    def _receive_production_message(self) -> Optional[UnifiedMessage]:
        """Production 模式接收消息 (通过 Webhook)"""
        logging.warning("SIP Production 模式请使用 Webhook 接收消息")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析 SIP 原始消息

        SIP Webhook 消息格式:
        {
            "call_id": "通话ID",
            "caller_id": "来电号码",
            "callee_id": "接听号码",
            "direction": "inbound/outbound",
            "status": "ringing/answered/ended",
            "audio_data": "音频数据 (base64)",
            "timestamp": "时间戳"
        }
        """
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                logging.error("解析SIP消息失败: 无效JSON格式")
                return None

        call_id = raw_data.get("call_id", "")
        caller_id = raw_data.get("caller_id", "")
        direction = raw_data.get("direction", "inbound")
        status = raw_data.get("status", "")
        audio_base64 = raw_data.get("audio_data", "")

        import base64
        audio_data = None
        if audio_base64:
            try:
                audio_data = base64.b64decode(audio_base64)
            except Exception as e:
                logging.error(f"解码音频数据失败: {e}")

        # 将音频转换为文本
        content = ""
        if audio_data:
            content = self.speech_to_text(audio_data) or ""

        # 如果是来电响铃状态，返回特殊消息
        if status == "ringing":
            content = "[来电响铃]"

        return UnifiedMessage(
            message_id=call_id or str(int(time.time())),
            channel=MessageChannel.SIP,
            chat_id=call_id,
            user_id=caller_id,
            agent_id="",
            content=content,
            content_type=ContentType.TEXT,
            timestamp=datetime.now(),
            global_user_id=f"sip:{caller_id}",
            session_id=f"sip:{call_id}",
            raw_message=raw_data,
            metadata={
                "caller_id": caller_id,
                "call_id": call_id,
                "direction": direction,
                "status": status,
                "sip_mode": self.sip_mode,
            },
        )

    def play_welcome_message(self, chat_id: str) -> bool:
        """播放欢迎语音"""
        if not self.welcome_message:
            return True

        audio_data = self.text_to_speech(self.welcome_message)
        if audio_data:
            return self._send_dev_audio(audio_data, chat_id) if self.sip_mode == "dev" else self._send_production_audio(audio_data, chat_id)
        return False

    def hangup_call(self, call_id: str) -> bool:
        """挂断通话"""
        if self.sip_mode == "dev" and self._call_session:
            try:
                self._call_session.hangup()
                self._call_session = None
                return True
            except Exception as e:
                logging.error(f"挂断通话失败: {e}")
                return False
        return True

    def get_channel_config(self) -> Dict[str, Any]:
        return {
            "channel": self.channel.value,
            "bot_prefix": self.bot_prefix,
            "show_tool_messages": self.show_tool_messages,
            "show_thinking": self.show_thinking,
            "sip_mode": self.sip_mode,
            "sip_server": self.sip_server,
            "sip_username": self.sip_username,
            "sip_port": self.sip_port,
            "transport_protocol": self.transport_protocol,
            "tts_provider": self.tts_provider,
            "tts_voice": self.tts_voice,
            "stt_provider": self.stt_provider,
            "language": self.language,
            "welcome_message": self.welcome_message,
            "authenticated": self._initialized,
        }

    def update_config(self, config_updates: Dict):
        """更新配置"""
        if "bot_prefix" in config_updates:
            self.bot_prefix = config_updates["bot_prefix"]
        if "show_tool_messages" in config_updates:
            self.show_tool_messages = config_updates["show_tool_messages"]
        if "show_thinking" in config_updates:
            self.show_thinking = config_updates["show_thinking"]
        if "sip_mode" in config_updates:
            self.sip_mode = config_updates["sip_mode"]
        if "sip_server" in config_updates:
            self.sip_server = config_updates["sip_server"]
        if "sip_username" in config_updates:
            self.sip_username = config_updates["sip_username"]
        if "sip_password" in config_updates:
            self.sip_password = config_updates["sip_password"]
        if "sip_port" in config_updates:
            self.sip_port = int(config_updates["sip_port"])
        if "transport_protocol" in config_updates:
            self.transport_protocol = config_updates["transport_protocol"]
        if "dashscope_api_key" in config_updates:
            self.dashscope_api_key = config_updates["dashscope_api_key"]
        if "tts_provider" in config_updates:
            self.tts_provider = config_updates["tts_provider"]
        if "tts_voice" in config_updates:
            self.tts_voice = config_updates["tts_voice"]
        if "stt_provider" in config_updates:
            self.stt_provider = config_updates["stt_provider"]
        if "language" in config_updates:
            self.language = config_updates["language"]
        if "welcome_message" in config_updates:
            self.welcome_message = config_updates["welcome_message"]

def create_sip_adapter(username: str = "", password: str = "",
                      mode: str = "dev") -> SIPAdapter:
    """创建 SIP 适配器"""
    adapter = SIPAdapter()
    if username and password:
        adapter.authenticate({
            "sip_username": username,
            "sip_password": password,
            "sip_mode": mode,
        })
    return adapter
