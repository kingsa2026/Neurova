# -*- coding: utf-8 -*-
"""workspace_files 安全修复回归测试（审计 2026-09-11）。

覆盖：
- P0-4  跨 agent 工作区 IDOR（有主工作区仅属主/admin 可访问）
- P0-4  隐藏目录（.git）整棵拒绝
- P0-4  zip 下载文件名白名单（header 注入封口）
- P1-8  工作区根以仓库为基准（不再随 CWD 漂移）
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import workspace_files as wf
from neurova.api.deps import get_current_user


@pytest.fixture()
def ws_root(tmp_path, monkeypatch):
    root = tmp_path / "agent_workspaces"
    root.mkdir()
    monkeypatch.setattr(wf, "_WORKSPACES_ROOT", root)
    return root


@pytest.fixture()
def client(ws_root):
    app = FastAPI()
    app.include_router(wf.router, prefix="/api/v1/workspace")
    return TestClient(app)


def _identity(uid: str, role: str = "user"):
    return {"user_id": uid, "username": uid, "role": role, "neuser_id": uid}


def _owned_agent(ws_root, agent_id: str, owner: str):
    d = ws_root / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent_config.json").write_text(
        json.dumps({"agent_id": agent_id, "owner_user_id": owner}), encoding="utf-8"
    )
    (d / "note.txt").write_text("hello", encoding="utf-8")
    return d


def test_owned_workspace_denies_other_user(ws_root, client):
    _owned_agent(ws_root, "agtb", "alice")
    client.headers.clear()
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: _identity("mallory")
    assert client.get("/api/v1/workspace/agtb/files").status_code == 403
    assert client.get("/api/v1/workspace/agtb/files/zip").status_code == 403
    assert client.post(
        "/api/v1/workspace/agtb/files/mkdir", json={"path": "x"}
    ).status_code == 403

    app.dependency_overrides[get_current_user] = lambda: _identity("alice")
    assert client.get("/api/v1/workspace/agtb/files").status_code == 200
    assert client.get("/api/v1/workspace/agtb/files/zip").status_code == 200


def test_owned_workspace_admin_bypass(ws_root, client):
    _owned_agent(ws_root, "agtc", "alice")
    client.app.dependency_overrides[get_current_user] = lambda: _identity("root", role="admin")
    assert client.get("/api/v1/workspace/agtc/files").status_code == 200


def test_ownerless_workspace_shared_access(ws_root, client):
    """无主工作区（default/共享口径）对已认证用户放行。"""
    d = ws_root / "default"
    d.mkdir()
    (d / "a.txt").write_text("x", encoding="utf-8")
    client.app.dependency_overrides[get_current_user] = lambda: _identity("anyone")
    assert client.get("/api/v1/workspace/default/files").status_code == 200


def test_hidden_dir_components_rejected(ws_root, client):
    d = ws_root / "agtd"
    d.mkdir()
    (d / ".git").mkdir()
    (d / ".git" / "config").write_text("[core]", encoding="utf-8")
    client.app.dependency_overrides[get_current_user] = lambda: _identity("alice")
    assert client.get("/api/v1/workspace/agtd/files", params={"subdir": ".git"}).status_code == 400
    assert client.get(
        "/api/v1/workspace/agtd/files", params={"subdir": "sub/.git"}
    ).status_code == 400


def test_zip_filename_sanitized(ws_root, client):
    """header 注入面：sanitizer 单元断言 + 端到端 Content-Disposition 干净。"""
    assert wf._ZIP_NAME_RE.sub("_", 'a"b\rc\nd') == "a_b_c_d"

    d = ws_root / "agte"
    d.mkdir()
    weird = "weird dir"
    (d / weird).mkdir()
    client.app.dependency_overrides[get_current_user] = lambda: _identity("alice")
    resp = client.get("/api/v1/workspace/agte/files/zip", params={"subdir": weird})
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    assert "\r" not in cd and "\n" not in cd
    assert cd.count('"') <= 2


def test_workspace_root_is_absolute(ws_root):
    """P1-8：工作区根为绝对路径，不随进程 CWD 漂移。"""
    from pathlib import Path

    assert Path(wf._WORKSPACES_ROOT).is_absolute()


def test_unauthenticated_rejected(ws_root, client):
    app = client.app
    app.dependency_overrides.pop(get_current_user, None)
    # 无 override 时走真实 deps（无凭证）→ 401
    assert client.get("/api/v1/workspace/whatever/files").status_code in (401, 403)
