# -*- coding: utf-8 -*-
"""P2-1（审计 2026-11-04）：/health/detailed 默认只信回环。

详细健康报告含路径级读数；与 /metrics 同一套三档策略
（NEUROVA_HEALTH_ACCESS=local|public|token，默认 local）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.app import AppState, _add_health_routes
from neurova.core.health_checker import HealthChecker


def _client(host: str) -> TestClient:
    app = FastAPI()
    state = AppState()
    state.health_checker = HealthChecker()
    _add_health_routes(app, state)
    return TestClient(app, client=(host, 50000))


def test_default_local_allows_loopback():
    assert _client("127.0.0.1").get("/health/detailed").status_code == 200


def test_default_local_rejects_remote():
    resp = _client("203.0.113.9").get("/health/detailed")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"


def test_public_mode_allows_remote(monkeypatch):
    monkeypatch.setenv("NEUROVA_HEALTH_ACCESS", "public")
    assert _client("203.0.113.9").get("/health/detailed").status_code == 200


def test_token_mode_requires_matching_token(monkeypatch):
    monkeypatch.setenv("NEUROVA_HEALTH_ACCESS", "token")
    monkeypatch.setenv("NEUROVA_HEALTH_TOKEN", "s3cret")
    client = _client("203.0.113.9")
    assert client.get("/health/detailed").status_code == 403
    assert client.get("/health/detailed", headers={"x-health-token": "wrong"}).status_code == 403
    assert client.get("/health/detailed", headers={"x-health-token": "s3cret"}).status_code == 200
    assert client.get(
        "/health/detailed", headers={"authorization": "Bearer s3cret"}
    ).status_code == 200


def test_token_mode_without_token_fails_closed(monkeypatch):
    monkeypatch.setenv("NEUROVA_HEALTH_ACCESS", "token")
    monkeypatch.delenv("NEUROVA_HEALTH_TOKEN", raising=False)
    assert _client("127.0.0.1").get("/health/detailed").status_code == 403
