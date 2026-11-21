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

import array
import asyncio
import io
import json
import logging
import threading
import time
import wave
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    import pyvoip

    PYVOIP_AVAILABLE = True
except ImportError:
    PYVOIP_AVAILABLE = False

try:
    # M6：VoIPPhone 是 pyVoIP 唯一提供通话对象/DTMF/RTP 音频的入口——
    # 裸 SIPClient 拿不到 VoIPCall（DTMF 捕获与音频转写都无从谈起）。
    from pyvoip.VoIP import VoIPPhone as _PyVoIPPhone

    PYVOIP_PHONE_AVAILABLE = True
except ImportError:
    _PyVoIPPhone = None
    PYVOIP_PHONE_AVAILABLE = False

try:
    # 原代码此处误写为 `pass`，requests 从未被导入
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from neurova.asr.streaming import TurnEndpointDetector
from neurova.channels import ChannelAdapter, ChannelConfig, ContentType, MessageChannel, UnifiedMessage
from neurova.channels.base import ChannelEventType, ChannelMessage
from neurova.channels.voice_ingress import getAsrTranscriber
from neurova.voice_context_module import DTMF_DIGITS_KEY, VOICE_CONTEXT_KEY

#: DTMF 收号去抖：最后一个数字事件后静默多久，就把整串收号冲成一个按键回合。
DTMF_FLUSH_INTERVAL_SEC = 1.2

#: 通话音频单次读取字节数（pyVoIP read_audio：8kHz·8bit，160 字节=20ms）。
CALL_AUDIO_CHUNK_BYTES = 160

#: 一轮通话音频转写的等待上限（秒）——与渠道语音预检同一量级。
CALL_TRANSCRIBE_TIMEOUT_SEC = 20.0

#: 通话音频的采样率（pyVoIP RTP PCMU 解码后为 8kHz）。
CALL_AUDIO_SAMPLE_RATE = 8000


def _get_asr_transcriber():
    """SIP 通话转写的 patch 点：口径本体在 `voice_ingress.getAsrTranscriber`（单一事实源）。

    与渠道语音预检（voice_precheck）、/minutes 纪要链同一取法——通话音频的
    转写引擎链不另接第二份装配。
    """
    return getAsrTranscriber()


def _pcm8ToPcm16(data: bytes) -> bytes:
    """pyVoIP read_audio 的 8bit 无符号 PCM（WAV 8bit 口径）→ 16bit 小端 PCM。

    VAD（TurnEndpointDetector.feed）与 WAV 包装都吃 16bit 有符号样本。
    """
    return array.array("h", ((b - 128) << 8 for b in data)).tobytes()


def _pcm8kToWav16k(pcm8k: bytes) -> bytes:
    """把一轮 8kHz·8bit 通话音频升采样并包装成 16kHz·16bit 单声道 WAV。

    与 DashScope/本地引擎的 16k 口径一致；audioop 是 pyVoIP 自身的同款依赖
    （Python 3.12 可用），在函数内导入避免模块导入期触发弃用警告。
    """
    import audioop

    pcm16 = _pcm8ToPcm16(pcm8k)
    upsampled, _ = audioop.ratecv(pcm16, 2, 1, CALL_AUDIO_SAMPLE_RATE, 16000, None)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(upsampled)
    return buf.getvalue()


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
        # Gen2 契约：走基类构造获得 config/_connected/_event_callback。
        # 此前未调 super().__init__，channel_type/health_check/_emit_event 恒 AttributeError
        super().__init__(ChannelConfig(channel_type="sip", enabled=False))
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

        # M6：dev 模式通话/DTMF/音频转写状态
        self._voip_phone = None
        self._audio_thread: Optional[threading.Thread] = None
        self._dtmf_digits: list = []
        self._dtmf_timer: Optional[threading.Timer] = None
        self._dtmf_lock = threading.Lock()
        # 事件循环（connect 时捕获）：pyVoIP 线程把入站回合投回应用循环用
        self._loop = None

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
            logging.warning("SIP 通道未实现: pyVoIP 未安装，Dev 模式不可用（安装命令: pip install pyvoip）")
            return False

        try:
            server = self.sip_server if self.sip_server else None
            if PYVOIP_PHONE_AVAILABLE:
                # M6：走 VoIPPhone——pyVoIP 的通话（VoIPCall）/DTMF（RFC2833）/RTP
                # 音频都挂在 VoIPPhone→VoIPCall 链上，裸 SIPClient 拿不到通话对象。
                self._voip_phone = _PyVoIPPhone(
                    server=server,
                    port=self.sip_port,
                    username=self.sip_username,
                    password=self.sip_password,
                    callCallback=self._onIncomingCall,
                    sipPort=self.sip_port,
                )
                self._voip_client = getattr(self._voip_phone, "sip", self._voip_phone)
                self._voip_phone.start()
                logging.info("SIP Dev 模式初始化成功（VoIPPhone）- 用户: %s", self.sip_username)
            else:
                # 兼容路径：仅暴露裸 SIPClient 的 pyVoIP 变体（无通话/DTMF 能力，
                # 只保留注册语义）。真实 pyVoIP 1.6.x 恒走上面的 VoIPPhone 分支。
                self._voip_client = pyvoip.SIPClient(
                    server=server,
                    port=self.sip_port,
                    username=self.sip_username,
                    password=self.sip_password,
                    transport=self.transport_protocol.lower(),
                )
                self._voip_client.register()
                logging.info("SIP Dev 模式初始化成功 - 用户: %s", self.sip_username)

            self._initialized = True
            return True
        except (OSError, requests.RequestException, ValueError) as e:
            logging.error("SIP Dev 模式初始化失败: %s", e)
            return False

    def _init_production_mode(self) -> bool:
        """
        Production 模式初始化 - 使用 LiveKit SIP Server

        LiveKit SIP Server 对接从未实现——与 connect 诚实语义一致，
        绝不虚构"初始化成功"（原无条件 _initialized=True/return True 假成功已清除）。
        """
        logging.warning("SIP 通道未实现: Production 模式（LiveKit SIP Server）未实现")
        return False

    async def connect(self) -> bool:
        """Gen2 契约：SIP 协议栈未实现——配置校验后诚实失败（禁假成功）。

        此前缺 connect 实现，抽象类无法实例化；这里只做真实可行的配置校验，
        绝不虚构 SIP 能力：启用/测试 sip 渠道如实返回不可用。
        """
        # M6：在异步生命周期入口捕获应用事件循环——pyVoIP 的信令/RTP 线程
        # 捕获到 DTMF/音频转写后，经它把入站回合投回渠道事件链。
        self._loop = asyncio.get_running_loop()
        if self.sip_mode == "dev" and self._initialized and self._voip_phone is not None:
            # dev 模式（VoIPPhone 已注册就绪）是真实可用的通路：SIP 监听、
            # 通话、DTMF、RTP 音频都在本进程跑通。此前"协议栈未实现"的诚实
            # 失败只覆盖 production（LiveKit）与未初始化两种态，不变。
            self._connected = True
            logging.info("SIP dev 通道已连接（VoIPPhone 就绪，用户: %s）", self.sip_username)
            return True
        if not self.sip_username or not self.sip_password:
            logging.error("SIP connect 失败: 用户名和密码未配置")
            return False
        logging.warning("SIP 通道未实现")
        return False

    async def disconnect(self):
        """Gen2 契约：清理通话会话与客户端引用"""
        phone = self._voip_phone
        self._call_session = None
        self._voip_client = None
        self._voip_phone = None
        self._connected = False
        if phone is not None:
            try:
                phone.stop()
            except Exception as e:  # noqa: BLE001 - 停机失败不阻断清理，如实留痕
                logging.error("SIP VoIPPhone 停止失败: %s", e)
        logging.info("SIP adapter disconnected")

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
            # 任务2（台账 2026-09-11 渠道域收尾）：requests 缺失禁止假成功
            # （原虚构空音频数据），与 B-3/B-9 诚实语义一致。
            logging.warning("SIP 通道未实现: requests 未安装，TTS 不可用（安装命令: pip install requests）")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }

            payload = {
                "model": "sambert-zhichu-v1",
                "input": {"text": text},
                "parameters": {
                    "voice": self.tts_voice,
                    "format": "wav",
                    "sample_rate": 16000,
                },
            }

            resp = requests.post(self.DASHSCOPE_TTS_URL, headers=headers, json=payload, timeout=30)

            if resp.status_code == 200:
                result = resp.json()
                if "output" in result and "audio" in result["output"]:
                    # 返回音频 URL 或直接音频数据
                    audio_data = result["output"]["audio"]
                    logging.info("TTS 转换成功")
                    return audio_data

            logging.error("TTS 转换失败: %s", resp.json())
            return None
        except (requests.RequestException, json.JSONDecodeError) as e:
            logging.error("TTS 转换异常: %s", e)
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
            # 同 text_to_speech：requests 缺失禁止虚构识别文本（原假数据）。
            logging.warning("SIP 通道未实现: requests 未安装，STT 不可用（安装命令: pip install requests）")
            return None

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
                timeout=30,
            )

            if resp.status_code == 200:
                result = resp.json()
                if "output" in result and "text" in result["output"]:
                    text = result["output"]["text"]
                    logging.info("STT 转换成功: %s", text[:50])
                    return text

            logging.error("STT 转换失败: %s", resp.json())
            return None
        except Exception as e:
            logging.error("STT 转换异常: %s", e)
            return None

    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """Gen2 契约 + M6 dev 通路：活跃 dev 通话时文本经 TTS→RTP 真发送；
        其余情形诚实返回 None（禁假成功）。

        dev 路径在 M6 之前不可达（_call_session 恒 None）；VoIPPhone 接通后
        它成为真实通路：TTS 合成 → write_audio 写入 RTP。production/LiveKit
        通路仍未实现，维持诚实失败。
        """
        if self.sip_mode == "dev" and self._call_session is not None and (content or "").strip():
            audio = self.text_to_speech(content)
            if not audio:
                logging.error("SIP 回复 TTS 失败（未配置 DashScope key 或转换失败），音频回复未发送")
                return None
            if self._send_dev_audio(audio, chat_id):
                return f"sip-audio-{int(time.time() * 1000)}"
            return None
        logging.warning("SIP 通道未实现")
        return None

    def _send_dev_audio(self, audio_data: bytes, chat_id: str) -> bool:
        """Dev 模式发送音频（pyVoIP VoIPCall.write_audio → RTP）"""
        if not PYVOIP_AVAILABLE:
            logging.warning("SIP 通道未实现: pyVoIP 未安装，Dev 模式音频发送不可用")
            return False

        try:
            # 在现有通话中发送音频
            if self._call_session:
                self._call_session.write_audio(audio_data)
                return True
            else:
                logging.warning("没有活跃的通话会话")
                return False
        except Exception as e:
            logging.error("发送音频异常: %s", e)
            return False

    def _send_production_audio(self, audio_data: bytes, chat_id: str) -> bool:
        """Production 模式发送音频——LiveKit 通路未实现，诚实失败（原无条件 return True 已清除）"""
        logging.warning("SIP 通道未实现: Production 模式音频发送未实现")
        return False

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
                logging.error("解码音频数据失败: %s", e)

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
            return (
                self._send_dev_audio(audio_data, chat_id)
                if self.sip_mode == "dev"
                else self._send_production_audio(audio_data, chat_id)
            )
        return False

    def hangup_call(self, call_id: str) -> bool:
        """挂断通话"""
        if self.sip_mode == "dev" and self._call_session:
            try:
                self._call_session.hangup()
                self._call_session = None
                # M6：挂断前未冲出的收号序列补一个按键回合，不静默丢失
                self._flushDtmfTurn()
                return True
            except Exception as e:
                logging.error("挂断通话失败: %s", e)
                return False
        return True

    # ============================================================
    # M6：DTMF 捕获与通话音频转写闭环
    # ============================================================

    def _onIncomingCall(self, call) -> None:
        """pyVoIP VoIPPhone 来电回调（信令线程）：接管通话并接线 DTMF/音频。

        pyVoIP 在 VoIPCall 构造期就把 RTP 解析器的 dtmf 回调绑到
        ``call.dtmf_callback``（RTPClient 内部缓冲用），本方法把每个
        ``RTPClient.dtmf`` 改绑到适配器钩子——同一捕获点（RFC2833 电话
        事件 marker 包触发），按键语义才能进回合而不是只进 pyVoIP 缓冲。
        """
        self._call_session = call
        with self._dtmf_lock:
            self._dtmf_digits = []
        for client in getattr(call, "RTPClients", []) or []:
            try:
                client.dtmf = self._onDtmfEvent
            except Exception as e:  # noqa: BLE001 - 单个 RTP 绑定失败不放弃其余
                logging.error("SIP DTMF 捕获点接线失败: %s", e)
        try:
            call.answer()
        except Exception as e:  # noqa: BLE001 - 应答失败如实留痕，音频循环自会退出
            logging.error("SIP 来电应答失败: %s", e)
        self._startAudioTurnLoop(call)

    def _onDtmfEvent(self, digit: str) -> None:
        """pyVoIP RTP 层 DTMF 捕获点（RFC2833 电话事件，每位数字一次）。"""
        if not digit:
            return
        with self._dtmf_lock:
            self._dtmf_digits.append(str(digit))
            digits = "".join(self._dtmf_digits)
        logging.info("SIP DTMF 捕获: %s（累计 %s）", digit, digits)
        self._scheduleDtmfFlush()

    def _scheduleDtmfFlush(self) -> None:
        """收号去抖：数字停止 DTMF_FLUSH_INTERVAL_SEC 后冲出一个按键回合。"""
        with self._dtmf_lock:
            if not self._dtmf_digits:
                return
            if self._dtmf_timer is not None:
                self._dtmf_timer.cancel()
            self._dtmf_timer = threading.Timer(DTMF_FLUSH_INTERVAL_SEC, self._flushDtmfTurn)
            self._dtmf_timer.daemon = True
            self._dtmf_timer.start()

    def _flushDtmfTurn(self) -> None:
        """把收号序列作为一个按键回合冲出（voice_context 单源注入 metadata）。"""
        with self._dtmf_lock:
            if self._dtmf_timer is not None:
                self._dtmf_timer.cancel()
                self._dtmf_timer = None
            digits = "".join(self._dtmf_digits)
            self._dtmf_digits = []
        if not digits:
            return
        call = self._call_session
        caller = self._callerId(call)
        voice_context = {
            "text": "",
            DTMF_DIGITS_KEY: digits,
            "engine": "sip-rfc2833",
            "language": self.language or "zh",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        message = self._make_message(
            message_id=f"sip-dtmf-{int(time.time() * 1000)}",
            sender_id=caller or "sip-caller",
            sender_name=caller or "SIP 来电",
            content=digits,
            chat_id=self._currentCallId(call),
            message_type="dtmf",
            raw_event={"transport": "sip", "dtmf": digits},
            metadata={VOICE_CONTEXT_KEY: voice_context},
        )
        logging.info("SIP 按键回合冲出: digits=%s", digits)
        self._emitInbound(message)

    def _startAudioTurnLoop(self, call) -> None:
        thread = threading.Thread(
            target=self._audioTurnLoop, args=(call,), name="sip-audio-turn", daemon=True
        )
        self._audio_thread = thread
        thread.start()

    def _audioTurnLoop(self, call) -> None:
        """通话音频→静默切轮→ASR 转写→语音回合（M6 闭环）。

        形态对齐 /minutes 纪要链：转写是秒级重活，在独立线程内用临时事件
        循环跑完，不占应用循环。音频来自 pyVoIP ``read_audio``（8kHz·8bit）。
        """
        detector = TurnEndpointDetector(sample_rate=CALL_AUDIO_SAMPLE_RATE)
        turn_audio = bytearray()
        while self._call_session is call:
            state_name = getattr(getattr(call, "state", None), "name", "")
            if state_name == "ENDED":
                break
            try:
                data = call.read_audio(CALL_AUDIO_CHUNK_BYTES, blocking=True)
            except Exception as e:  # noqa: BLE001 - 读失败=本通话音频终止，如实留痕
                logging.error("SIP 通话音频读取失败: %s", e)
                break
            if not data:
                break
            turn_audio += data
            if detector.feed(_pcm8ToPcm16(data)):
                self._finalizeTurnInThread(call, bytes(turn_audio), detector.voiced_ms)
                turn_audio = bytearray()
                detector.reset()
        if turn_audio:
            self._finalizeTurnInThread(call, bytes(turn_audio), detector.voiced_ms)
        # 尾随按键仍走去抖冲刷（不立即冲，避免把正在输入的序列拦腰截断）
        self._scheduleDtmfFlush()

    def _finalizeTurnInThread(self, call, pcm8k: bytes, voicedMs: int) -> None:
        """音频线程内完成一轮转写并投递回合（转写失败不伪造空回合）。"""
        if not pcm8k or voicedMs <= 0:
            # 纯静默段不成语音回合：真引擎对静默给空文本（如实不成轮），
            # mock 引擎对任何字节都给文本——统一在切轮源头拦截，不留静默假回合。
            return
        try:
            message = asyncio.run(self._finalizeAudioTurn(call, pcm8k, voicedMs))
        except Exception as e:  # noqa: BLE001 - 单轮失败不影响通话其余轮次
            logging.error("SIP 通话音频转写回合失败: %s", e)
            return
        if message is not None:
            self._emitInbound(message)

    async def _finalizeAudioTurn(self, call, pcm8k: bytes, voicedMs: int = 0) -> Optional[ChannelMessage]:
        """一轮通话音频 → 既有 ASR 引擎 → 语音消息（ASR 真产物按单源键携带）。"""
        wav_bytes = _pcm8kToWav16k(pcm8k)
        try:
            transcriber = _get_asr_transcriber()
            result = await asyncio.wait_for(
                transcriber(wav_bytes), timeout=CALL_TRANSCRIBE_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            logging.warning("SIP 通话转写超时（%ss），本轮不进回合", CALL_TRANSCRIBE_TIMEOUT_SEC)
            return None
        except Exception as e:  # noqa: BLE001 - 转写失败如实降级，不产假回合
            logging.warning("SIP 通话转写失败: %s", e)
            return None
        text = ""
        if isinstance(result, dict):
            text = (result.get("text") or "").strip()
        if not text:
            logging.warning("SIP 通话转写空结果，本轮不进回合")
            return None
        caller = self._callerId(call)
        message = self._make_message(
            message_id=f"sip-voice-{int(time.time() * 1000)}",
            sender_id=caller or "sip-caller",
            sender_name=caller or "SIP 来电",
            content=text,
            chat_id=self._currentCallId(call),
            message_type="voice",
            raw_event={
                "transport": "sip",
                "voiced_ms": voicedMs,
            },
            metadata={
                "voice_transcribed": True,
                "voice_transcript": text,
                VOICE_CONTEXT_KEY: result,
            },
        )
        logging.info("SIP 通话转写进回合: len=%s", len(text))
        return message

    def _emitInbound(self, message: ChannelMessage) -> None:
        """把入站回合投进渠道事件链（pyVoIP 线程安全）。

        有应用事件循环时经 ``run_coroutine_threadsafe`` 投回；无循环环境
        （单测/函数级 live-verify）当场跑完。
        """
        coro = self._emit_event(ChannelEventType.MESSAGE_RECEIVED, message)
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            asyncio.run(coro)

    @staticmethod
    def _callerId(call) -> str:
        """从来电信令里取主叫号码（pyVoIP request.headers['From']）。"""
        request = getattr(call, "request", None)
        headers = getattr(request, "headers", None) or {}
        sender = headers.get("From") or {}
        if isinstance(sender, dict):
            return str(sender.get("number") or sender.get("uri") or "")
        return ""

    @staticmethod
    def _currentCallId(call) -> str:
        return str(getattr(call, "call_id", "") or "")

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


def create_sip_adapter(username: str = "", password: str = "", mode: str = "dev") -> SIPAdapter:
    """创建 SIP 适配器"""
    adapter = SIPAdapter()
    if username and password:
        adapter.authenticate(
            {
                "sip_username": username,
                "sip_password": password,
                "sip_mode": mode,
            }
        )
    return adapter
