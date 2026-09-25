"""协作房间端点集成测试：GET 房间/历史 + POST 消息触发轮次（依赖以 monkeypatch 注入）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import collaboration_room_api as room_api


@pytest.fixture
def client(monkeypatch):
    # 假协作管理器：project 有 members(dict) 与 owner_id
    project = SimpleNamespace(
        project_id="project_x", owner_id="u1", name="房间", description="d",
        members={"a1": object(), "a2": object()}, metadata={},
    )
    fake_manager = SimpleNamespace(get_project=lambda pid: project if pid == "project_x" else None)
    monkeypatch.setattr(room_api, "get_collaboration_manager", lambda: fake_manager, raising=False)

    # 假 store：history 返回固定行
    fake_store = SimpleNamespace(history=lambda room_id, limit=200: [
        {"sender_type": "user", "sender_id": "u1", "role": "user", "content": "hi", "ts": 1, "meta": {}},
    ])
    monkeypatch.setattr(room_api, "get_room_store", lambda: fake_store)

    # 假 router：记录 handle_user_message 调用
    calls = {}

    class _FakeRouter:
        async def handle_user_message(self, room_id, text, actor_user, members, responder_agent_id=""):
            calls.update(room_id=room_id, text=text, actor=actor_user, members=members)
    monkeypatch.setattr(room_api, "get_room_turn_router", lambda: _FakeRouter())

    app = FastAPI()
    app.include_router(room_api.router, prefix="/v1/collaboration")
    app.dependency_overrides[auth_mod.get_current_user] = lambda: {"user_id": "u1", "role": "admin"}
    return TestClient(app), calls


def test_get_room_returns_members_and_owner(client):
    c, _ = client
    r = c.get("/v1/collaboration/rooms/project_x")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] == "project_x"
    assert set(m["id"] for m in data["members"]) == {"a1", "a2"}
    assert data["owner"] == "u1"


def test_get_messages_returns_history(client):
    c, _ = client
    r = c.get("/v1/collaboration/rooms/project_x/messages")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert rows[0]["content"] == "hi" and rows[0]["sender_id"] == "u1"


def test_post_message_triggers_turn_router(client):
    c, calls = client
    r = c.post("/v1/collaboration/rooms/project_x/messages", json={"text": "@a1 hello"})
    assert r.status_code == 200
    assert calls["room_id"] == "project_x"
    assert calls["text"] == "@a1 hello"
    assert calls["actor"] == "u1"
    assert set(m["id"] for m in calls["members"]) == {"a1", "a2"}


def test_post_message_unknown_room_404(client):
    c, _ = client
    r = c.post("/v1/collaboration/rooms/nope/messages", json={"text": "x"})
    assert r.status_code == 404


def test_member_dicts_filters_empty_id():
    # 根因防回归：/start 未传 owner 会写入空键成员；_member_dicts 应过滤掉。
    from neurova.api.endpoints.collaboration_room_api import _member_dicts

    project = SimpleNamespace(members={"": object(), "a1": object()})
    assert _member_dicts(project) == [{"id": "a1", "name": "a1"}]


def test_agent_display_name_resolves_and_fallsback(monkeypatch):
    from neurova.api.endpoints import collaboration_room_api as ra

    class _Cfg:
        name = "Neurova"

    class _Ag:
        config = _Cfg()

    monkeypatch.setattr(ra, "get_agent_instance", lambda agent_id: _Ag())
    assert ra._agent_display_name("default") == "Neurova"

    monkeypatch.setattr(ra, "get_agent_instance", lambda agent_id: None)
    assert ra._agent_display_name("kai") == "kai"  # 未加载→回落 id


def test_member_dicts_uses_display_name(monkeypatch):
    from neurova.api.endpoints import collaboration_room_api as ra

    monkeypatch.setattr(ra, "_agent_display_name", lambda mid: "Neurova" if mid == "default" else mid)
    project = SimpleNamespace(members={"default": object(), "": object()})
    assert ra._member_dicts(project) == [{"id": "default", "name": "Neurova"}]
