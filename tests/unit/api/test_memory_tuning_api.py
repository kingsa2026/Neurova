# -*- coding: utf-8 -*-
"""D7 自动调参端点判据：管理员门 / 运行回写 / 最近报告。"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault(
    "NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_d7_tuning_0123456789"
)

from neurova.api.endpoints import memory_settings_api
from neurova.cognitive_layers.memory_layer.settings_config import (
    MemorySettingsConfig,
    get_memory_settings,
)

BASE = "/api/v1/memory-settings/settings"

MOCK_USER = {"user_id": "u1", "username": "user", "role": "user"}
MOCK_ADMIN = {"user_id": "admin1", "username": "admin", "role": "admin"}


@pytest.fixture
def client(tmp_path):
    MemorySettingsConfig.reset_instance()
    get_memory_settings(str(tmp_path))
    app = FastAPI()
    app.include_router(memory_settings_api.router, prefix="/api/v1/memory-settings")
    with TestClient(app) as c:
        yield c
    MemorySettingsConfig.reset_instance()


def _override(client, user):
    from neurova.api.deps import get_current_user
    from tests.auth_headers import overrideIdentity

    overrideIdentity(client.app, lambda: user)
    yield client
    client.app.dependency_overrides.clear()


@pytest.fixture
def user_client(client):
    yield from _override(client, MOCK_USER)


@pytest.fixture
def admin_client(client):
    yield from _override(client, MOCK_ADMIN)


def test_tuning_requires_admin(user_client):
    resp = user_client.post(f"{BASE}/tuning/auto", json={"apply": False})
    assert resp.status_code == 403
    resp = user_client.get(f"{BASE}/tuning/last")
    assert resp.status_code == 403


def test_tuning_requires_auth(client):
    resp = client.post(f"{BASE}/tuning/auto", json={"apply": False})
    assert resp.status_code == 401


def test_admin_run_applies_best_and_reports(admin_client):
    resp = admin_client.post(
        f"{BASE}/tuning/auto", json={"floors": [0.4, 0.9], "apply": True}
    )
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["applied"] is True
    assert [c["floor"] for c in report["candidates"]] == [0.4, 0.9]
    assert report["best"]["floor"] in (0.4, 0.9)

    # 最优档已写进记忆设置
    settings = admin_client.get(f"{BASE}").json()["data"]
    assert (
        settings["recall.temp_channel_relevance_floor"]
        == report["best"]["floor"]
    )

    # 最近报告可查
    last = admin_client.get(f"{BASE}/tuning/last").json()["data"]
    assert last["best"]["floor"] == report["best"]["floor"]


def test_admin_run_apply_false_keeps_settings(admin_client):
    resp = admin_client.post(
        f"{BASE}/tuning/auto", json={"floors": [0.4, 0.9], "apply": False}
    )
    assert resp.status_code == 200
    settings = admin_client.get(f"{BASE}").json()["data"]
    assert settings["recall.temp_channel_relevance_floor"] == 0.6
