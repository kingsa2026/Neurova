# -*- coding: utf-8 -*-
"""P2-13：记忆有效期窗口写入面——`AddMemoryRequest` 补 `valid_from/valid_until`，
crud 透传 `manager.remember`（C6 检索侧 `isVisibleAt` 过滤早已接线，写入面此前
零生产调用方，生产普通记忆行窗口恒 NULL、过滤恒真）。

判据：
1. 带 valid_until 的记忆创建后 `manager._memories[mid].valid_until` 非空；
2. 不带窗口的行两界仍为 None（旧行为不变）；
3. 非法 ISO 串在请求边界 422——不吞成"永远有效"（与
   `manager._coerce_validity_moment` 的显式报错同口径）。
"""

from __future__ import annotations
from tests.auth_headers import bearerHeaders

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_default
from neurova.api.endpoints import memory as memory_pkg


@pytest.fixture()
def manager(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(
        db_path=str(tmp_path / "mem" / "memory.db"),
        agent_id="validity-agent",
        enable_buffer=False,
    )


@pytest.fixture()
def client(manager, monkeypatch):
    """挂真 router + 真 manager：走生产装配点 `get_app_state()`，不绕开取值路径。"""

    class _FakeAgent:
        memory_manager = manager

    class _FakeState:
        agents = {"validity-agent": _FakeAgent()}

        def get_agent(self, agent_id=None):
            return self.agents.get(agent_id or "validity-agent")

    import neurova.api.app as app_module

    monkeypatch.setattr(app_module, "get_app_state", lambda: _FakeState())

    app = FastAPI()
    app.include_router(memory_pkg.router, prefix="/v1/memory")
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "username": "tester", "role": "admin",
        "neuser_id": "default", "user_id": "default",
    }
    yield TestClient(app, headers=bearerHeaders("default"))
    app.dependency_overrides.clear()


class TestMemoryValidityWindowWriteFace:
    def test_validUntilLandsOnMemoryRow(self, client, manager):
        resp = client.post("/v1/memory", json={
            "content": "季度末过期的事实",
            "memory_type": "semantic",
            "valid_until": "2027-01-01T00:00:00+00:00",
        })
        assert resp.status_code == 200, resp.text[:200]
        memory_id = resp.json()["data"]["memory_id"]
        row = manager._memories[memory_id]
        assert row.valid_until is not None, "valid_until 必须真落到记忆行"
        assert row.valid_from is None

    def test_validFromAndUntilBothLand(self, client, manager):
        resp = client.post("/v1/memory", json={
            "content": "窗口内才有效",
            "valid_from": "2026-01-01T00:00:00+00:00",
            "valid_until": "2026-12-31T23:59:59+00:00",
        })
        assert resp.status_code == 200, resp.text[:200]
        row = manager._memories[resp.json()["data"]["memory_id"]]
        assert row.valid_from is not None and row.valid_until is not None

    def test_noWindowStaysNull(self, client, manager):
        resp = client.post("/v1/memory", json={"content": "普通记忆"})
        assert resp.status_code == 200, resp.text[:200]
        row = manager._memories[resp.json()["data"]["memory_id"]]
        assert row.valid_from is None and row.valid_until is None, "未声明窗口的行保持 NULL"

    def test_unparseableWindowIs422(self, client, manager):
        resp = client.post("/v1/memory", json={
            "content": "窗口写错的记忆",
            "valid_until": "下周三",
        })
        assert resp.status_code == 422, "非法 ISO 串在契约面 422，不吞成永远有效"
        assert not manager._memories, "拒收的请求不落行"

    def test_windowSurvivesReadBack(self, client, manager):
        """经 API 读回验证窗口仍在（写→读闭环）。"""
        resp = client.post("/v1/memory", json={
            "content": "读回窗口",
            "valid_until": "2027-06-30T12:00:00+00:00",
        })
        assert resp.status_code == 200
        memory_id = resp.json()["data"]["memory_id"]
        detail = client.get(f"/v1/memory/{memory_id}")
        assert detail.status_code == 200, detail.text[:200]
        assert manager._memories[memory_id].valid_until is not None, "读回后窗口仍在"
