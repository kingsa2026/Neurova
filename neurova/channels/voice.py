"""
电话渠道适配器 (Twilio)

支持 Twilio 语音通话，含 TTS/STT
"""

import asyncio
import time
from datetime import datetime, timezone

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.voice_context_module import DTMF_DIGITS_KEY, VOICE_CONTEXT_KEY

logger = get_logger(__name__)


class VoiceAdapter(ChannelAdapter):
    """
    语音通话适配器 (Twilio)

    支持:
    - 语音通话 (TTS)
    - 语音识别 (STT)
    - 语音消息收发
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "voice"
        self._client = None
        self._active_calls: Dict[str, Any] = {}

    async def connect(self) -> bool:
        """初始化 Twilio 连接"""
        try:
            from twilio.rest import Client

            account_sid = self.config.app_id
            auth_token = self.config.app_secret

            if not account_sid or not auth_token:
                logger.error("Twilio credentials not configured")
                return False

            self._client = Client(account_sid, auth_token)
            self._connected = True
            logger.info("Voice adapter connected to Twilio")
            return True

        except ImportError:
            logger.error("twilio not installed. Run: pip install twilio")
            return False
        except Exception as e:
            logger.exception("Voice connect error: %s", e)
            return False

    async def disconnect(self):
        """断开连接"""
        self._client = None
        self._connected = False
        self._active_calls.clear()
        logger.info("Voice adapter disconnected")

    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """
        发送语音消息或发起通话

        参数:
            chat_id: 电话号码 (E.164 格式)
            content: 消息内容 (文本将被 TTS 转换)
            message_type: "call" (语音通话) 或 "sms" (短信)
        """
        if not self._connected or not self._client:
            logger.error("Voice adapter not connected")
            return None

        try:
            if message_type == "call":
                # 发起语音通话
                # P1-16: Twilio SDK 是同步 HTTP，直调会阻塞事件循环——下沉工作线程
                call = await asyncio.to_thread(
                    self._client.calls.create,
                    to=chat_id,
                    from_=self.config.extra.get("from_number", ""),
                    twiml=f'<Response><Say voice="alice">{content}</Say></Response>',
                )
                call_id = call.sid
                self._active_calls[call_id] = {
                    "to": chat_id,
                    "content": content,
                    "status": "initiated",
                }
                logger.info("Voice call initiated: %s", call_id)
                return call_id

            elif message_type == "sms":
                # 发送短信（P1-16 同款：同步 SDK 下沉工作线程）
                message = await asyncio.to_thread(
                    self._client.messages.create,
                    to=chat_id,
                    from_=self.config.extra.get("from_number", ""),
                    body=content,
                )
                logger.info("SMS sent: %s", message.sid)
                return message.sid

            else:
                logger.warning("Unsupported message type: %s", message_type)
                return None

        except Exception as e:
            logger.exception("Voice send_message error: %s", e)
            return None

    async def handle_webhook(self, data: Dict[str, Any]) -> str:
        """
        处理 Twilio Webhook 回调

        返回 TwiML 响应
        """
        call_sid = data.get("CallSid")
        call_status = data.get("CallStatus")

        if call_sid in self._active_calls:
            self._active_calls[call_sid]["status"] = call_status

        speech_text = data.get("SpeechResult") or data.get("Body") or ""
        digits = (data.get("Digits") or "").strip()

        # L3：Gather 按键（Digits）非空时经 voice_context 单源进回合 metadata
        # （对齐 channels/sip.py 的 DTMF 按键回合形态），agent 侧由唯一渲染口
        # voiceContextLines 读出按键语义；语音正文不受影响。
        metadata: Dict[str, Any] = {}
        message_type = "voice" if call_sid else "sms"
        message_id = call_sid or ""
        content = speech_text
        if digits:
            metadata[VOICE_CONTEXT_KEY] = {
                "text": speech_text,
                DTMF_DIGITS_KEY: digits,
                "engine": "twilio-gather",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if not speech_text:
                # 纯按键回合：按键序列作正文（过路由非空闸）、独立消息类型，
                # 与 SIP 按键回合同形；同通话多轮 Gather 各自成回合。
                content = digits
                message_type = "dtmf"
                message_id = f"{call_sid or 'voice'}-dtmf-{int(time.time() * 1000)}"

        # 触发事件
        message = ChannelMessage(
            channel_type="voice",
            message_id=message_id,
            sender_id=data.get("From", ""),
            sender_name="Voice User",
            content=content,
            message_type=message_type,
            chat_id=data.get("From", ""),
            chat_type="p2p",
            raw_event=data,
            metadata=metadata,
        )

        # 带用户输入的回调（Gather 按键/语音、短信正文）是真实入站回合，必须以
        # MESSAGE_RECEIVED 进链——此前仅 completed 进链，mid-call 的用户输入
        # 被映射成 BOT_ERROR 后在 manager 分发链（只认 MESSAGE_RECEIVED）被丢。
        # 仅状态通报（ringing / 无输入的 completed 等）维持原事件映射。
        has_user_input = bool(speech_text) or bool(digits)
        if call_status == "completed" or has_user_input:
            event_type = ChannelEventType.MESSAGE_RECEIVED
        else:
            event_type = ChannelEventType.BOT_ERROR
        await self._emit_event(event_type, message)

        # 返回 TwiML 响应
        if call_status == "ringing":
            return '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Hello from Neurova</Say></Response>'
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

    def get_call_status(self, call_id: str) -> Optional[Dict[str, Any]]:
        """获取通话状态"""
        return self._active_calls.get(call_id)

    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查

        返回:
            Dict: 包含 connected, channel_type, last_error, active_calls 等
        """
        base_health = await super().health_check()
        base_health.update(
            {
                "active_calls_count": len(self._active_calls),
                "has_client": self._client is not None,
                "from_number": self.config.extra.get("from_number", ""),
            }
        )
        return base_health


def create_voice_adapter(config: ChannelConfig) -> VoiceAdapter:
    """创建语音适配器实例"""
    return VoiceAdapter(config)
