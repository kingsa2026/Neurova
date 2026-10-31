# -*- coding: utf-8 -*-
"""批 S 红灯判据（docs/specs/2026-10-31-full-repo-defect-sweep-fixplan.md 批 S）。

S1 console 附件属主隔离 / S2 skill_pool 审批六腿门 / S3 图谱补建越权。
S4（检索缓存隔离）在 tests/unit/agent/test_retrievalCacheIsolation.py。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── S1：console 附件属主隔离 ─────────────────────────────────────────────

U1 = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}
U2 = {"user_id": "u2", "username": "u2", "role": "user", "neuser_id": "u2"}


@pytest.fixture()
def files_env(tmp_path, monkeypatch):
    from neurova.api import deps as deps_mod
    from neurova.api.endpoints import console as console_mod
    from neurova.api.endpoints import console_files

    monkeypatch.setattr(console_mod, "_CONSOLE_UPLOAD_DIR", tmp_path / "uploads")
    app = FastAPI()
    app.include_router(console_files.router, prefix="/api/v1/console")
    holder = {"user": dict(U1)}

    def _user():
        return holder["user"]

    # 端点签名是 Depends(deps.get_current_user)——必须以函数对象为键做 override
    app.dependency_overrides[deps_mod.get_current_user] = _user
    yield TestClient(app), holder


def test_s1_upload_lands_in_owner_scope_and_lists_only_own(files_env):
    client, holder = files_env
    r1 = client.post(
        "/api/v1/console/upload",
        files={"file": ("a.txt", b"hello-a", "text/plain")},
    )
    assert r1.status_code == 200, r1.text

    holder["user"] = dict(U2)
    listed = client.get("/api/v1/console/uploads").json()["data"]["files"]
    assert listed == [], "user2 不得看到 user1 的附件（修前全共享可见）"

    holder["user"] = dict(U1)
    mine = client.get("/api/v1/console/uploads").json()["data"]["files"]
    assert len(mine) == 1 and mine[0]["filename"].endswith("a.txt")


def test_s1_download_other_users_file_is_404(files_env):
    client, holder = files_env
    info = client.post(
        "/api/v1/console/upload",
        files={"file": ("secret.txt", b"top secret", "text/plain")},
    ).json()["data"]
    stored_name = info["filename"]

    holder["user"] = dict(U2)
    resp = client.get(f"/api/v1/console/uploads/{stored_name}")
    assert resp.status_code == 404, (
        f"跨属主下载必须 404，实得 {resp.status_code}（修前 200 泄漏内容）"
    )


def test_s1_delete_other_users_file_is_404(files_env):
    client, holder = files_env
    info = client.post(
        "/api/v1/console/upload",
        files={"file": ("keep.txt", b"data", "text/plain")},
    ).json()["data"]
    stored_name = info["filename"]

    stored = f"{info['file_id']}_{info['filename']}"
    holder["user"] = dict(U2)
    resp = client.delete(f"/api/v1/console/uploads/{stored}")
    assert resp.status_code == 404, (
        f"跨属主删除必须 404，实得 {resp.status_code}（修前他人文件可被删）"
    )

    holder["user"] = dict(U1)
    assert client.get(f"/api/v1/console/uploads/{stored}").status_code == 200


# ── S2：skill_pool 待审批面六腿的门 ─────────────────────────────────────

OWNER = {"user_id": "owner1", "username": "owner1", "role": "user", "neuser_id": "owner1"}
STRANGER = {"user_id": "stranger", "username": "stranger", "role": "user", "neuser_id": "s"}


class _StubPacker:
    def list_pending_templates(self):
        return [{"template_id": "t1"}]

    def approve_template(self, template_id):
        return True

    def reject_template(self, template_id):
        return True


class _StubAgent:
    skill_packer = _StubPacker()


@pytest.fixture()
def pool_env(tmp_path, monkeypatch):
    from neurova.api import deps as deps_mod
    from neurova.api.endpoints import skill_pool_api as sp

    app = FastAPI()
    app.include_router(sp.router, prefix="/api/v1/skills")
    holder = {"user": dict(OWNER)}
    app.dependency_overrides[deps_mod.get_current_user] = lambda: holder["user"]
    monkeypatch.setattr(
        "neurova.api.endpoints.governance._get_agent",
        lambda agent_id: _StubAgent(),
    )
    monkeypatch.setattr(sp, "_agent_owner", lambda agent_id: "owner1")
    client = TestClient(app)
    return client, holder


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/skills/agent/agentA/pending-skills"),
        ("post", "/api/v1/skills/agent/agentA/pending-skills/t1/approve"),
        ("post", "/api/v1/skills/agent/agentA/pending-skills/t1/reject"),
        ("get", "/api/v1/skills/agent/agentA/pending-experiences"),
        ("post", "/api/v1/skills/agent/agentA/pending-experiences/r1/approve"),
        ("post", "/api/v1/skills/agent/agentA/pending-experiences/r1/reject"),
    ],
)
def test_s2_pending_faces_require_agent_access(pool_env, method, path):
    """六条腿补 _require_agent_access：非 owner 非 admin → 403（修前放行）。"""
    client, holder = pool_env
    holder["user"] = dict(STRANGER)
    resp = getattr(client, method)(path)
    assert resp.status_code == 403, (
        f"{method.upper()} {path} 越权访问他人 agent 审批面必须 403，"
        f"实得 {resp.status_code}"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/skills/agent/agentA/pending-skills"),
        ("post", "/api/v1/skills/agent/agentA/pending-skills/t1/approve"),
        ("get", "/api/v1/skills/agent/agentA/pending-experiences"),
    ],
)
def test_s2_owner_still_passes(pool_env, method, path):
    """反向控制：owner 本人必须照常可达。"""
    client, holder = pool_env
    resp = getattr(client, method)(path)
    assert resp.status_code in (200,), f"{path} owner 被误伤：{resp.status_code}"


# ── S3：图谱补建端点的门 ─────────────────────────────────────────────────


def test_s3_backfill_requires_admin(tmp_path, monkeypatch):
    from neurova.api import auth as auth_mod
    from neurova.api.endpoints import knowledge_graph_api as kga

    app = FastAPI()
    app.include_router(kga.router, prefix="/api/v1/knowledge-graph")
    holder = {"user": {"user_id": "u9", "username": "u9", "role": "user", "neuser_id": "u9"}}
    app.dependency_overrides[auth_mod.get_current_user_or_service] = lambda: holder["user"]
    client = TestClient(app)

    resp = client.post("/api/v1/knowledge-graph/agentA/knowledge-graph/backfill")
    assert resp.status_code == 403, (
        f"普通用户不得对全 agent 域条目跑 LLM 抽取（跨租户泄漏面），"
        f"实得 {resp.status_code}"
    )
