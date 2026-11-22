# -*- coding: utf-8 -*-
"""L3 Twilio Digits 接入（多模态追平计划语音域遗留）——红→绿 TDD 判据。

缺口：`voice.py handle_webhook` 只读 ``SpeechResult``/``Body``（语音与文本），
未读 Twilio Gather 的 ``Digits`` 字段——电话按键输入被整体丢弃。

改法对齐 `channels/sip.py` 上批 M6 形态：Digits 非空时经
`voice_context_module` 的单源键（``VOICE_CONTEXT_KEY``/``DTMF_DIGITS_KEY``）
把按键语义写进回合 metadata，读侧由唯一渲染口 ``voiceContextLines`` 拼行；
纯按键回合正文带按键序列（过路由非空闸，与 SIP 按键回合同形）。

判定面：适配器产物（事件类型、metadata、TwiML）。webhook HTTP 路由本批
刻意不接（见 test_channelVoiceFactorySeamCloses 的安全边界登记），本卡只
负责让 handle_webhook 把按键语义带上回合。
"""

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.voice import VoiceAdapter
from neurova.voice_context_module import (
    DTMF_DIGITS_KEY,
    VOICE_CONTEXT_KEY,
    voiceContextLines,
)


def _adapter() -> VoiceAdapter:
    return VoiceAdapter(ChannelConfig(channel_type="voice"))


def _capture(adapter: VoiceAdapter) -> list:
    captured = []

    async def _cb(event_type, message):
        captured.append((event_type, message))

    adapter.set_event_callback(_cb)
    return captured


class TestDigitsReachTheTurn:
    @pytest.mark.asyncio
    async def testDigitsWebhookCarriesDtmfSemantics(self):
        """POST 带 Digits=1234 的 Gather 回调 → 回合 metadata 出现按键语义。"""
        adapter = _adapter()
        captured = _capture(adapter)

        twiml = await adapter.handle_webhook({
            "CallSid": "CA-digits-1",
            "CallStatus": "in-progress",
            "From": "+8613800000000",
            "Digits": "1234",
        })

        assert captured, "Digits webhook 没有产生任何回合消息"
        event_type, message = captured[-1]
        # 按键是真实入站回合：必须以 MESSAGE_RECEIVED 进链（BOT_ERROR 不进回合）
        assert event_type == ChannelEventType.MESSAGE_RECEIVED, (
            f"按键回合没有按入站消息进链：{event_type}")
        ctx = message.metadata.get(VOICE_CONTEXT_KEY)
        assert isinstance(ctx, dict), f"回合 metadata 没带语音上下文：{message.metadata.keys()}"
        assert ctx.get(DTMF_DIGITS_KEY) == "1234", f"按键语义未入 voice_context：{ctx}"
        assert message.content == "1234", "纯按键回合正文应带按键序列（过路由非空闸）"
        assert message.message_type == "dtmf"
        assert message.chat_id == "+8613800000000"
        # Twilio 回复：合法 XML 空响应
        assert twiml.lstrip().startswith("<?xml"), f"回复不是合法 TwiML：{twiml!r}"
        assert "<Response" in twiml

    @pytest.mark.asyncio
    async def testSpeechAndDigitsBothPresentKeepsSpeechAndAddsDigits(self):
        """Gather 同时带回语音与按键：语音仍作正文，按键进 voice_context。"""
        adapter = _adapter()
        captured = _capture(adapter)

        await adapter.handle_webhook({
            "CallSid": "CA-mix",
            "CallStatus": "in-progress",
            "From": "+8613800000000",
            "SpeechResult": "帮我查话费",
            "Digits": "1",
        })

        assert captured
        _, message = captured[-1]
        assert message.content == "帮我查话费", "既有语音正文不得被按键顶掉"
        assert message.message_type == "voice"
        ctx = message.metadata.get(VOICE_CONTEXT_KEY)
        assert isinstance(ctx, dict) and ctx.get(DTMF_DIGITS_KEY) == "1", (
            f"混合回合没带按键语义：{message.metadata.keys()}")
        assert ctx.get("text") == "帮我查话费"

    def testVoiceContextLinesRenderTwilioDigits(self):
        """按键语义能被唯一渲染口读出（读写两侧词汇咬合）。"""
        lines = voiceContextLines(
            {"text": "", DTMF_DIGITS_KEY: "1234", "engine": "twilio-gather"}
        )
        joined = "\n".join(lines)
        assert "1234" in joined and "DTMF" in joined, f"渲染口读不出按键：{lines}"


class TestNoDigitsLegacyPathsUnchanged:
    @pytest.mark.asyncio
    async def testSpeechResultPathUnchanged(self):
        """无 Digits 的语音转写路径回归不变：正文=SpeechResult，不带按键语义。"""
        adapter = _adapter()
        captured = _capture(adapter)

        await adapter.handle_webhook({
            "CallSid": "CA-speech",
            "CallStatus": "completed",
            "From": "+8613800000000",
            "SpeechResult": "你好",
        })

        assert captured
        event_type, message = captured[-1]
        assert event_type == ChannelEventType.MESSAGE_RECEIVED
        assert message.content == "你好"
        assert message.message_type == "voice"
        assert DTMF_DIGITS_KEY not in (message.metadata.get(VOICE_CONTEXT_KEY) or {})

    @pytest.mark.asyncio
    async def testRingingStillGreetsWithTwiml(self):
        """响铃路径回归不变：状态事件 + 问候 TwiML，不带按键语义。"""
        adapter = _adapter()
        captured = _capture(adapter)

        twiml = await adapter.handle_webhook({
            "CallSid": "CA-ring",
            "CallStatus": "ringing",
            "From": "+8613800000000",
        })

        assert captured
        event_type, message = captured[-1]
        assert event_type == ChannelEventType.BOT_ERROR
        assert VOICE_CONTEXT_KEY not in message.metadata
        assert "<Say>" in twiml

    @pytest.mark.asyncio
    async def testEmptyDigitsIsIgnored(self):
        """Digits 为空串视同未提供：不得写入空按键语义。"""
        adapter = _adapter()
        captured = _capture(adapter)

        await adapter.handle_webhook({
            "CallSid": "CA-empty",
            "CallStatus": "in-progress",
            "From": "+8613800000000",
            "Digits": "",
        })

        assert captured
        _, message = captured[-1]
        assert VOICE_CONTEXT_KEY not in message.metadata
