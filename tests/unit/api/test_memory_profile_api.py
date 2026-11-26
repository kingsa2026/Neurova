# -*- coding: utf-8 -*-
"""Memory Profile GET/PUT 必须匹配 MemoryManager 的真实签名。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory import profile
from neurova.api.endpoints.memory.base import requireIdentityForMemoryFace


class _ProfileManager:
    def __init__(self):
        self.profile = {"preferences": {"theme": "dark"}}
        self.updates = []

    def get_user_profile(self):
        return dict(self.profile)

    def update_user_profile(self, **kwargs):
        self.updates.append(kwargs)
        self.profile.update(kwargs)
        return True


def _client(monkeypatch, manager):
    app = FastAPI()
    app.include_router(profile.router, prefix="/api/v1/memory")
    app.dependency_overrides[requireIdentityForMemoryFace] = lambda: None
    app.dependency_overrides[profile.get_current_user_or_default] = lambda: {
        "user_id": "u1",
        "neuser_id": "u1",
        "role": "user",
    }
    monkeypatch.setattr(profile, "get_memory_manager", lambda agent_id, user: manager)
    return TestClient(app)


def test_get_user_profile_uses_no_argument_manager_contract(monkeypatch):
    manager = _ProfileManager()
    client = _client(monkeypatch, manager)

    response = client.get("/api/v1/memory/users/u1/profile")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["preferences"] == {"theme": "dark"}


def test_put_user_profile_expands_keyword_updates(monkeypatch):
    manager = _ProfileManager()
    client = _client(monkeypatch, manager)

    response = client.put(
        "/api/v1/memory/users/u1/profile",
        json={"conversation_style": "concise", "knowledge_level": 4},
    )

    assert response.status_code == 200, response.text
    assert manager.updates == [{"conversation_style": "concise", "knowledge_level": 4}]
    assert manager.profile["conversation_style"] == "concise"
