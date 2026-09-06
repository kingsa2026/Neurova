"""聊天页对齐 QwenPaw — 后端契约测试（红绿灯 TDD）

锁定契约：
1. SSE 流在 done 事件之前发一次 usage 事件：prompt_tokens/completion_tokens/
   total_tokens/model/estimated（来源 usage_accounting.last_call()，
   入账已在 multi_model_client 下沉，此处不双计）；无记录时不发 usage 事件
   （不伪造数据）。
2. 会话拖拽排序落库：POST /console/chat/sessions/reorder 接收
   {agent_id, ordered_ids}，SessionRepository.set_sessions_sort_order 持久化，
   list_sessions 返回带 sort_order 字段且按其排序。
"""
from __future__ import annotations

import asyncio
import json
import typing

import pytest
from starlette.requests import Request

from neurova.api.endpoints import console as console_module


# ---------------------------------------------------------------------------
# 1. SSE usage 事件
# ---------------------------------------------------------------------------

def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": [(b"content-type", b"application/json")],
    }
    return Request(scope, receive=receive)


class FakeRepo:
    def create_session(self, agent_id="", user_id="", title="新对话", config=None):
        return "sess-1"


class RecordingAgent:
    def __init__(self, emit_events: bool = False):
        self.chat_kwargs: typing.Optional[dict] = None
        self.emit_events = emit_events

    async def chat(self, message, **kwargs):
        self.chat_kwargs = kwargs
        if self.emit_events:
            emitter = (kwargs.get("metadata") or {}).get("event_emitter")
            emitter("content", "你好")
        return {"text": "你好", "reasoning": "", "tool_messages": []}


def _patch(monkeypatch, agent) -> None:
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: FakeRepo())
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id: agent)


async def _call_and_drain(body) -> typing.Tuple[typing.Any, typing.List[dict]]:
    resp = await console_module.post_console_chat(body, _make_request())
    events: typing.List[dict] = []
    if isinstance(resp, StreamingResponse := __import__("starlette.responses", fromlist=["StreamingResponse"]).StreamingResponse):
        async for chunk in resp.body_iterator:
            for line in str(chunk).splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:"):].strip()))
    return resp, events


class TestSSEUsageEvent:
    def test_usage_event_emitted_before_done(self, monkeypatch):
        """有真实入账时，done 之前应发 usage 事件（QwenPaw turn_usage 对齐）。"""
        from neurova.core import usage_accounting

        usage_accounting.reset_usage_accounting()
        usage_accounting.get_usage_accounting().record(
            model="gpt-4o", provider="openai",
            prompt_tokens=120, completion_tokens=30,
        )
        try:
            agent = RecordingAgent(emit_events=True)
            _patch(monkeypatch, agent)
            body = console_module.ChatRequest(message="你好", session_id="s1", stream=True)
            _, events = asyncio.run(_call_and_drain(body))

            types = [e.get("type") for e in events]
            assert "usage" in types, f"SSE 缺少 usage 事件: {types}"
            usage_ev = next(e for e in events if e["type"] == "usage")
            assert usage_ev["prompt_tokens"] == 120
            assert usage_ev["completion_tokens"] == 30
            assert usage_ev["total_tokens"] == 150
            assert usage_ev["model"] == "gpt-4o"
            assert usage_ev["estimated"] is False
            assert types.index("usage") < types.index("done"), "usage 必须在 done 之前"
        finally:
            usage_accounting.reset_usage_accounting()

    def test_no_usage_event_without_record(self, monkeypatch):
        """无真实入账（last_call 为 None）时不发 usage 事件 — 不伪造数据。"""
        from neurova.core import usage_accounting

        usage_accounting.reset_usage_accounting()
        try:
            agent = RecordingAgent(emit_events=True)
            _patch(monkeypatch, agent)
            body = console_module.ChatRequest(message="你好", session_id="s1", stream=True)
            _, events = asyncio.run(_call_and_drain(body))

            assert all(e.get("type") != "usage" for e in events)
            assert events[-1].get("type") == "done"
        finally:
            usage_accounting.reset_usage_accounting()


# ---------------------------------------------------------------------------
# 2. 会话拖拽排序落库
# ---------------------------------------------------------------------------

class FakeRepoWithSort(FakeRepo):
    """带 sort_order 持久化语义的假 repo。"""

    def __init__(self):
        self._sessions: typing.Dict[str, dict] = {}
        for sid in ("a", "b", "c"):
            self._sessions[sid] = {
                "session_id": sid, "title": f"S-{sid}", "agent_id": "default",
                "created_at": "2026-09-06T00:00:00", "updated_at": "2026-09-06T00:00:00",
                "pinned": False, "sort_order": 0, "user_id": "u1",
            }

    def list_sessions(self, agent_id="", user_id=""):
        items = [s for s in self._sessions.values() if not agent_id or s["agent_id"] == agent_id]
        return sorted(items, key=lambda s: (s.get("sort_order", 0), s.get("updated_at", "")), reverse=False)

    def set_sessions_sort_order(self, agent_id, ordered_ids):
        for idx, sid in enumerate(ordered_ids):
            if sid in self._sessions:
                self._sessions[sid]["sort_order"] = idx + 1
        return True


class TestSessionReorderEndpoint:
    def test_reorder_persists_sort_order(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        repo = FakeRepoWithSort()
        monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
        monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")

        app = FastAPI()
        app.include_router(console_module.router, prefix="/api/v1/console")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/console/chat/sessions/reorder",
                json={"agent_id": "default", "ordered_ids": ["c", "a", "b"]},
            )
        assert resp.status_code == 200, resp.text
        # 落库后排序生效
        ordered = [s["session_id"] for s in repo.list_sessions(agent_id="default")]
        assert ordered == ["c", "a", "b"]

    def test_reorder_rejects_unknown_session(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        repo = FakeRepoWithSort()
        monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
        monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")

        app = FastAPI()
        app.include_router(console_module.router, prefix="/api/v1/console")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/console/chat/sessions/reorder",
                json={"agent_id": "default", "ordered_ids": ["a", "ghost"]},
            )
        assert resp.status_code == 404, "不存在的会话应 404（防越权/误传静默成功）"

    def test_list_sessions_includes_sort_order(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        repo = FakeRepoWithSort()
        monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
        monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")

        app = FastAPI()
        app.include_router(console_module.router, prefix="/api/v1/console")
        with TestClient(app) as client:
            resp = client.get("/api/v1/console/chat/sessions", params={"agent_id": "default"})
        assert resp.status_code == 200
        sessions = resp.json()["data"]["sessions"]
        assert sessions, "应有会话列表"
        for s in sessions:
            assert "sort_order" in s, "会话摘要应携带 sort_order 字段"
