"""
电话渠道适配器 (Twilio)

支持 Twilio 语音通话，含 TTS/STT
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)

logger = logging.getLogger(__name__)

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
            logger.exception(f"Voice connect error: {e}")
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
                call = self._client.calls.create(
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
                logger.info(f"Voice call initiated: {call_id}")
                return call_id

            elif message_type == "sms":
                # 发送短信
                message = self._client.messages.create(
                    to=chat_id,
                    from_=self.config.extra.get("from_number", ""),
                    body=content,
                )
                logger.info(f"SMS sent: {message.sid}")
                return message.sid

            else:
                logger.warning(f"Unsupported message type: {message_type}")
                return None

        except Exception as e:
            logger.exception(f"Voice send_message error: {e}")
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

        # 触发事件
        message = ChannelMessage(
            channel_type="voice",
            message_id=call_sid or "",
            sender_id=data.get("From", ""),
            sender_name="Voice User",
            content=data.get("SpeechResult", data.get("Body", "")),
            message_type="voice" if call_sid else "sms",
            chat_id=data.get("From", ""),
            chat_type="p2p",
            raw_event=data,
        )

        event_type = (
            ChannelEventType.MESSAGE_RECEIVED
            if call_status == "completed"
            else ChannelEventType.BOT_ERROR
        )
        await self._emit_event(event_type, message)

        # 返回 TwiML 响应
        if call_status == "ringing":
            return '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Hello from Neurova</Say></Response>'
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

    def get_call_status(self, call_id: str) -> Optional[Dict[str, Any]]:
        """获取通话状态"""
        return self._active_calls.get(call_id)


def create_voice_adapter(config: ChannelConfig) -> VoiceAdapter:
    """创建语音适配器实例"""
    return VoiceAdapter(config)
