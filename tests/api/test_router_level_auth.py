# -*- coding: utf-8 -*-
"""P0-5（审计 2026-09-11）：router 级鉴权回归——零鉴权模块封口。

代表抽样：projects_api（写操作面）、webhooks（CRUD 面）、
knowledge_integration（get_current_user_or_service 机器兼容面）。
无凭证一律 401；override 注入身份后放行。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user, get_current_user_or_service
from neurova.api.endpoints import knowledge_integration, projects_api, webhooks

_ID = {"user_id": "tuser", "username": "tuser", "role": "user", "neuser_id": "tuser"}


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/t")
    return TestClient(app)


@pytest.mark.parametrize("router,path,method", [
    (projects_api.router, "/t", "get"),
    (projects_api.router, "/t", "post"),
    (webhooks.router, "/t", "get"),
])
def test_router_requires_auth_without_credentials(router, path, method):
    client = _client(router)
    resp = client.request(method, path, json={} if method == "post" else None)
    assert resp.status_code == 401, resp.text[:200]


def test_router_accepts_overridden_identity():
    client = _client(projects_api.router)
    client.app.dependency_overrides[get_current_user] = lambda: _ID
    resp = client.get("/t")
    assert resp.status_code == 200


def test_knowledge_integration_service_token_face():
    """knowledge_integration 走 or_service：机器调用方（服务令牌）兼容。"""
    client = _client(knowledge_integration.router)
    client.app.dependency_overrides[get_current_user_or_service] = lambda: {
        **_ID, "role": "admin", "auth_source": "service_token",
    }
    resp = client.get("/t/sync/links")
    assert resp.status_code == 200
    # 覆盖移除后回真实依赖 → 401
    client.app.dependency_overrides.pop(get_current_user_or_service, None)
    assert client.get("/t/sync/links").status_code == 401
