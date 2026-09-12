# -*- coding: utf-8 -*-
"""F-4 根修防回归（台账 2026-09-11）：chat SSE/REST 的 TTS audio_url 必须是
可经鉴权 HTTP 取回的 URL，而非服务器本地文件路径。

预存缺陷：post_chat_pipeline 把 TTS 产物直写 attachment_dir 后，chat.py 把
本地文件路径原样塞进 SSE audio 事件 url / done payload audio_url / 非流式
响应 data.audio.url——任何 HTTP 消费方拿到本地路径都无法使用。

根修（API 边界转换，内部 audio_path 契约保持本地路径不动——
artifacts_api 按 "audio_path" 正则注册本地产物依赖它）：
- GET /api/v1/chat/tts-audio/{agent_id}/{filename} 鉴权内容端点
  （登录态 + agent 访问权 + 文件名白名单防穿越，只服务 TTS 产物）；
- 三个发射点统一经 _tts_audio_http_url 转换。

隔离纪律：产物目录/假引擎全在 tmp_path，无真实 TTS 推理（假 agent 直接
返回静音 wav 字节路径，模拟管线产物）。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from neurova.api.auth import get_current_user
from neurova.api.endpoints import chat as chat_mod


WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfake-silence"


class FakeAgent:
    """假 Agent：chat() 返回预置结果（模拟管线 TTS 产物路径）。"""

    def __init__(self, attachment_dir: str, owner_user_id: str | None = "u1", result: dict | None = None):
        self.config = SimpleNamespace(attachment_dir=attachment_dir, owner_user_id=owner_user_id)
        self.result = result if result is not None else {"text": "你好"}

    async def chat(self, **kwargs):
        return dict(self.result)


def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat/stream",
        "headers": [(b"content-type", b"application/json")],
    }
    return Request(scope, receive=receive)


def _write_tts_product(tmp_path: Path) -> Path:
    attachment_dir = tmp_path / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    wav = attachment_dir / f"tts_s1_{int(time.time())}.wav"
    wav.write_bytes(WAV_BYTES)
    return wav


def _parse_sse(chunks) -> list[dict]:
    events: list[dict] = []
    name = None
    for chunk in chunks:
        for line in str(chunk).splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name:
                events.append({"event": name, "data": json.loads(line[len("data:"):].strip())})
    return events


async def _drain_stream(body):
    from starlette.responses import StreamingResponse

    resp = await chat_mod.chat_stream(_make_request(), body, {"user_id": "u1", "role": "admin"})
    assert isinstance(resp, StreamingResponse), f"流式端点提前返回错误响应: {resp}"
    events = []
    async for chunk in resp.body_iterator:
        events.extend(_parse_sse([chunk]))
    return events


# ═══════════════════════════════════════════════════════════════
# 1. SSE audio 事件 / done payload：audio_url 必须是 /api/ HTTP URL
# ═══════════════════════════════════════════════════════════════


def test_stream_audio_event_url_is_http_url(tmp_path, monkeypatch):
    """有 TTS 产物时：audio 事件 url 与 done.audio_url 必须以 /api/ 开头
    （鉴权内容端点 URL），绝不允许本地文件路径外泄。"""
    wav = _write_tts_product(tmp_path)
    agent = FakeAgent(
        attachment_dir=str(wav.parent),
        result={"text": "你好", "audio_path": str(wav), "audio_data": WAV_BYTES},
    )
    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id: agent)

    body = chat_mod.ChatStreamRequest(message="hi", agent_id="a1", session_id="s1")
    events = asyncio.run(_drain_stream(body))

    audio = [e for e in events if e["event"] == "audio"]
    assert audio, "有 TTS 产物却未发 audio 事件"
    url = audio[-1]["data"]["url"]
    assert url.startswith("/api/"), f"audio 事件 url 不是 HTTP URL: {url!r}"
    assert "tts-audio/a1/" in url and url.endswith(wav.name), f"URL 指向错误: {url!r}"
    assert ":" not in url, f"URL 含盘符，疑似本地路径外泄: {url!r}"

    done = [e for e in events if e["event"] == "done"]
    assert done and done[-1]["data"].get("audio_url") == url, "done payload audio_url 与 audio 事件不一致"


def test_stream_no_tts_product_emits_no_audio_event(tmp_path, monkeypatch):
    """无产物不发事件（现状锁存）：done 也不得携带 audio_url。"""
    agent = FakeAgent(attachment_dir=str(tmp_path / "attachments"))
    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id: agent)

    body = chat_mod.ChatStreamRequest(message="hi", agent_id="a1", session_id="s1")
    events = asyncio.run(_drain_stream(body))

    assert not [e for e in events if e["event"] == "audio"], "无产物却发了 audio 事件"
    done = [e for e in events if e["event"] == "done"]
    assert done and "audio_url" not in done[-1]["data"], "无产物 done 却带 audio_url"


# ═══════════════════════════════════════════════════════════════
# 2. 鉴权内容端点：匿名 401 / 越权 403 / 穿越拒绝 / 同字节取回
# ═══════════════════════════════════════════════════════════════


@pytest.fixture()
def tts_client(tmp_path, monkeypatch):
    wav = _write_tts_product(tmp_path)
    agent = FakeAgent(attachment_dir=str(wav.parent))
    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id: agent)

    app = FastAPI()
    app.include_router(chat_mod.router, prefix="/api/v1/chat")
    return TestClient(app), wav


def test_tts_audio_endpoint_rejects_anonymous(tts_client):
    client, _wav = tts_client
    resp = client.get("/api/v1/chat/tts-audio/a1/tts_s1_1.wav")
    assert resp.status_code == 401, "匿名访问鉴权内容端点未被拒绝"


def test_tts_audio_endpoint_roundtrip_same_bytes(tts_client):
    client, wav = tts_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "admin"}
    try:
        resp = client.get(f"/api/v1/chat/tts-audio/a1/{wav.name}")
        assert resp.status_code == 200
        assert resp.content == WAV_BYTES, "端点取回字节与产物不一致"
        assert resp.headers["content-type"].startswith("audio/wav")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_tts_audio_endpoint_rejects_non_owner(tts_client):
    client, wav = tts_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "intruder", "role": "user"}
    try:
        resp = client.get(f"/api/v1/chat/tts-audio/a1/{wav.name}")
        assert resp.status_code == 403, "非 owner 非 admin 可读取他人 TTS 产物"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_tts_audio_endpoint_rejects_traversal_and_non_tts(tts_client):
    client, _wav = tts_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "admin"}
    try:
        for evil in ["..%2F..%2Fsecret.wav", "tts_x%5C..%5C..%5Cwin.wav", "memory.db", "tts_a.wav.txt"]:
            resp = client.get(f"/api/v1/chat/tts-audio/a1/{evil}")
            assert resp.status_code in (400, 404), f"穿越/非 TTS 文件未被拒: {evil} → {resp.status_code}"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ═══════════════════════════════════════════════════════════════
# 3. 非流式响应 data.audio.url：同一根因命中点
# ═══════════════════════════════════════════════════════════════


def test_nonstream_audio_url_is_http_url(tmp_path, monkeypatch):
    wav = _write_tts_product(tmp_path)
    agent = FakeAgent(attachment_dir=str(wav.parent), result={"text": "你好", "audio_path": str(wav)})
    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id: agent)

    body = chat_mod.ChatRequest(message="hi", agent_id="a1", session_id="s1")

    async def call():
        return await chat_mod.chat(_make_request(), body, {"user_id": "u1", "role": "admin"})

    resp = asyncio.run(call())
    url = resp["data"]["audio"]["url"]
    assert url is not None and url.startswith("/api/"), f"非流式 audio.url 不是 HTTP URL: {url!r}"
    assert "tts-audio/a1/" in url and url.endswith(wav.name)
