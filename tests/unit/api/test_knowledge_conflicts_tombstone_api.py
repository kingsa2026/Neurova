"""P0-2/P0-3 API 契约测试（Utopia 对标落地清单）。

端点契约：
- GET  /v1/knowledge/conflicts            → 冲突清单（仅管理员；非 admin 403）
- POST /v1/knowledge/conflicts/{id}/resolve → 裁决（仅管理员；resolution 非法 400）
- GET  /v1/knowledge/deleted              → 墓碑清单（仅管理员；非 admin 403）
- POST /v1/knowledge/{id}/restore         → 复活（属主/管理员；他人 403；未删 404）
- GET  /v1/knowledge/{id}/revisions       → revision 账本（仅可见条目）
- DELETE /v1/knowledge/{id}               → tombstone（条目从所有视图消失，可在 /deleted 审计）
- DELETE /v1/knowledge/{id}?purge=true    → 物理删除（原 purge 通道语义保留）
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}

PREFIX = "/v1/knowledge"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: r)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    client = TestClient(app)
    return client, holder, r


class TestConflictApi:
    def test_list_conflicts_admin_only(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "同名A", "content": "a"})
        client.post(PREFIX, json={"title": "同名A", "content": "b"})

        holder["user"] = dict(ALICE)
        assert client.get(f"{PREFIX}/conflicts").status_code == 403

        holder["user"] = dict(ADMIN)
        resp = client.get(f"{PREFIX}/conflicts")
        assert resp.status_code == 200
        conflicts = resp.json()
        assert len(conflicts) == 1
        assert conflicts[0]["status"] == "pending"
        assert conflicts[0]["similarity"] >= 0.9

    def test_resolve_supersede_hides_old(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "裁决条目", "content": "a"})
        client.post(PREFIX, json={"title": "裁决条目", "content": "b"})
        cid = client.get(f"{PREFIX}/conflicts").json()[0]["conflict_id"]

        resp = client.post(
            f"{PREFIX}/conflicts/{cid}/resolve", json={"resolution": "supersede_old"}
        )
        assert resp.status_code == 200
        assert client.get(f"{PREFIX}/conflicts").json() == []

        deleted_ids = {d["knowledge_id"] for d in client.get(f"{PREFIX}/deleted").json()}
        conflicts_resolved = client.get(f"{PREFIX}/conflicts?status=resolved").json()
        assert len(conflicts_resolved) == 1
        # 被取代的旧条目在墓碑里
        assert repo.list_deleted()[0]["superseded_by"] is not None

    def test_resolve_invalid_resolution_400(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "非法", "content": "a"})
        client.post(PREFIX, json={"title": "非法", "content": "b"})
        cid = client.get(f"{PREFIX}/conflicts").json()[0]["conflict_id"]
        resp = client.post(f"{PREFIX}/conflicts/{cid}/resolve", json={"resolution": "nuke"})
        assert resp.status_code == 400


class TestTombstoneApi:
    def test_delete_then_admin_sees_tombstone_and_owner_restores(self, api):
        client, holder, repo = api
        holder["user"] = dict(ALICE)
        kid = client.post(PREFIX, json={"title": "可复活的", "content": "c"}).json()["knowledge_id"]
        resp = client.delete(f"{PREFIX}/{kid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "deleted"
        assert client.get(f"{PREFIX}/{kid}").status_code == 404

        # 墓碑清单仅管理员
        holder["user"] = dict(ALICE)
        assert client.get(f"{PREFIX}/deleted").status_code == 403
        holder["user"] = dict(ADMIN)
        deleted = client.get(f"{PREFIX}/deleted").json()
        assert len(deleted) == 1
        assert deleted[0]["knowledge_id"] == kid
        assert deleted[0]["deleted_by"] == "1"

        # 他人不可复活
        bob = {"user_id": "2", "username": "bob", "role": "user", "neuser_id": "2"}
        holder["user"] = dict(bob)
        assert client.post(f"{PREFIX}/{kid}/restore").status_code == 403

        # 属主复活成功，条目回到视图
        holder["user"] = dict(ALICE)
        resp = client.post(f"{PREFIX}/{kid}/restore")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "restored"
        assert client.get(f"{PREFIX}/{kid}").status_code == 200

    def test_restore_not_deleted_404(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        kid = client.post(PREFIX, json={"title": "活着", "content": "c"}).json()["knowledge_id"]
        assert client.post(f"{PREFIX}/{kid}/restore").status_code == 404

    def test_purge_keeps_physical_channel(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        kid = client.post(PREFIX, json={"title": "违规", "content": "c"}).json()["knowledge_id"]
        resp = client.delete(f"{PREFIX}/{kid}?purge=true")
        assert resp.status_code == 200
        # 契约沿用旧值（test_knowledge_unpublish 锁定 action == "deleted"）
        assert resp.json()["data"]["action"] == "deleted"
        assert repo.get_item("default", kid) is None
        assert client.get(f"{PREFIX}/deleted").json() == []


class TestRevisionsApi:
    def test_revisions_visible_and_ordered(self, api):
        client, holder, repo = api
        holder["user"] = dict(ALICE)
        kid = client.post(PREFIX, json={"title": "v0", "content": "c0"}).json()["knowledge_id"]
        client.put(f"{PREFIX}/{kid}", json={"title": "v1"})
        client.put(f"{PREFIX}/{kid}", json={"title": "v2", "content": "c2"})

        holder["user"] = dict(ADMIN)
        revs = client.get(f"{PREFIX}/{kid}/revisions").json()
        assert len(revs) == 2
        assert revs[0]["old"]["title"] == "v1"  # 最新在前
        assert revs[1]["old"]["title"] == "v0"

    def test_revisions_unknown_entry_404(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        assert client.get(f"{PREFIX}/no-such/revisions").status_code == 404
