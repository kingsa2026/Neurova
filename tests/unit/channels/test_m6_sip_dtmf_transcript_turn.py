# -*- coding: utf-8 -*-
"""M6 SIP 实时语音深度补全（多模态追平计划批一）——红→绿 TDD 判据。

两张卡点（当前代码均缺失，本文件先红）：
1. **DTMF 捕获→按键语义进回合**：pyVoIP 的真实捕获点在 RTP 层——
   ``RTPClient`` 解析 RFC2833 电话事件（payload 101）marker 包时回调
   ``client.dtmf(digit)``（pyVoIP 1.6.8 ``RTP.py:565``），该回调在
   ``VoIPCall`` 构造期被绑成 ``call.dtmf_callback``。适配器接手通话时把
   每个 ``RTPClient.dtmf`` 改绑到自身钩子，收号序列经
   ``voice_context_module.VOICE_CONTEXT_KEY`` 单源写入回合 metadata。
2. **通话转写闭环**：通话音频（pyVoIP ``read_audio``，8kHz·8bit PCM）→
   静默切轮（复用 ``asr.streaming.TurnEndpointDetector``，只读复用）→
   16kHz WAV → 既有 ASR 引擎（``voice_ingress.getAsrTranscriber`` 单源，
   与渠道预检 / /minutes 同源）→ 转写文本作为语音消息进回合。

信令层桩说明：本文件用 ``_StubCall``/``_StubRTPClient`` 顶替 pyVoIP 的
VoIPCall/RTPClient 形状（venv 未装 pyVoIP，且信令层不在本卡判定面）；
DTMF 触发走的是与 pyVoIP RTP 解析器**完全相同**的调用点
（``client.dtmf(digit)``），不是 MagicMock 恒真——桩只提供数据形状，
判定全部落在适配器的真实产物上。
"""

import inspect
import re
import threading
import time
from types import SimpleNamespace

import pytest

import neurova.channels.sip as sip_module
from neurova.channels.base import ChannelEventType
from neurova.channels.sip import SIPAdapter
from neurova.voice_context_module import DTMF_DIGITS_KEY, VOICE_CONTEXT_KEY, voiceContextLines

#: 与既有渠道语音测试同源的 ASR 真产物形状（funasr/mock 一致的三键）
ASR_PRODUCT = {"text": "帮我看下明天的排程", "language": "zh", "duration_sec": 1.2}

#: 8kHz·8bit 音频块：1600 字节 = 200ms
SPEECH_CHUNK = b"\xff\x00" * 800  # 满幅方波——能量远超 VAD 阈值
SILENCE_CHUNK = b"\x80" * 1600  # 静默（8bit 中点 128）


class _StubRTPClient:
    """pyVoIP RTPClient 的形状桩：dtmf 槽位即真实捕获点（RTP.py:565 调用）。"""

    def __init__(self):
        self.dtmf = None


class _StubCall:
    """pyVoIP VoIPCall 的形状桩（仅信令层替身；音频/状态按测试脚本走）。"""

    def __init__(self, chunks=None, call_id="call-m6", caller="1001"):
        self.RTPClients = [_StubRTPClient()]
        self.call_id = call_id
        self.request = SimpleNamespace(headers={"From": {"number": caller}})
        self.state = SimpleNamespace(name="RINGING")
        self.chunks = list(chunks or [])
        self.answered = False
        self.hangups = 0
        self.written = bytearray()

    def answer(self):
        self.answered = True
        self.state = SimpleNamespace(name="ANSWERED")

    def hangup(self):
        self.hangups += 1
        self.state = SimpleNamespace(name="ENDED")

    def read_audio(self, length=160, blocking=True):
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def write_audio(self, data):
        self.written += data


def _newAdapter():
    adapter = SIPAdapter()
    adapter.sip_mode = "dev"
    return adapter


def _captureAdapter(adapter):
    """挂事件回调，返回 capturer（同步收集 _emitInbound 投递的消息）。"""
    captured = []

    async def _cb(event_type, message):
        captured.append((event_type, message))

    adapter.set_event_callback(_cb)
    return captured


def _waitUntil(predicate, timeout=5.0, message="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _joinAudioThread(adapter, timeout=3.0):
    thread = getattr(adapter, "_audio_thread", None)
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)


# ============================================================
# 卡点 1：DTMF 捕获 → 按键语义进回合 metadata
# ============================================================


class TestDtmfReachesTheTurn:
    def testIncomingCallBindsDtmfCapturePointOnRtpClients(self):
        """来电接管时把 pyVoIP RTP 层的 dtmf 捕获点改绑到适配器钩子。"""
        adapter = _newAdapter()
        call = _StubCall()

        adapter._onIncomingCall(call)

        assert call.answered, "来电未被应答"
        for client in call.RTPClients:
            assert client.dtmf.__func__ is adapter._onDtmfEvent.__func__, (
                "RTP 层 dtmf 捕获点没有改绑到适配器钩子——DTMF 将只进 pyVoIP 内部缓冲，进不了回合")
            assert client.dtmf.__self__ is adapter, "捕获点未绑到本适配器实例"

    def testDtmfEventReachesTurnMetadata(self):
        """SIP 桩发 DTMF 事件（client.dtmf 逐位触发）→ 回合 metadata 出现按键语义。"""
        adapter = _newAdapter()
        captured = _captureAdapter(adapter)
        call = _StubCall(chunks=[])  # 无音频：音频循环即刻退出，不干扰判定
        adapter._onIncomingCall(call)
        _joinAudioThread(adapter)

        # 与 pyVoIP RTP 解析器同一触发形态：每个 RFC2833 事件回调一次
        for digit in "123":
            for client in call.RTPClients:
                client.dtmf(digit)
        adapter._flushDtmfTurn()

        assert captured, "DTMF 事件没有产生任何回合消息"
        event_type, message = captured[-1]
        assert event_type == ChannelEventType.MESSAGE_RECEIVED
        ctx = message.metadata.get(VOICE_CONTEXT_KEY)
        assert isinstance(ctx, dict), f"回合 metadata 没带语音上下文：{message.metadata.keys()}"
        assert ctx.get(DTMF_DIGITS_KEY) == "123", f"按键语义未入 voice_context：{ctx}"
        assert message.content == "123", "按键序列应作为正文进回合（通过路由非空闸）"
        assert message.message_type == "dtmf"
        assert message.chat_id == "call-m6"

    def testDtmfSequenceAutoFlushesAfterDebounce(self, monkeypatch):
        """数字停止后按去抖间隔自动冲出一个按键回合（不需要手工 flush）。"""
        monkeypatch.setattr(sip_module, "DTMF_FLUSH_INTERVAL_SEC", 0.05)
        adapter = _newAdapter()
        captured = _captureAdapter(adapter)
        call = _StubCall(chunks=[])
        adapter._onIncomingCall(call)
        _joinAudioThread(adapter)

        for digit in "9527":
            for client in call.RTPClients:
                client.dtmf(digit)

        assert _waitUntil(lambda: bool(captured)), "去抖窗口后未自动冲出按键回合"
        _, message = captured[-1]
        assert message.metadata[VOICE_CONTEXT_KEY][DTMF_DIGITS_KEY] == "9527"

    def testPendingDtmfFlushesOnHangup(self):
        """挂断时未冲出的收号序列必须补一个回合，不许静默丢失。"""
        adapter = _newAdapter()
        captured = _captureAdapter(adapter)
        call = _StubCall(chunks=[])
        adapter._onIncomingCall(call)
        _joinAudioThread(adapter)

        for client in call.RTPClients:
            client.dtmf("7")
        assert adapter.hangup_call("call-m6") is True

        assert _waitUntil(lambda: bool(captured)), "挂断时收号序列被丢弃"
        _, message = captured[-1]
        assert message.metadata[VOICE_CONTEXT_KEY][DTMF_DIGITS_KEY] == "7"


# ============================================================
# 卡点 2：通话音频 → 既有 ASR → 转写文本进回合
# ============================================================


class TestCallAudioTranscriptionLoop:
    def testCallAudioTurnTranscribesAndReachesTurn(self, monkeypatch):
        """桩音频（说话+静默）→ 切轮 → ASR → 转写文本作为语音消息进回合。"""
        seen_audio = []

        async def fake_transcribe(audio_bytes, **kw):
            seen_audio.append(audio_bytes)
            return dict(ASR_PRODUCT)

        monkeypatch.setattr(sip_module, "_get_asr_transcriber", lambda: fake_transcribe)
        adapter = _newAdapter()
        captured = _captureAdapter(adapter)
        chunks = [SPEECH_CHUNK, SPEECH_CHUNK] + [SILENCE_CHUNK] * 5
        call = _StubCall(chunks=chunks)

        adapter._onIncomingCall(call)

        assert _waitUntil(lambda: bool(captured)), "音频轮次未被转写进回合"
        _joinAudioThread(adapter)
        event_type, message = captured[-1]
        assert event_type == ChannelEventType.MESSAGE_RECEIVED
        assert message.content == ASR_PRODUCT["text"], (
            f"转写文本没有成为回合正文：{message.content!r}")
        assert message.message_type == "voice"
        assert message.metadata.get("voice_transcribed") is True
        ctx = message.metadata.get(VOICE_CONTEXT_KEY)
        assert isinstance(ctx, dict) and ctx.get("text") == ASR_PRODUCT["text"], (
            f"ASR 产物没有按单源键进回合：{message.metadata.keys()}")
        assert seen_audio and seen_audio[0][:4] == b"RIFF", (
            "转写输入应是包装好的 WAV（16kHz PCM16），实际不是")

    def testTranscriptionFailureEmitsNoTurn(self, monkeypatch, caplog):
        """ASR 失败/空结果：如实留日志，不产空转写回合（不虚构语音轮次）。"""
        async def failing_transcribe(audio_bytes, **kw):
            return {"text": "", "error": "no speech"}

        monkeypatch.setattr(sip_module, "_get_asr_transcriber", lambda: failing_transcribe)
        adapter = _newAdapter()
        captured = _captureAdapter(adapter)
        chunks = [SPEECH_CHUNK, SPEECH_CHUNK] + [SILENCE_CHUNK] * 5
        call = _StubCall(chunks=chunks)

        adapter._onIncomingCall(call)
        _joinAudioThread(adapter)

        assert captured == [], "转写失败不得伪造语音回合"
        assert any("转写" in r.message for r in caplog.records), "失败原因必须如实留日志"

    def testSipTranscriberComesFromIngressSingleSource(self):
        """教义第 6 条：SIP 通话转写必须取自 voice_ingress 的单一转写口。"""
        src = inspect.getsource(sip_module)
        assert re.search(
            r"from neurova\.channels\.voice_ingress import [^\n]*getAsrTranscriber", src
        ), "sip.py 应从 voice_ingress 取 ASR 转写口（与预检//minutes 同源）"
        assert "_get_asr_transcriber" in src, "缺少测试 patch 点（对齐 voice_precheck 风格）"


# ============================================================
# voice_context 单源：DTMF 按键语义的渲染词汇
# ============================================================


class TestVoiceContextRendersDtmf:
    def testDtmfDigitsKeyIsSingleSource(self):
        assert DTMF_DIGITS_KEY == "dtmf_digits"

    def testVoiceContextLinesRenderDtmfDigits(self):
        lines = voiceContextLines({"text": "", DTMF_DIGITS_KEY: "123"})
        assert any("DTMF" in line and "123" in line for line in lines), (
            f"按键语义没有渲染进 prompt 行：{lines}")

    def testVoiceContextLinesWithoutDtmfStayUnchanged(self):
        lines = voiceContextLines({"text": "只是语音"})
        assert any("只是语音" in line for line in lines)
        assert not any("DTMF" in line for line in lines), "无按键时不得渲染 DTMF 行"

    def testFullTurnMetadataRendersThroughSingleVocabulary(self):
        """端到端词汇咬合：DTMF 回合的 voice_context 能被唯一渲染口读出。"""
        ctx = {"text": "", DTMF_DIGITS_KEY: "9527", "engine": "sip-rfc2833"}
        lines = voiceContextLines(ctx)
        joined = "\n".join(lines)
        assert "9527" in joined and "DTMF" in joined
