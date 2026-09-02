# -*- coding: utf-8 -*-
"""RemoteWhisper 远程转写引擎测试（Whisper 改远程调用）。

锁定：无 key 诚实 False / 401 探测降级 / multipart 调用契约 /
失败不产假文本 / 三级 fallback 链顺序。
"""
import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def engine():
    from neurova.asr.remote_whisper_engine import RemoteWhisperEngine

    eng = RemoteWhisperEngine.__new__(RemoteWhisperEngine)
    eng._initialized = False
    import logging as _logging

    eng._logger = _logging.getLogger("test.remote_whisper")
    eng._base_url = "https://api.example.com/v1"
    eng._api_key = "sk-test"
    eng._model = "whisper-1"
    eng._timeout = 5.0
    eng._total_requests = 0
    eng._total_inference_ms = 0.0
    return eng


def test_no_key_returns_false(monkeypatch):
    from neurova.asr.remote_whisper_engine import RemoteWhisperEngine

    monkeypatch.delenv("NEUROVA_ASR_REMOTE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    eng = RemoteWhisperEngine()
    ok = asyncio.run(eng.initialize())
    assert ok is False
    assert eng._initialized is False


def test_probe_401_degrades_honestly(engine, monkeypatch):
    import requests as requests_mod

    resp = MagicMock()
    resp.status_code = 401
    monkeypatch.setattr(requests_mod, "get", lambda *a, **k: resp)
    ok = asyncio.run(engine.initialize())
    assert ok is False


def test_probe_200_initializes(engine, monkeypatch):
    import requests as requests_mod

    resp = MagicMock()
    resp.status_code = 200
    monkeypatch.setattr(requests_mod, "get", lambda *a, **k: resp)
    ok = asyncio.run(engine.initialize())
    assert ok is True


def test_transcribe_multipart_contract(engine, monkeypatch):
    import requests as requests_mod

    captured = {}

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"text": "hello world"}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured.update({"url": url, "headers": headers, "files": files, "data": data})
        return resp

    monkeypatch.setattr(requests_mod, "post", fake_post)
    engine._initialized = True

    result = asyncio.run(engine.transcribe(b"AUDIOBYTES", language="en"))
    assert result["text"] == "hello world"
    assert result["inference_ms"] >= 0
    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["files"]["file"][1] == b"AUDIOBYTES"
    assert captured["data"]["model"] == "whisper-1"
    assert captured["data"]["language"] == "en"


def test_transcribe_api_error_no_fake_text(engine, monkeypatch):
    import requests as requests_mod

    resp = MagicMock()
    resp.status_code = 503
    resp.text = "service unavailable"
    monkeypatch.setattr(requests_mod, "post", lambda *a, **k: resp)
    engine._initialized = True

    result = asyncio.run(engine.transcribe(b"X", language="zh"))
    assert result["text"] == ""
    assert "503" in result["error"]


def test_fallback_chain_three_tier():
    from neurova.asr.manager import FALLBACK_CHAIN

    assert FALLBACK_CHAIN == ["funasr", "remote_whisper", "whisper"]
