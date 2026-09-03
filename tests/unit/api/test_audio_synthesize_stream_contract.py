# -*- coding: utf-8 -*-
"""synthesize-stream 端点诚实性契约（2026-09-03）。

实测事故链：引擎链失败时端点返回 200+0 字节 → 前端 0 字节 blob →
<audio> Range 请求必 416。且 MIME/引擎名在流式生成器运行前声明——
fallback 实际切到 edge（MP3）时头部仍标 moss/audio/wav（撒谎）。

契约锁定：
1. 引擎空流 → 502（不再 200+0 字节）；
2. 引擎即抛错 → 502 带原因；
3. 首个 chunk 取出后才声明 MIME/引擎名（fallback 后头部说真话）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import audio as audio_api


class _FakeEngine:
    """第一块取出前暴露 wav、取出后暴露 mpeg —— 模拟 fallback 换引擎。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._started = False

    @property
    def is_initialized(self):
        return True

    @property
    def audio_media_type(self):
        # 流式开始（首个 chunk 被拉取）前是 moss(wav)，之后是 edge(mpeg)
        return "audio/mpeg" if self._started else "audio/wav"

    def get_engine_name(self):
        return "edge-tts" if self._started else "moss-nano"

    async def synthesize_stream(self, text, **kwargs):
        self._started = True
        for chunk in self._chunks:
            yield chunk


class _EmptyEngine(_FakeEngine):
    pass


def _client(fake_tts, monkeypatch):
    monkeypatch.setattr(audio_api, "_get_tts_manager", lambda: fake_tts)
    app = FastAPI()
    app.include_router(audio_api.router, prefix="/api/v1/audio")
    return TestClient(app)


def test_stream_returns_502_on_empty_engine(monkeypatch):
    """空流 → 502，不静默发 200+0 字节（前端 0 字节 blob 的根因）。"""
    client = _client(_EmptyEngine(chunks=[]), monkeypatch)
    resp = client.post("/api/v1/audio/synthesize-stream", json={"text": "你好"})
    assert resp.status_code == 502
    assert "未产出音频" in resp.json()["detail"]


def test_stream_returns_502_on_engine_error(monkeypatch):
    class _BrokenEngine:
        @property
        def is_initialized(self):
            return True

        def get_engine_name(self):
            return "moss-nano"

        async def synthesize_stream(self, text, **kwargs):
            raise RuntimeError("moss broken")
            yield b""  # pragma: no cover

    client = _client(_BrokenEngine(), monkeypatch)
    resp = client.post("/api/v1/audio/synthesize-stream", json={"text": "你好"})
    assert resp.status_code == 502
    assert "moss broken" in resp.json()["detail"]


def test_stream_headers_reflect_engine_after_first_chunk(monkeypatch):
    """MIME/引擎名必须反映实际产出引擎（fallback 后不得标 moss/audio/wav）。"""
    client = _client(_FakeEngine(chunks=[b"\xff\xf3data1", b"data2"]), monkeypatch)
    resp = client.post("/api/v1/audio/synthesize-stream", json={"text": "你好"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers["x-tts-engine"] == "edge-tts"
    # 流式完整下发
    assert resp.content == b"\xff\xf3data1data2"
