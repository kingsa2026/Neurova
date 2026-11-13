# -*- coding: utf-8 -*-
"""P2-9（审计 2026-11-04）：SeenCursorManager 接回生产端点。

原先 479 行管理器全仓零生产调用；现在 /coordination/seen-boundary/*
由它承担：check-freshness 只读、record 执行后记账、stats/reset 运维面。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.coordination_api import router
from neurova.collaboration.seen_cursor import SeenCursorManager, reset_seen_cursor_manager


@pytest.fixture(autouse=True)
def _cleanSeenCursor(tmp_path, monkeypatch):
    reset_seen_cursor_manager()
    manager = SeenCursorManager(data_dir=str(tmp_path / "seen"))
    monkeypatch.setattr(
        "neurova.collaboration.seen_cursor.get_seen_cursor_manager", lambda: manager
    )
    yield
    reset_seen_cursor_manager()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    # P1-6 收口后 coordination router 级需登录（reset 另收 admin）——测试身份走依赖覆盖。
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    return TestClient(app)


def test_checkThenRecordThenCheckDetectsDuplicate(client):
    ops = {"agent_id": "agent_seen", "operations": ["open:doc-1", "edit:doc-1:title"]}

    first = client.post("/coordination/seen-boundary/check-freshness", json=ops).json()
    assert first["fresh"] is True
    assert first["operation_count"] == 2

    recorded = client.post(
        "/coordination/seen-boundary/record",
        json={**ops, "session_id": "sess-1", "turn_id": "turn-1"},
    ).json()
    assert recorded["recorded"] is True
    assert recorded["cursor_id"].startswith("seen_")

    second = client.post("/coordination/seen-boundary/check-freshness", json=ops).json()
    assert second["fresh"] is False
    assert "already seen" in (second["reason"] or "").lower()


def test_statsAndResetAreWired(client):
    client.post("/coordination/seen-boundary/record", json={
        "agent_id": "agent_stats", "operations": ["op-a"],
    })
    stats = client.get("/coordination/seen-boundary/stats").json()["seen_boundary"]
    assert stats["agents"] == 1
    assert stats["seen_operations"] >= 1

    assert client.post("/coordination/seen-boundary/reset").json()["status"] == "reset"
    after = client.get("/coordination/seen-boundary/stats").json()["seen_boundary"]
    assert after["agents"] == 0
    fresh = client.post("/coordination/seen-boundary/check-freshness", json={
        "agent_id": "agent_stats", "operations": ["op-a"],
    }).json()
    assert fresh["fresh"] is True, "reset 后同一操作必须重新视为新鲜"
