# -*- coding: utf-8 -*-
"""流式 TTS content-type 修复测试（补课 4.3）。

原 bug：/synthesize-stream 恒声明 audio/wav，但 edge-tts 引擎产 MP3
裸字节——前端按 wav 解码必然失败。锁定按引擎动态 media_type 语义。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(engine_media_type: str):
    from neurova.api.endpoints import audio as audio_mod

    tts = MagicMock()
    tts.is_initialized = True
    tts.get_engine_name.return_value = "edge-tts" if engine_media_type == "audio/mpeg" else "moss-nano"
    # 补课 4.3 修复后：端点读引擎属性 audio_media_type（非方法）
    tts.audio_media_type = engine_media_type

    async def fake_stream(text):
        yield b"chunk1"
        yield b"chunk2"

    tts.synthesize_stream = fake_stream
    monkey_patch = audio_mod._get_tts_manager
    audio_mod._get_tts_manager = lambda: tts

    from neurova.api.auth import get_current_user_or_default

    app = FastAPI()
    app.include_router(audio_mod.router, prefix="/audio")
    client = TestClient(app)

    return client, audio_mod, monkey_patch


@pytest.mark.parametrize("media_type", ["audio/mpeg", "audio/wav"])
def test_stream_media_type_follows_engine(media_type):
    client, audio_mod, orig = _make_client(media_type)
    try:
        resp = client.post("/audio/synthesize-stream", json={"text": "你好"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(media_type)
        assert b"chunk1chunk2" in resp.content
    finally:
        audio_mod._get_tts_manager = orig


def test_edge_tts_declares_mpeg():
    from neurova.tts.edge_tts import EdgeTTS

    assert EdgeTTS.audio_media_type == "audio/mpeg"


def test_base_default_is_wav():
    from neurova.tts.base import TTSBase

    assert TTSBase.audio_media_type == "audio/wav"

def test_voice_engine_wrapper_does_not_500():
    """根因回归：_get_tts_manager 返回 VoiceEngine 统一层时，
    流式端点必须解包底层引擎（原实现直接当 TTSManager 用 → AttributeError 500）。"""
    from types import SimpleNamespace

    class FakeVoiceEngine:  # 名字匹配 type().__name__ == "VoiceEngine" 分支
        pass

    inner = SimpleNamespace(is_initialized=True, audio_media_type="audio/mpeg")

    async def fake_stream(text):
        yield b"x"

    inner.synthesize_stream = fake_stream

    from neurova.api.endpoints import audio as audio_mod

    wrapper = FakeVoiceEngine()
    wrapper._engine = inner
    wrapper.is_available = lambda: True  # 真 VoiceEngine 表面（生产鸭子判定依赖）
    wrapper.get_engine_name = lambda: "edge-tts"

    audio_mod._get_tts_manager = lambda: wrapper

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from neurova.api.auth import get_current_user_or_default

    app = FastAPI()
    app.include_router(audio_mod.router, prefix="/audio")
    client = TestClient(app)
    resp = client.post("/audio/synthesize-stream", json={"text": "你好"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("audio/mpeg")
