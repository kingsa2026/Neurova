# -*- coding: utf-8 -*-
"""分类写权限口径（用户裁定 2026-11-09）：**分类仅对公共库设归属门**。

裁定：公共库条目改分类影响全员可见面（部门白名单按分类收口），归属主/管理员；
私有条目（私人库＋共享给我）已由可见性按用户隔离——可见即可改分类，不再另设
归属门。其余字段（正文/标题/标签…）维持「被共享者只读」不变：本判据同时钉住
放宽是**按字段选门**，不是把 can_modify 整体放开。

判据面（真仓库 + 真路由 + 身份覆盖，行为断言不在 mock 仓库上）：
- 共享给我（private + shared_with 命中）→ PUT 只带 category：200 且分类落库、正文不动；
- 陌生人（不可见）→ 404（不泄露存在性）；
- 公共条目：被共享者/陌生人 403，属主与 admin 200；
- 混合字段（category+title）→ 仍走属主/管理员门 403；
- 属主与 admin 的既有路径不回退（反向钉）；
- 部门白名单不被放宽绕开：白名单外条目对受限用户连可见都没有（404）；
- 仓库层 can_modify 对被共享者仍为 False——放宽只发生在 API 按字段选门这一层。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "alice", "role": "user", "tenant_id": "default"}
BOB = {"user_id": "2", "username": "bob", "role": "user", "tenant_id": "default"}
CAROL = {"user_id": "3", "username": "carol", "role": "user", "tenant_id": "default"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}

UNRESTRICTED = {"restricted": False, "allowed_categories": [], "tenant_id": "default"}
DEPT_RND_ONLY = {
    "tenant_id": "default",
    "group_id": "g1",
    "allowed_categories": ["rnd"],
    "restricted": True,
    "default_category": None,
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment",
        lambda username, **kw: UNRESTRICTED,
    )
    repo = KnowledgeRepository(str(tmp_path))
    shared_id = repo.create_knowledge(
        agent_id="a1", title="共享条目", content="共享正文原文", category="general",
        owner_user_id="1",
    )["knowledge_id"]
    repo.share_entry(ALICE, shared_id, ["2"])
    private_id = repo.create_knowledge(
        agent_id="a1", title="私有条目", content="私有正文原文", category="general",
        owner_user_id="1",
    )["knowledge_id"]
    public_id = repo.create_knowledge(
        agent_id="a1", title="公共条目", content="公共正文原文", category="general",
        owner_user_id="1", visibility="public",
    )["knowledge_id"]

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix="/v1/knowledge")
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
        lambda: holder["user"]
    )
    monkeypatch.setattr(
        "neurova.api.endpoints.knowledge_core.get_repository", lambda: repo
    )
    yield {
        "client": TestClient(app),
        "repo": repo,
        "holder": holder,
        "shared_id": shared_id,
        "private_id": private_id,
        "public_id": public_id,
    }


def _putAs(env, user, kid, payload):
    env["holder"]["user"] = dict(user)
    return env["client"].put(f"/v1/knowledge/{kid}", json=payload)


class TestCategoryOnlyRelaxation:
    def test_sharee_recategorizes_shared_private_entry(self, env):
        repo = env["repo"]
        resp = _putAs(env, BOB, env["shared_id"], {"category": "ops"})

        assert resp.status_code == 200, resp.text
        item = repo.get_item("a1", env["shared_id"])
        assert item["category"] == "ops", "分类须真实落库"
        assert item["content"] == "共享正文原文", "分类放宽不得波及正文"

    def test_stranger_still_404_on_invisible_entry(self, env):
        for kid in (env["shared_id"], env["private_id"]):
            resp = _putAs(env, CAROL, kid, {"category": "ops"})
            assert resp.status_code == 404, (kid, resp.status_code)
            assert env["repo"].get_item("a1", kid)["category"] == "general", "404 之外不得落库"

    def test_owner_and_admin_private_paths_unchanged(self, env):
        resp = _putAs(env, ALICE, env["private_id"], {"category": "ops"})
        assert resp.status_code == 200, resp.text
        resp = _putAs(env, ADMIN, env["shared_id"], {"category": "rnd"})
        assert resp.status_code == 200, resp.text


class TestPublicAndStrictGatesStay:
    def test_public_category_still_owner_or_admin(self, env):
        assert _putAs(env, BOB, env["public_id"], {"category": "ops"}).status_code == 403
        assert _putAs(env, CAROL, env["public_id"], {"category": "ops"}).status_code == 403
        assert _putAs(env, ALICE, env["public_id"], {"category": "ops"}).status_code == 200
        assert _putAs(env, ADMIN, env["public_id"], {"category": "rnd"}).status_code == 200

    def test_sharee_content_write_still_403(self, env):
        resp = _putAs(env, BOB, env["shared_id"], {"content": "篡改正文"})

        assert resp.status_code == 403, resp.text
        assert env["repo"].get_item("a1", env["shared_id"])["content"] == "共享正文原文"

    def test_mixed_fields_keep_strict_gate(self, env):
        resp = _putAs(env, BOB, env["shared_id"], {"category": "ops", "title": "改名"})

        assert resp.status_code == 403, "夹带非分类字段即回严门"
        item = env["repo"].get_item("a1", env["shared_id"])
        assert item["category"] == "general" and item["title"] == "共享条目"


class TestIsolationNotBypassed:
    def test_dept_whitelist_still_hides_entry_from_restricted_sharee(self, env, monkeypatch):
        monkeypatch.setattr(
            "neurova.auth.user_group_model.resolveUserDepartment",
            lambda username, **kw: DEPT_RND_ONLY if username == "bob" else UNRESTRICTED,
        )
        resp = _putAs(env, BOB, env["shared_id"], {"category": "rnd"})

        assert resp.status_code == 404, "白名单外条目对受限用户不可见，放宽不得把可见性修穿"
        assert env["repo"].get_item("a1", env["shared_id"])["category"] == "general"

    def test_relaxation_is_field_scoped_not_a_can_modify_change(self, env):
        repo = env["repo"]
        shared = repo.find_item(env["shared_id"])[1]

        assert repo.can_modify(BOB, shared) is False, "仓库层归属门必须原样保留"
        resp = _putAs(env, BOB, env["shared_id"], {"category": "ops"})
        assert resp.status_code == 200, "放宽只发生在 API 按字段选门这一层"
