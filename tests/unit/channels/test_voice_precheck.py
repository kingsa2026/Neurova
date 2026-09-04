# -*- coding: utf-8 -*-
"""P1-12 渠道语音消息预转写（OpenClaw 音频预检启发）— TDD 测试

OC 语义：「音频预检——先转录再判断是否需要 @ 提及，群语音消息不漏」。
Neurova 落点：ChannelManager 收口处（_on_channel_event）对带 audio_bytes 的
voice/audio 消息先转写，替换 "[语音]" 占位为转写文本；转写失败降级保留占位，
绝不阻断消息处理链。等价性：无 audio_bytes 的消息行为完全不变。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.channels.base import ChannelMessage
from neurova.channels.voice_precheck import transcribe_voice_message


def _voice_msg(content="[语音]", audio_bytes=None, chat_type="group"):
    metadata = {"channel": "feishu"}
    if audio_bytes is not None:
        metadata["audio_bytes"] = audio_bytes
    return ChannelMessage(
        channel_type="feishu",
        message_id="m1",
        sender_id="u1",
        sender_name="张三",
        content=content,
        message_type="voice",
        chat_id="c1",
        chat_type=chat_type,
        metadata=metadata,
    )


class TestTranscribeVoiceMessage:
    @pytest.mark.asyncio
    async def test_transcribes_and_replaces_placeholder(self):
        msg = _voice_msg(audio_bytes=b"fake-audio")
        with patch(
            "neurova.channels.voice_precheck._get_asr_transcriber",
            return_value=AsyncMock(return_value={"text": "帮我查一下明天天气"}),
        ):
            out = await transcribe_voice_message(msg)
        assert out.content == "帮我查一下明天天气"
        assert out.metadata.get("voice_transcribed") is True
        # 原始字节保留（agent 侧语音链路兜底不受影响）
        assert out.metadata.get("audio_bytes") == b"fake-audio"

    @pytest.mark.asyncio
    async def test_no_audio_bytes_unchanged(self):
        """等价性：无 audio_bytes 的语音消息行为不变"""
        msg = _voice_msg()
        out = await transcribe_voice_message(msg)
        assert out.content == "[语音]"
        assert "voice_transcribed" not in out.metadata

    @pytest.mark.asyncio
    async def test_non_voice_message_unchanged(self):
        msg = ChannelMessage(
            channel_type="feishu", message_id="m2", sender_id="u1",
            sender_name="张三", content="普通文本", message_type="text",
            chat_id="c1", metadata={"audio_bytes": b"xx"},
        )
        out = await transcribe_voice_message(msg)
        assert out.content == "普通文本"

    @pytest.mark.asyncio
    async def test_asr_failure_degrades_to_placeholder(self):
        """转写失败降级：保留占位、标注失败、绝不抛异常"""
        msg = _voice_msg(audio_bytes=b"fake")

        async def _boom(b, **kw):
            raise RuntimeError("asr down")

        with patch(
            "neurova.channels.voice_precheck._get_asr_transcriber",
            return_value=_boom,
        ):
            out = await transcribe_voice_message(msg)
        assert out.content == "[语音]"
        assert out.metadata.get("voice_transcribed") is not True

    @pytest.mark.asyncio
    async def test_empty_transcript_keeps_placeholder(self):
        """空转写结果视为失败（不把占位替换成空串）"""
        msg = _voice_msg(audio_bytes=b"fake")
        with patch(
            "neurova.channels.voice_precheck._get_asr_transcriber",
            return_value=AsyncMock(return_value={"text": ""}),
        ):
            out = await transcribe_voice_message(msg)
        assert out.content == "[语音]"

    @pytest.mark.asyncio
    async def test_non_dict_result_degrades(self):
        """ASR 返回非 dict（防御）降级保留占位"""
        msg = _voice_msg(audio_bytes=b"fake")
        with patch(
            "neurova.channels.voice_precheck._get_asr_transcriber",
            return_value=AsyncMock(return_value="unexpected"),
        ):
            out = await transcribe_voice_message(msg)
        assert out.content == "[语音]"


class TestManagerWiring:
    """ChannelManager 收口接线：handler 链之前预转写"""

    @pytest.mark.asyncio
    async def test_on_channel_event_transcribes_before_handlers(self):
        from neurova.channels.manager import ChannelManager
        from neurova.channels.base import ChannelEventType

        mgr = ChannelManager()
        received = {}

        async def handler(message):
            received["content"] = message.content
            received["metadata"] = message.metadata
            return "ok"

        mgr.set_message_handler(handler)

        msg = _voice_msg(audio_bytes=b"fake")

        async def _fake_transcribe(m):
            m.content = "转写后的指令"
            m.metadata["voice_transcribed"] = True
            return m

        with patch(
            "neurova.channels.voice_precheck.transcribe_voice_message",
            side_effect=_fake_transcribe,
        ):
            await mgr._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, msg)

        assert received["content"] == "转写后的指令"
