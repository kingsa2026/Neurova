"""N8 跨域 harness 检索端点。"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api

MOCK_USER = {"user_id": "test_user", "username": "testuser", "role": "admin"}


@pytest.fixture()
def client(monkeypatch):
    class _Service:
        def searchDomainHarnesses(self, query, *, domain="", limit=5):
            return [
                {
                    "skill_id": "peer",
                    "version": "1.2.0",
                    "domain": domain or "legal",
                    "adopted": True,
                    "context_template": "PEER",
                    "score": 1.0 if query else None,
                }
            ][:limit]

    monkeypatch.setattr(skill_pool_api, "_pool_service", lambda agent_id: _Service())
    from neurova.api.deps import get_current_user

    app = FastAPI()
    app.include_router(skill_pool_api.router, prefix="/v1/skill-pool")
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_domain_harness_search(client):
    resp = client.get(
        "/v1/skill-pool/agent/agent/domain-harnesses",
        params={"query": "合同", "domain": "legal", "limit": 3},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["skill_id"] == "peer"
    assert data[0]["adopted"] is True
