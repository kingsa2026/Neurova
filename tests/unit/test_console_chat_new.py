"""红绿灯 TDD：console /chat/new 端点读取 body 中的 agent_id/title (S1 后端根因)。

全链路：前端 createSession(agentId) 传 agent_id -> 后端 /chat/new 读 body
-> repo.create_session(agent_id=...) -> 会话携带 agent_id -> 记忆/历史隔离正确。
修复前端点硬编码 agent_id=""，导致多 agent 会话全落入 default agent。
"""
from __future__ import annotations

import asyncio
import json
from starlette.requests import Request

from neurova.api.endpoints import console as console_module


def _make_json_request(payload) -> Request:
    body = json.dumps(payload).encode() if payload is not None else b""
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat/new",
        "headers": [(b"content-type", b"application/json")],
    }
    return Request(scope, receive=receive)


class FakeRepo:
    def __init__(self) -> None:
        self.captured: dict = {}

    def create_session(self, agent_id="", user_id="", title="新对话", config=None):
        self.captured.update(
            {"agent_id": agent_id, "user_id": user_id, "title": title}
        )
        return "sess-1"


def test_post_console_chat_new_reads_agent_id_and_title(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    resp = asyncio.run(
        console_module.post_console_chat_new(
            _make_json_request({"agent_id": "agent_x", "title": "My Chat"})
        )
    )
    assert resp["data"]["session_id"] == "sess-1"
    assert repo.captured["agent_id"] == "agent_x"
    assert repo.captured["title"] == "My Chat"
    assert repo.captured["user_id"] == "u1"


def test_post_console_chat_new_defaults_when_body_missing(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    resp = asyncio.run(
        console_module.post_console_chat_new(_make_json_request(None))
    )
    assert resp["data"]["session_id"] == "sess-1"
    assert repo.captured["agent_id"] == ""
    assert repo.captured["title"] == "新对话"
