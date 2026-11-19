# -*- coding: utf-8 -*-
"""租户级共享（可靠性方案 §8-P1，2026-11-19 拍板复制发布语义）红灯。

- E1 shared_with 租户段：跨租户默认不可见（租户先于角色，admin 不穿透）；
  显式 `tenant:<id>` 段只读可见、取消即失效；检索 scope 与分片同判；
- E2 跨租户发布副本：源租户 admin 发起、目标租户 admin 审批，批准才落副本
  （origin_* 血缘、目标租户内初始 private、空属主归目标 admin），副本与源独立演进。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.repository import KnowledgeRepository

SRC_ADMIN = {"user_id": "1", "username": "src-admin", "role": "admin", "tenant_id": "tenant-a"}
SRC_USER = {"user_id": "2", "username": "src-user", "role": "user", "tenant_id": "tenant-a"}
DST_ADMIN = {"user_id": "3", "username": "dst-admin", "role": "admin", "tenant_id": "tenant-b"}
DST_USER = {"user_id": "4", "username": "dst-user", "role": "user", "tenant_id": "tenant-b"}


@pytest.fixture
def repo(tmp_path):
    return KnowledgeRepository(tmp_path)


def _mkEntry(repo, title="跨租户条目", **kw):
    return repo.create_knowledge(
        "agent-1", title=title, content="正文内容",
        tenant_id="tenant-a", owner_user_id="2", **kw)


class TestTenantShareSegment:
    def test_crossTenantInvisibleByDefaultEvenForAdmin(self, repo):
        """现状基线：跨租户一律不可见，admin 也不穿透——本批不许破坏。"""
        entry = _mkEntry(repo)

        assert repo.can_view(DST_ADMIN, entry) is False
        assert repo.can_view(DST_USER, entry) is False
        assert all(i["knowledge_id"] != entry["knowledge_id"]
                   for i in repo.visible_items(DST_ADMIN))

    def test_tenantSegmentGrantsReadOnlyCrossTenantView(self, repo):
        entry = _mkEntry(repo)
        repo.share_tenants(SRC_ADMIN, entry["knowledge_id"], ["tenant-b"])

        shared = repo.get_item("agent-1", entry["knowledge_id"])
        assert repo.can_view(DST_ADMIN, shared) is True
        assert repo.can_view(DST_USER, shared) is True
        # 只读：跨租户分享不改写权限，分类写权也不外放
        assert repo.can_modify(DST_ADMIN, shared) is False
        assert repo.can_modify(DST_USER, shared) is False
        assert repo.can_categorize(DST_USER, shared) is False

    def test_unshareTenantRevokesImmediately(self, repo):
        entry = _mkEntry(repo)
        repo.share_tenants(SRC_ADMIN, entry["knowledge_id"], ["tenant-b"])
        repo.unshare_tenants(SRC_ADMIN, entry["knowledge_id"], ["tenant-b"])

        shared = repo.get_item("agent-1", entry["knowledge_id"])
        assert repo.can_view(DST_USER, shared) is False
        assert all(i["knowledge_id"] != entry["knowledge_id"]
                   for i in repo.visible_items(DST_USER))

    def test_sharedScopeSearchHitsTenantSegment(self, repo):
        entry = _mkEntry(repo)
        repo.share_tenants(SRC_ADMIN, entry["knowledge_id"], ["tenant-b"])
        shared = repo.get_item("agent-1", entry["knowledge_id"])
        kid = entry["knowledge_id"]

        ids = [i["knowledge_id"] for i in repo.visible_items(DST_USER, scope="shared")]
        assert kid in ids
        ids = [i["knowledge_id"] for i in repo.visible_items(DST_USER, scope="all")]
        assert kid in ids
        ids = [i["knowledge_id"] for i in repo.visible_items(DST_USER, scope="public")]
        assert kid not in ids
        ids = [i["knowledge_id"] for i in repo.visible_items(DST_USER, scope="private")]
        assert kid not in ids

    def test_shareTenantsRejectsSelfTenant(self, repo):
        entry = _mkEntry(repo)

        with pytest.raises(ValueError, match="自身"):
            repo.share_tenants(SRC_ADMIN, entry["knowledge_id"], ["tenant-a"])

    def test_userSegmentSharingStillWorks(self, repo):
        """回归钉：既有用户级 shared_with 行为零漂移（同租户内只读可见）。"""
        entry = _mkEntry(repo)
        repo.share_entry(SRC_ADMIN, entry["knowledge_id"], ["5"])

        sameTenantUser = {"user_id": "5", "username": "src-user2",
                          "role": "user", "tenant_id": "tenant-a"}
        shared = repo.get_item("agent-1", entry["knowledge_id"])
        assert repo.can_view(sameTenantUser, shared) is True
        assert repo.can_modify(sameTenantUser, shared) is False


class TestPublishCopy:
    def test_requestRequiresSourceAdmin(self, repo):
        entry = _mkEntry(repo)

        with pytest.raises(PermissionError):
            repo.request_publish_copy(SRC_USER, entry["knowledge_id"], "tenant-b")

    def test_requestRequiresDistinctTenant(self, repo):
        entry = _mkEntry(repo)

        with pytest.raises(ValueError, match="自身|target"):
            repo.request_publish_copy(SRC_ADMIN, entry["knowledge_id"], "tenant-a")

    def test_pendingRequestCreatesNoVisibleCopy(self, repo):
        entry = _mkEntry(repo)
        req = repo.request_publish_copy(SRC_ADMIN, entry["knowledge_id"], "tenant-b")

        assert req["status"] == "pending"
        # 请求不是条目：目标租户此刻看不到任何副本
        assert all(i.get("origin_knowledge_id") != entry["knowledge_id"]
                   for i in repo.visible_items(DST_ADMIN))
        pending = repo.pending_copy_requests(DST_ADMIN)
        assert len(pending) == 1 and pending[0]["request_id"] == req["request_id"]

    def test_targetAdminApproveLandsPrivateCopyWithOrigin(self, repo):
        entry = _mkEntry(repo)
        req = repo.request_publish_copy(SRC_ADMIN, entry["knowledge_id"], "tenant-b")

        result = repo.decide_publish_copy(DST_ADMIN, req["request_id"], approve=True)

        copy = repo.get_item("agent-1", result["copy_knowledge_id"])
        assert copy is not None
        assert copy["tenant_id"] == "tenant-b"
        assert copy["origin_tenant_id"] == "tenant-a"
        assert copy["origin_knowledge_id"] == entry["knowledge_id"]
        assert copy["visibility"] == "private"
        assert copy["owner_user_id"] == "3"
        # 目标租户 admin 可见（空属主归 admin），普通用户不可见——公开仍走目标侧审批链
        assert repo.can_view(DST_ADMIN, copy) is True
        assert repo.can_view(DST_USER, copy) is False
        # 源侧请求留痕可反查
        src = repo.get_item("agent-1", entry["knowledge_id"])
        rec = [r for r in src.get("copy_requests", []) if r["status"] == "approved"]
        assert len(rec) == 1 and rec[0]["copy_knowledge_id"] == result["copy_knowledge_id"]

    def test_targetAdminRejectLandsNothing(self, repo):
        entry = _mkEntry(repo)
        req = repo.request_publish_copy(SRC_ADMIN, entry["knowledge_id"], "tenant-b")

        repo.decide_publish_copy(DST_ADMIN, req["request_id"], approve=False, note="暂不接收")

        src = repo.get_item("agent-1", entry["knowledge_id"])
        rec = [r for r in src.get("copy_requests", []) if r["status"] == "rejected"]
        assert len(rec) == 1
        assert all(i.get("origin_knowledge_id") != entry["knowledge_id"]
                   for i in repo.visible_items(DST_ADMIN))

    def test_decideRequiresTargetAdmin(self, repo):
        entry = _mkEntry(repo)
        req = repo.request_publish_copy(SRC_ADMIN, entry["knowledge_id"], "tenant-b")

        with pytest.raises(PermissionError):
            repo.decide_publish_copy(SRC_ADMIN, req["request_id"], approve=True)

    def test_copyIsIndependentFromSourceEdits(self, repo):
        entry = _mkEntry(repo, title="原标题")
        req = repo.request_publish_copy(SRC_ADMIN, entry["knowledge_id"], "tenant-b")
        result = repo.decide_publish_copy(DST_ADMIN, req["request_id"], approve=True)

        repo.update_knowledge("agent-1", entry["knowledge_id"],
                              {"title": "新标题", "content": "新正文"})

        copy = repo.get_item("agent-1", result["copy_knowledge_id"])
        assert copy["title"] == "原标题"
