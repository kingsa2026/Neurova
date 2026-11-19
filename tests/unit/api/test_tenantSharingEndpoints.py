# -*- coding: utf-8 -*-
"""租户级共享端点（可靠性方案 §8-P1）。

- share/unshare body 扩展 tenant_ids（shared_with 写 `tenant:<id>` 段）；
- publish-copy：源租户 admin 发起 → 目标租户 admin 审批 → 副本落库（origin 血缘）；
- 字面路由 /copy-requests 先于 GET /{knowledge_id} 注册（遮蔽契约）。
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

SRC_ADMIN = {"user_id": "1", "username": "src-admin", "role": "admin",
             "tenant_id": "tenant-a", "neuser_id": "1"}
SRC_USER = {"user_id": "2", "username": "src-user", "role": "user",
            "tenant_id": "tenant-a", "neuser_id": "2"}
DST_ADMIN = {"user_id": "3", "username": "dst-admin", "role": "admin",
             "tenant_id": "tenant-b", "neuser_id": "3"}

PREFIX = "/v1/knowledge"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: r)
    # 组树在单测里不装：租户存在性校验只保留"非空"这一层（repo 层已挡自身租户）
    monkeypatch.setattr("neurova.api.endpoints.knowledge_sharing._ensureTenantExists",
                        lambda tid: None)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(SRC_ADMIN)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    client = TestClient(app)
    return client, holder, r


def _mkEntry(client, holder, title="跨租户条目"):
    holder["user"] = dict(SRC_ADMIN)
    resp = client.post(PREFIX, json={"title": title, "content": "正文内容"})
    assert resp.status_code == 200, resp.text
    return resp.json()["knowledge_id"]


class TestShareTenantSegmentEndpoint:
    def test_shareWithTenantIdsWritesSegment(self, api):
        client, holder, repo = api
        kid = _mkEntry(client, holder)

        resp = client.post(f"{PREFIX}/{kid}/share",
                           json={"tenant_ids": ["tenant-b"]})

        assert resp.status_code == 200, resp.text
        item = repo.get_item("agent-1", kid) or next(
            (i for items in repo._items.values() for i in items
             if i["knowledge_id"] == kid), None)
        assert "tenant:tenant-b" in (item.get("shared_with") or [])

    def test_shareRequiresUsernamesOrTenantIds(self, api):
        client, holder, repo = api
        kid = _mkEntry(client, holder)

        resp = client.post(f"{PREFIX}/{kid}/share", json={})

        assert resp.status_code == 400

    def test_copyRequestsLiteralRouteNotShadowed(self, api):
        """GET /copy-requests 是字面路由，不得被 GET /{knowledge_id} 吞成 404。"""
        client, holder, _ = api
        holder["user"] = dict(DST_ADMIN)

        resp = client.get(f"{PREFIX}/copy-requests")

        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 0


class TestPublishCopyEndpoint:
    def test_roundtripApproveLandsCopy(self, api):
        client, holder, repo = api
        kid = _mkEntry(client, holder)

        resp = client.post(f"{PREFIX}/{kid}/publish-copy",
                           json={"target_tenant": "tenant-b"})
        assert resp.status_code == 200, resp.text
        requestId = resp.json()["data"]["request_id"]

        holder["user"] = dict(DST_ADMIN)
        pending = client.get(f"{PREFIX}/copy-requests").json()["data"]
        assert len(pending) == 1 and pending[0]["request_id"] == requestId

        decide = client.post(f"{PREFIX}/copy-requests/{requestId}/decide",
                             json={"approve": True})
        assert decide.status_code == 200, decide.text
        copyId = decide.json()["data"]["copy_knowledge_id"]
        assert copyId

        copies = [i for items in repo._items.values() for i in items
                  if i.get("origin_knowledge_id") == kid]
        assert len(copies) == 1
        assert copies[0]["tenant_id"] == "tenant-b"
        assert copies[0]["origin_tenant_id"] == "tenant-a"
        assert copies[0]["knowledge_id"] == copyId

    def test_publishCopyRejectsNonAdmin(self, api):
        client, holder, _ = api
        # 属主本人（非 admin）发起：可见可改，但跨租户发布是治理动作，仍 403
        holder["user"] = dict(SRC_USER)
        resp = client.post(PREFIX, json={"title": "跨租户条目", "content": "正文内容"})
        assert resp.status_code == 200, resp.text
        kid = resp.json()["knowledge_id"]

        resp = client.post(f"{PREFIX}/{kid}/publish-copy",
                           json={"target_tenant": "tenant-b"})

        assert resp.status_code == 403

    def test_decideBySourceAdminRejected(self, api):
        client, holder, _ = api
        kid = _mkEntry(client, holder)
        holder["user"] = dict(SRC_ADMIN)
        requestId = client.post(f"{PREFIX}/{kid}/publish-copy",
                                json={"target_tenant": "tenant-b"}).json()["data"]["request_id"]

        resp = client.post(f"{PREFIX}/copy-requests/{requestId}/decide",
                           json={"approve": True})

        assert resp.status_code == 403

    def test_rejectLandsNothing(self, api):
        client, holder, repo = api
        kid = _mkEntry(client, holder)
        holder["user"] = dict(SRC_ADMIN)
        requestId = client.post(f"{PREFIX}/{kid}/publish-copy",
                                json={"target_tenant": "tenant-b"}).json()["data"]["request_id"]
        holder["user"] = dict(DST_ADMIN)

        resp = client.post(f"{PREFIX}/copy-requests/{requestId}/decide",
                           json={"approve": False, "note": "暂不接收"})

        assert resp.status_code == 200
        assert resp.json()["data"]["copy_knowledge_id"] is None
        assert all(i.get("origin_knowledge_id") != kid
                   for items in repo._items.values() for i in items)
