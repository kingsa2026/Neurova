"""治理端点的租户隔离契约（交接文档 2026-10-31 §3）。

同一文件的 list 端点已按租户过滤，但 resolve / restore / 待审清单没有：
租户 A 的管理员拿着租户 B 的 conflict_id / knowledge_id 仍能裁决或复活，
待审队列也会跨租户泄露。判据一律走 HTTP 端点（生产装配点），不直接调私有方法。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_tenant_isolation_012345")

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

PREFIX = "/v1/knowledge"


def _user(tenant, *, role="admin", uid="9"):
    return {"user_id": uid, "username": f"{tenant}-{uid}", "role": role,
            "neuser_id": uid, "tenant_id": tenant}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: repo)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": _user("tenant-a")}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    return TestClient(app), holder, repo


def _seedConflict(client):
    client.post(PREFIX, json={"title": "同名租户冲突", "content": "a"})
    client.post(PREFIX, json={"title": "同名租户冲突", "content": "b"})
    return client.get(f"{PREFIX}/conflicts").json()[0]["conflict_id"]


def test_cross_tenant_resolve_conflict_is_404(api):
    client, holder, repo = api
    cid = _seedConflict(client)

    holder["user"] = _user("tenant-b")
    resp = client.post(f"{PREFIX}/conflicts/{cid}/resolve",
                       json={"resolution": "keep_both"})
    assert resp.status_code == 404
    assert repo.list_conflicts(status="pending", tenantId="tenant-a")[0]["status"] == "pending"

    holder["user"] = _user("tenant-a")
    assert client.post(f"{PREFIX}/conflicts/{cid}/resolve",
                       json={"resolution": "keep_both"}).status_code == 200


def test_cross_tenant_restore_is_404_and_tombstone_hidden(api):
    client, holder, repo = api
    kid = client.post(PREFIX, json={"title": "租户A条目", "content": "x"}).json()["knowledge_id"]
    assert client.delete(f"{PREFIX}/{kid}").status_code in (200, 204)

    holder["user"] = _user("tenant-b")
    assert client.get(f"{PREFIX}/deleted").json() == []
    assert client.post(f"{PREFIX}/{kid}/restore").status_code == 404
    assert any(r["knowledge_id"] == kid for r in repo.list_deleted())

    holder["user"] = _user("tenant-a")
    assert client.post(f"{PREFIX}/{kid}/restore").status_code == 200


def test_pending_submissions_scoped_to_tenant(api):
    client, holder, _ = api
    kid = client.post(PREFIX, json={"title": "待审条目", "content": "y"}).json()["knowledge_id"]
    assert client.post(f"{PREFIX}/{kid}/submit-public").status_code == 200
    assert len(client.get(f"{PREFIX}/public-submissions").json()) == 1

    holder["user"] = _user("tenant-b")
    assert client.get(f"{PREFIX}/public-submissions").json() == []
