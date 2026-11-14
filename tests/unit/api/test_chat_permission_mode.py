# -*- coding: utf-8 -*-
"""P1-4：聊天请求级权限模式——校验（非法 422）与元数据透传（会话级切换入口）。
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from neurova.api.auth import get_current_user
from neurova.api.endpoints.chat import router


@pytest.fixture
def client():
    captured = {}

    async def _chat(**kwargs):
        captured.update(kwargs)
        return {"text": "ok"}

    agent = MagicMock()
    agent.chat = _chat
    app = FastAPI()
    app.include_router(router, prefix="/chat")

    async def _mock_get_current_user(request: Request):
        return {"user_id": "test-user", "role": "admin"}

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    with patch("neurova.api.endpoints._app_state", {"agents": {"default": agent}}):
        client = TestClient(app)
        yield client, captured


def test_invalid_permission_mode_422(client):
    client, _captured = client
    resp = client.post(
        "/chat", json={"message": "hi", "agent_id": "default", "permission_mode": "nuclear"}
    )
    assert resp.status_code == 422
    assert "permission_mode" in resp.json()["detail"]


def test_valid_mode_flows_into_metadata(client):
    client, captured = client
    resp = client.post(
        "/chat",
        json={"message": "hi", "agent_id": "default", "permission_mode": "plan"},
    )
    assert resp.status_code == 200
    assert captured["metadata"]["permission_mode"] == "plan"


def test_missing_mode_leaves_metadata_untouched(client):
    client, captured = client
    client.post("/chat", json={"message": "hi", "agent_id": "default"})
    assert "permission_mode" not in captured["metadata"]


def test_stream_invalid_permission_mode_422(client):
    client, _captured = client
    resp = client.post(
        "/chat/stream",
        json={"message": "hi", "agent_id": "default", "permission_mode": "nuclear"},
    )
    assert resp.status_code == 422
