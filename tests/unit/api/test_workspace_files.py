# -*- coding: utf-8 -*-
"""B3-4 工作区文件管理 API 测试（QwenPaw #7078/#7151 对齐）。

锁定契约：
1. agent_id 校验（非法字符 400）。
2. 路径穿越 fail-closed（../ 逃逸一律 400）。
3. list/mkdir/copy/move/zip 全链。
4. 已存在目标未 overwrite → 409。
"""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import workspace_files as wf


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 工作区根锚定到 tmp（防污染真实 agent_workspaces）
    import re

    def fake_root(agent_id: str):
        if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", agent_id or ""):
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=f"Invalid agent_id: '{agent_id}'")
        root = tmp_path / "agent_workspaces" / agent_id
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    monkeypatch.setattr(wf, "_workspace_root", fake_root)

    app = FastAPI()
    app.include_router(wf.router, prefix="/api/v1/workspace")
    # 鉴权依赖 override（单测聚焦文件管理逻辑本身）
    app.dependency_overrides[wf._get_current_user] = lambda: {"user_id": "t"}
    return TestClient(app)


def _write_file(root_dir, rel, content: str):
    import pathlib

    p = pathlib.Path(root_dir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestWorkspaceFiles:
    def test_invalid_agent_id_rejected(self, client):
        resp = client.get("/api/v1/workspace/..%2Fevil/files")
        assert resp.status_code in (400, 404)

    def test_mkdir_and_list(self, client):
        r = client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "docs/sub"})
        assert r.status_code == 200
        r2 = client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "docs/sub"})
        assert r2.status_code == 409
        listing = client.get("/api/v1/workspace/alpha/files", params={"subdir": "docs"})
        assert listing.status_code == 200
        names = [e["name"] for e in listing.json()["data"]["entries"]]
        assert names == ["sub"]

    def test_copy_move_flow(self, client, tmp_path):
        client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "src"})
        root = tmp_path / "agent_workspaces" / "alpha"
        _write_file(root, "src/a.txt", "hello")
        r = client.post("/api/v1/workspace/alpha/files/copy", json={
            "source": "src/a.txt", "path": "src/b.txt"})
        assert r.status_code == 200
        assert (root / "src" / "b.txt").read_text(encoding="utf-8") == "hello"
        r2 = client.post("/api/v1/workspace/alpha/files/move", json={
            "source": "src/b.txt", "path": "src/c.txt"})
        assert r2.status_code == 200
        assert (root / "src" / "b.txt").exists() is False
        assert (root / "src" / "c.txt").exists() is True

    def test_path_traversal_fail_closed(self, client):
        resp = client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "../../escape"})
        assert resp.status_code == 400
        resp2 = client.post("/api/v1/workspace/alpha/files/move", json={
            "source": "../outside", "path": "in"})
        assert resp2.status_code == 400
        resp3 = client.post("/api/v1/workspace/alpha/files/copy", json={
            "source": "a", "path": "x/../../y"})
        assert resp3.status_code == 400

    def test_move_conflict_409(self, client):
        client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "a"})
        client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "b"})
        resp = client.post("/api/v1/workspace/alpha/files/move", json={
            "source": "a", "path": "b", "overwrite": False})
        assert resp.status_code == 409
        resp_ok = client.post("/api/v1/workspace/alpha/files/move", json={
            "source": "a", "path": "b", "overwrite": True})
        assert resp_ok.status_code == 200

    def test_zip_download(self, client, tmp_path):
        client.post("/api/v1/workspace/alpha/files/mkdir", json={"path": "pkg"})
        root = tmp_path / "agent_workspaces" / "alpha"
        _write_file(root, "pkg/data.txt", "payload")
        resp = client.get("/api/v1/workspace/alpha/files/zip", params={"subdir": "pkg"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert "data.txt" in zf.namelist()
            assert zf.read("data.txt") == b"payload"
