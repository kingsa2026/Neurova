# -*- coding: utf-8 -*-
"""2026-09-08 审计修复：TTS 链批。

- ⑧ 流式端点直传 voice/speed → sapi5/mock（无 **kwargs）TypeError 500，
  绕过 fallback/502 语义
- ⑨ ASR 降级分支直访 VoiceEngine.is_initialized → AttributeError 500
  （TTS 侧同根因已鸭子解包，ASR 侧漏修）
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from neurova.api.endpoints import audio as audio_mod

    app = FastAPI()
    app.include_router(audio_mod.router, prefix="/audio")
    return audio_mod, TestClient(app)


class TestStreamEndpointNoKwargsEngines:
    """无 **kwargs 引擎（sapi5/mock）被降级选中时端点不得 500。"""

    def test_stream_to_engine_without_kwargs_falls_back_not_500(self, monkeypatch):
        audio_mod, client = _make_app()

        calls: list[tuple] = []

        class RigidEngine:
            """模拟 sapi5/mock：synthesize_stream(self, text) 无 **kwargs。"""

            audio_media_type = "audio/wav"

            @staticmethod
            def get_engine_name():
                return "rigid"

            @staticmethod
            async def synthesize_stream(text):
                calls.append(("rigid", text))
                yield b"rigid-bytes"

        class LooseEngine:
            """模拟 moss/edge：接受 kwargs。"""

            audio_media_type = "audio/wav"

            @staticmethod
            def get_engine_name():
                return "loose"

            @staticmethod
            async def synthesize_stream(text, **kwargs):
                calls.append(("loose", text))
                yield b"loose-bytes"

        class FakeManager:
            def __init__(self):
                self.is_initialized = True
                self._engines = {"rigid": RigidEngine(), "loose": LooseEngine()}
                self._engine = self._engines["rigid"]
                self._engine_name = "rigid"

            async def _initialize_engine(self, name):
                self._engine = self._engines[name]
                self._engine_name = name
                return True

            async def synthesize_stream(self, text, **kwargs):
                current = self._engine
                try:
                    async for chunk in current.synthesize_stream(text, **kwargs):
                        yield chunk
                    return
                except TypeError:
                    pass
                for name, eng in self._engines.items():
                    if eng is current:
                        continue
                    await self._initialize_engine(name)
                    try:
                        async for chunk in eng.synthesize_stream(text, **kwargs):
                            yield chunk
                        return
                    except TypeError:
                        continue

        fake = FakeManager()
        monkeypatch.setattr(audio_mod, "_get_tts_manager", lambda: fake)
        resp = client.post(
            "/audio/synthesize-stream", json={"text": "你好", "voice": "x", "speed": 1.2}
        )
        assert resp.status_code == 200, f"无 kwargs 引擎在链首时端点 500（绕过 fallback）: {resp.text[:200]}"
        assert b"loose-bytes" in resp.content


class TestAsrFallbackDuckUnwrap:
    """VoiceEngine 不可用时降级分支经鸭子解包，不 AttributeError。"""

    def test_voiceengine_without_is_initialized_reaches_503(self, monkeypatch):
        audio_mod, client = _make_app()

        class FakeVoiceEngine:
            """模拟 VoiceEngine 统一层：无 is_initialized 属性。"""

            @staticmethod
            def is_available():
                return False

            _engine = None

        monkeypatch.setattr(audio_mod, "_get_asr_manager", lambda: FakeVoiceEngine())
        resp = client.post(
            "/audio/transcribe",
            files={"audio_file": ("a.wav", b"fake", "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 503, (
            f"ASR 降级分支对 VoiceEngine 直访 is_initialized → {resp.status_code}（应 503）"
        )

    def test_real_asr_manager_unwrapped_and_used(self, monkeypatch):
        """有真实底层 manager 时经 _get_asr_manager 鸭子解包后正常转写。"""
        audio_mod, client = _make_app()

        calls = {}

        class RealAsrManager:
            is_initialized = True

            async def transcribe(self, audio_bytes, language="zh"):
                calls["lang"] = language
                return {"text": "识别结果", "confidence": 0.9}

        class Wrapper:
            """模拟 VoiceEngine 统一层：is_available=False（引擎未就绪），
            降级分支应解包 _engine 使用真实 manager。"""

            _engine = RealAsrManager()

            @staticmethod
            def is_available():
                return False

        monkeypatch.setattr(audio_mod, "_get_voice_engine", lambda t: Wrapper())
        resp = client.post(
            "/audio/transcribe",
            files={"audio_file": ("a.wav", b"fake", "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["text"] == "识别结果"
        assert calls.get("lang") == "zh"
