"""P1-2 记忆待确认队列 API 契约测试。

端点契约（/api/v1/memory 前缀）：
- GET  /pending              → 待审清单（本人提议；admin 全量）
- POST /pending/{id}/confirm → 确认入主库（调真实 remember；admin/提议人）
- POST /pending/{id}/reject  → 拒绝记指纹（admin/提议人）
- GET  /pending/decisions    → 裁决历史（仅 admin）
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth as memory_auth
from neurova.api.endpoints.memory import router as memory_router
from neurova.api.error_handlers import register_error_handlers
from neurova.memory.pending_memory import PendingMemoryStore

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}

PREFIX = "/api/v1/memory"


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = PendingMemoryStore(db_path=str(tmp_path / "pending.db"))
    monkeypatch.setattr(
        "neurova.memory.pending_memory.get_pending_memory_store", lambda: store
    )
    mm = MagicMock()
    mm.remember.return_value = "mem_confirmed"
    app = FastAPI()
    app.include_router(memory_router, prefix=PREFIX)
    register_error_handlers(app)
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[memory_auth.get_current_user_or_default] = lambda: holder["user"]
    client = TestClient(app)
    return client, holder, store, mm


def _propose(store, content="待确认内容", by="1"):
    return store.propose(content=content, proposed_by=by)


class TestPendingApi:
    def test_list_shows_own_proposals_only(self, api):
        client, holder, store, mm = api
        _propose(store, "alice 的提议", by="1")
        _propose(store, "bob 的提议", by="2")

        resp = client.get(f"{PREFIX}/pending")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert [i["content"] for i in items] == ["alice 的提议"]

        holder["user"] = dict(ADMIN)
        items = client.get(f"{PREFIX}/pending").json()["data"]["items"]
        assert len(items) == 2

    def test_confirm_calls_remember_and_returns_memory_id(self, api):
        client, holder, store, mm = api
        rec = _propose(store, by="1")
        with patch("neurova.api.endpoints.memory.pending.get_memory_manager", return_value=mm):
            resp = client.post(f"{PREFIX}/pending/{rec['id']}/confirm", json={"note": ""})
        assert resp.status_code == 200
        assert resp.json()["data"]["memory_id"] == "mem_confirmed"
        mm.remember.assert_called_once()
        assert store.list_pending() == []

    def test_confirm_stranger_forbidden(self, api):
        client, holder, store, mm = api
        rec = _propose(store, by="1")
        holder["user"] = {"user_id": "2", "username": "bob", "role": "user", "neuser_id": "2"}
        resp = client.post(f"{PREFIX}/pending/{rec['id']}/confirm", json={"note": ""})
        assert resp.status_code == 403

    def test_reject_blocks_reproposals(self, api):
        client, holder, store, mm = api
        rec = _propose(store, "会拒绝的内容", by="1")
        resp = client.post(f"{PREFIX}/pending/{rec['id']}/reject", json={"note": "不准确"})
        assert resp.status_code == 200

        # 同内容再提议：被指纹拦下（不产生新待审）
        store.propose(content="会拒绝的内容", proposed_by="1")
        assert store.list_pending() == []

    def test_decisions_admin_only(self, api):
        client, holder, store, mm = api
        rec = _propose(store, by="1")
        with patch("neurova.api.endpoints.memory.pending.get_memory_manager", return_value=mm):
            confirm_resp = client.post(f"{PREFIX}/pending/{rec['id']}/confirm", json={"note": ""})
        assert confirm_resp.status_code == 200, confirm_resp.text

        assert client.get(f"{PREFIX}/pending/decisions").status_code == 403
        holder["user"] = dict(ADMIN)
        resp = client.get(f"{PREFIX}/pending/decisions")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 1
