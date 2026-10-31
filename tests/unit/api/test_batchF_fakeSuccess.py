# -*- coding: utf-8 -*-
"""批 F 假成功三兄弟（specs/2026-10-31-full-repo-defect-sweep-fixplan.md 批 F）。

F1 非流式 /console/chat 恒回空 reply；F2 WS 异常吞成 Echo 假成功；
F3 memory/eki 三腿参数键名与真身错位。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import deps as deps_mod
from neurova.api.endpoints import console as console_mod

USER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}


class _OkAgent:
    async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
        return {"text": f"ns-reply:{message}", "reasoning": None, "tool_messages": []}


class _BoomAgent:
    async def chat(self, *a, **k):
        raise RuntimeError("llm down")


@pytest.fixture()
def ns_client(monkeypatch):
    """非流式用例：真 create_app + agent 桩（stream=False 直调 agent.chat）。"""
    app = console_mod.build_test_app() if hasattr(console_mod, "build_test_app") else None
    from neurova.api.app import create_app

    app = create_app(enable_memory=False, enable_channels=False)
    app.dependency_overrides[deps_mod.get_current_user] = lambda: dict(USER)
    monkeypatch.setattr(console_mod, "get_agent_instance", lambda agent_id=None: _OkAgent())
    return TestClient(app)


def test_f1_nonstream_chat_returns_agent_reply(ns_client):
    resp = ns_client.post(
        "/api/v1/console/chat",
        json={"message": "你好", "session_id": "ns-1", "stream": False},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["reply"] == "ns-reply:你好", (
        f"非流式必须真调 agent（修前恒空 reply 假成功），实得 {data['reply']!r}"
    )
    assert data.get("response") == data["reply"], "前端消费键 response 必须随批提供"


# ── F2：WS 异常必须 error 帧，不得 Echo 假成功 ────────────────────────────


def test_f2_ws_chat_error_sends_error_frame(monkeypatch):
    app = FastAPI()
    app.include_router(console_mod.router)
    monkeypatch.setattr(console_mod, "get_agent_instance", lambda: _BoomAgent())
    # WS 握手要求 ?token=<JWT>（2026-09-07 根因修复）——按 auth_headers 教义签真令牌
    from tests.auth_headers import bearerHeaders

    token = bearerHeaders("u1")["Authorization"].removeprefix("Bearer ")
    client = TestClient(app)
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect(f"/ws/ledger-ws?token={token}") as ws:
        ws.send_json({"type": "chat", "message": "hi", "session_id": "ws-1"})
        frame = ws.receive_json()
        assert frame.get("type") == "error", (
            f"agent 故障必须以 error 帧出去，实得 {frame}（修前吞成 Echo 假成功）"
        )
        assert "llm down" in frame.get("message", ""), "error 帧必须点名故障原因"
        # error 帧后服务端继续等下一条消息——此处不再多读（服务端与客户端
        # 会互相等），退出上下文即触发正常关闭序列


# ── F3：eki 三腿参数键名对齐真身 ──────────────────────────────────────────


@pytest.fixture()
def eki_env(monkeypatch):
    from neurova.api.endpoints import memory as memory_pkg

    captured = {}

    class _Mgr:
        def eki_process_task(self, **kwargs):
            captured["process"] = kwargs
            return {"importance": 0.5, "decay": 0.1}

        def eki_batch_update(self, **kwargs):
            captured["batch"] = kwargs
            return {"m1": 0.4}

        def eki_predict_decay(self, **kwargs):
            captured["decay"] = kwargs
            return 0.77

    monkeypatch.setattr(
        "neurova.api.endpoints.memory.eki.get_memory_manager",
        lambda agent_id, user: _Mgr(),
    )
    # F3 夹具走真 create_app：memory 路由由真装配挂载（本仓 .venv 的 fastapi
    # include 走懒加载 _IncludedRouter，裸 FastAPI+include 的 dependency_
    # overrides 与路由物化都与生产不同形）——身份按 auth_headers 教义挂真 JWT
    from neurova.api.app import create_app
    from tests.auth_headers import bearerHeaders

    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app, headers=bearerHeaders("u1")), captured


def test_f3_eki_process_maps_real_keys(eki_env):
    client, captured = eki_env
    resp = client.post("/api/v1/memory/eki/process", json={
        "task_embedding": [0.1, 0.2],
        "memory_context": ["mem-9"],
        "user_feedback": 0.8,
    })
    assert resp.status_code == 200, resp.text
    kwargs = captured["process"]
    assert kwargs.get("memory_id") == "mem-9", (
        f"observation 语义的记忆来源必须映射到 memory_id，实得 {kwargs}"
    )
    assert kwargs.get("observation") == 0.8, (
        f"user_feedback 语义映射到 observation，实得 {kwargs}"
    )
    assert kwargs.get("task_id"), "task_id 缺省时必须由服务端生成（真身第一键不可为空）"


def test_f3_eki_decay_maps_horizon_days_to_hours(eki_env):
    client, captured = eki_env
    resp = client.get("/api/v1/memory/eki/decay/mem-1", params={"horizon": 7})
    assert resp.status_code == 200, resp.text
    kwargs = captured["decay"]
    assert kwargs.get("hours_ahead") == 7 * 24, (
        f"horizon（天）必须换算成 hours_ahead（小时），实得 {kwargs}"
    )


def test_f3_eki_batch_update_passes_updates(eki_env):
    client, captured = eki_env
    resp = client.post("/api/v1/memory/eki/batch-update", json={
        "batch_data": [{"memory_id": "m1", "observations": [0.5]}],
    })
    assert resp.status_code == 200, resp.text
    kwargs = captured["batch"]
    assert kwargs.get("updates") == [
        {"memory_id": "m1", "observations": [0.5]}
    ], f"batch_data 必须以真身的 updates 键传入，实得 {kwargs}"
