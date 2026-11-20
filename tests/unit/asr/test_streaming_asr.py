# -*- coding: utf-8 -*-
"""流式 ASR 通道测试（对照报告 B4-1 落地：/api/v1/audio/asr/stream）。

锁定四件事：
1. TurnEndpointDetector——服务端 turn 终结（说话后静默≥阈值切轮；开口前
   静默不切；连续说话不切；超长强制切）
2. BatchTranscribeStreamingTurnSession——任意批式引擎的滑窗流式适配
3. FunASRStreamingTurnSession——paraformer-zh-streaming 的 cache/is_final 契约
4. WS 端点契约——鉴权 4401 / ready / partial / final(silence|finish|stop) /
   引擎不可用 error 帧
"""
import asyncio
import sys
import types

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient


def _pcm(ms: float, amplitude: int = 0, sample_rate: int = 16000) -> bytes:
    """ms 毫秒单声道 PCM16LE：amplitude=0 静音；>0 交变方波（有能量）。"""
    n = int(sample_rate * ms / 1000)
    out = bytearray()
    for i in range(n):
        v = amplitude if (i // 8) % 2 == 0 else -amplitude
        out += int(v).to_bytes(2, "little", signed=True)
    return bytes(out)


# ────────────────────────── 1. turn 终结检测 ──────────────────────────


class TestTurnEndpointDetector:
    def test_silence_after_speech_ends_turn(self):
        from neurova.asr.streaming import TurnEndpointDetector

        d = TurnEndpointDetector()
        assert d.feed(_pcm(500, amplitude=3000)) is False  # 500ms 语音
        assert d.feed(_pcm(100)) is False                  # 静默 100ms < 700ms
        assert d.feed(_pcm(700)) is True                   # 累计静默 800ms → 切轮
        assert d.end_reason == "silence"

    def test_continuous_speech_does_not_end(self):
        from neurova.asr.streaming import TurnEndpointDetector

        d = TurnEndpointDetector()
        for _ in range(30):
            assert d.feed(_pcm(100, amplitude=3000)) is False

    def test_silence_before_speech_does_not_end(self):
        from neurova.asr.streaming import TurnEndpointDetector

        d = TurnEndpointDetector()
        assert d.feed(_pcm(2000)) is False  # 开口前的静默不算轮末

    def test_max_turn_forces_end(self):
        from neurova.asr.streaming import TurnEndpointDetector

        d = TurnEndpointDetector(max_turn_ms=1000)
        assert d.feed(_pcm(1100, amplitude=3000)) is True
        assert d.end_reason == "max_duration"

    def test_reset_clears_state(self):
        from neurova.asr.streaming import TurnEndpointDetector

        d = TurnEndpointDetector()
        d.feed(_pcm(500, amplitude=3000))
        d.feed(_pcm(700))  # 此处已触发切轮
        d.reset()
        assert d.feed(_pcm(2000)) is False  # 重置后纯静默不再切轮


# ────────────────────────── 2. 批式引擎滑窗适配 ──────────────────────────


class TestBatchTranscribeStreamingTurnSession:
    def test_feed_transcribes_accumulated_audio(self):
        calls = []

        async def transcribe(audio_bytes, language="zh"):
            calls.append(len(audio_bytes))
            return {"text": f"文本{len(calls)}"}

        from neurova.asr.streaming import BatchTranscribeStreamingTurnSession

        s = BatchTranscribeStreamingTurnSession(transcribe, partial_interval_ms=0)
        assert asyncio.run(s.feed(_pcm(200, amplitude=3000))) == "文本1"
        assert asyncio.run(s.feed(_pcm(200, amplitude=3000))) == "文本2"
        # 200ms@16k PCM16 = 6400 字节；partial 转写的是**累计**音频
        assert calls == [6400, 12800]

    def test_partial_throttled_by_interval(self):
        calls = []

        async def transcribe(audio_bytes, language="zh"):
            calls.append(len(audio_bytes))
            return {"text": "x"}

        from neurova.asr.streaming import BatchTranscribeStreamingTurnSession

        s = BatchTranscribeStreamingTurnSession(transcribe, partial_interval_ms=10_000)
        asyncio.run(s.feed(_pcm(200, amplitude=3000)))
        asyncio.run(s.feed(_pcm(200, amplitude=3000)))
        assert calls == [6400]  # 间隔未到不重转

    def test_finish_transcribes_whole_turn(self):
        calls = []

        async def transcribe(audio_bytes, language="zh"):
            calls.append(len(audio_bytes))
            return {"text": "最终结果"}

        from neurova.asr.streaming import BatchTranscribeStreamingTurnSession

        s = BatchTranscribeStreamingTurnSession(transcribe, partial_interval_ms=10_000)
        asyncio.run(s.feed(_pcm(200, amplitude=3000)))
        assert asyncio.run(s.finish()) == "最终结果"
        assert calls == [6400, 6400]

    def test_error_result_raises(self):
        calls = []

        async def transcribe(audio_bytes, language="zh"):
            calls.append(1)
            if len(calls) == 1:
                return {"text": "ok"}
            return {"text": "", "error": "引擎炸了"}

        from neurova.asr.streaming import BatchTranscribeStreamingTurnSession

        s = BatchTranscribeStreamingTurnSession(transcribe)
        assert asyncio.run(s.feed(_pcm(200, amplitude=3000))) == "ok"
        with pytest.raises(RuntimeError):
            asyncio.run(s.finish())


# ────────────────────────── 3. FunASR 流式会话 ──────────────────────────


class TestFunASRStreamingTurnSession:
    @pytest.fixture()
    def fake_funasr(self, monkeypatch):
        """generate 返回**增量片段**（对齐真 paraformer-streaming 协议）。"""
        calls = []
        fake = types.ModuleType("funasr")

        class FakeAutoModel:
            def __init__(self, **kwargs):
                calls.append(("init", kwargs))

            def generate(self, input=None, cache=None, is_final=False, chunk_size=None, **kw):
                calls.append(("gen", int(len(input)), bool(is_final)))
                cache["n"] = cache.get("n", 0) + 1
                return [{"text": f"段{cache['n']}"}]

        fake.AutoModel = FakeAutoModel
        monkeypatch.setitem(sys.modules, "funasr", fake)
        return calls

    @pytest.fixture(autouse=True)
    def _fresh_model(self):
        from neurova.asr import streaming

        streaming.reset_funasr_streaming_model()
        yield
        streaming.reset_funasr_streaming_model()

    def test_create_loads_streaming_model(self, fake_funasr):
        from neurova.asr import streaming

        s = streaming.create_funasr_streaming_session("zh")
        assert s is not None
        # 流式专用模型 id（非批式 paraformer-zh）
        assert fake_funasr[0][1]["model"] == "paraformer-zh-streaming"

    def test_feed_accumulates_incremental_segments(self, fake_funasr):
        from neurova.asr import streaming

        s = streaming.create_funasr_streaming_session("zh")
        assert asyncio.run(s.feed(_pcm(100, amplitude=3000))) == "段1"
        assert asyncio.run(s.feed(_pcm(100, amplitude=3000))) == "段1段2"
        gen_calls = [c for c in fake_funasr if c[0] == "gen"]
        assert len(gen_calls) == 2
        assert all(c[2] is False for c in gen_calls)  # 中间帧不得 is_final

    def test_finish_sets_is_final(self, fake_funasr):
        from neurova.asr import streaming

        s = streaming.create_funasr_streaming_session("zh")
        asyncio.run(s.feed(_pcm(100, amplitude=3000)))
        assert asyncio.run(s.finish()) == "段1段2"
        assert fake_funasr[-1][0] == "gen" and fake_funasr[-1][2] is True

    def test_missing_funasr_returns_none(self, monkeypatch):
        from neurova.asr import streaming

        monkeypatch.setitem(sys.modules, "funasr", None)  # import 即失败
        assert streaming.create_funasr_streaming_session("zh") is None


# ────────────────────────── 4. WS 端点契约 ──────────────────────────


class FakeTurnSession:
    def __init__(self):
        self.fed: list = []
        self.finished = False
        self.closed = False

    async def feed(self, pcm: bytes) -> str:
        self.fed.append(len(pcm))
        return "部分文本"

    async def finish(self) -> str:
        self.finished = True
        return "最终文本"

    def close(self):
        self.closed = True


def _make_ws_client(monkeypatch, factory=None):
    """构造只挂 audio 路由的测试应用。

    factory：_create_streaming_session 的替身（None=引擎不可用）。
    鉴权：token == "tok" 通过，其余拒绝。
    """
    from neurova.api.endpoints import audio as audio_mod

    app = FastAPI()
    app.include_router(audio_mod.router, prefix="/audio")
    monkeypatch.setattr(
        "neurova.api.auth.verify_access_token",
        lambda token: {"sub": "tuser", "user_id": "tuser"} if token == "tok" else None,
    )
    if factory is None:
        monkeypatch.setattr(audio_mod, "_create_streaming_session", lambda language: (None, None))
    else:
        monkeypatch.setattr(audio_mod, "_create_streaming_session", lambda language: factory(language))
    return TestClient(app)


class TestAsrStreamEndpoint:
    def test_missing_token_rejected_4401(self, monkeypatch):
        client = _make_ws_client(monkeypatch)
        with pytest.raises(WebSocketDisconnect) as ei:
            with client.websocket_connect("/audio/asr/stream") as ws:
                ws.receive_json()
        assert ei.value.code == 4401

    def test_bad_token_rejected_4401(self, monkeypatch):
        client = _make_ws_client(monkeypatch)
        with pytest.raises(WebSocketDisconnect) as ei:
            with client.websocket_connect("/audio/asr/stream?token=wrong") as ws:
                ws.receive_json()
        assert ei.value.code == 4401

    def test_language_param_reaches_session_factory(self, monkeypatch):
        seen = {}

        def factory(language: str):
            seen["language"] = language
            return (FakeTurnSession(), "fake")

        client = _make_ws_client(monkeypatch, factory)
        with client.websocket_connect("/audio/asr/stream?token=tok&language=en") as ws:
            assert ws.receive_json()["type"] == "ready"
        assert seen["language"] == "en"

    def test_language_param_defaults_to_zh(self, monkeypatch):
        seen = {}

        def factory(language: str):
            seen["language"] = language
            return (FakeTurnSession(), "fake")

        client = _make_ws_client(monkeypatch, factory)
        with client.websocket_connect("/audio/asr/stream?token=tok") as ws:
            assert ws.receive_json()["type"] == "ready"
        assert seen["language"] == "zh"

    def test_engine_unavailable_sends_error_frame(self, monkeypatch):
        client = _make_ws_client(monkeypatch, factory=None)
        with client.websocket_connect("/audio/asr/stream?token=tok") as ws:
            frame = ws.receive_json()
            assert frame["type"] == "error"
            assert frame["code"] == "asr_unavailable"
            # 服务端已关连接：再读即断开
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    def test_ready_partial_and_finish_final(self, monkeypatch):
        sessions = []

        def factory(language: str):
            s = FakeTurnSession()
            sessions.append(s)
            return (s, "fake")

        client = _make_ws_client(monkeypatch, factory)
        with client.websocket_connect("/audio/asr/stream?token=tok") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready" and ready["engine"] == "fake"

            ws.send_bytes(_pcm(200, amplitude=3000))
            partial = ws.receive_json()
            assert partial["type"] == "partial" and partial["text"] == "部分文本"
            assert partial["turn_id"] == 0

            ws.send_json({"type": "finish"})
            final = ws.receive_json()
            assert final["type"] == "final" and final["text"] == "最终文本"
            assert final["reason"] == "finish" and final["turn_id"] == 0
            assert sessions[0].finished is True

            # finish 之后连接仍可用：下一轮 turn_id 递增
            ws.send_bytes(_pcm(200, amplitude=3000))
            partial2 = ws.receive_json()
            assert partial2["type"] == "partial" and partial2["turn_id"] == 1

            ws.send_json({"type": "stop"})
            # stop：先收 final（reason=stop）再断开
            stop_final = ws.receive_json()
            assert stop_final["type"] == "final" and stop_final["reason"] == "stop"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    def test_silence_auto_final_then_next_turn(self, monkeypatch):
        sessions = []

        def factory(language: str):
            s = FakeTurnSession()
            sessions.append(s)
            return (s, "fake")

        client = _make_ws_client(monkeypatch, factory)
        with client.websocket_connect("/audio/asr/stream?token=tok") as ws:
            assert ws.receive_json()["type"] == "ready"

            # 一帧里：500ms 语音 + 800ms 静默 → 服务端自动切轮
            ws.send_bytes(_pcm(500, amplitude=3000) + _pcm(800))
            partial = ws.receive_json()
            assert partial["type"] == "partial"
            final = ws.receive_json()
            assert final["type"] == "final" and final["reason"] == "silence"
            assert sessions[0].finished is True

            # 下一轮：turn_id 递增，旧会话已 close
            ws.send_bytes(_pcm(200, amplitude=3000))
            partial2 = ws.receive_json()
            assert partial2["turn_id"] == 1
            assert sessions[0].closed is True
            assert len(sessions) == 2
