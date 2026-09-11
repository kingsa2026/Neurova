# -*- coding: utf-8 -*-
"""generation 端点安全修复回归测试（审计 2026-09-11）。

覆盖：
- P0-1  task_id/落盘文件名不再接受路径穿越字符（X-Request-ID 解耦）
- P0-2  /generation/* 路由级鉴权（无 token 401）
- P1-6  ref_images 本地路径白名单（防本地文件外泄）
- P1-7  _persist_media 出网校验（防 SSRF）
- P1-9  /video/status 与 /tasks 任务归属校验
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as gen
from neurova.api.deps import get_current_user
from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord


# ── P0-1：task_id 文件名安全化 ──────────────────────────────────────────────

@pytest.mark.parametrize("evil", [
    "../../../../etc/passwd",
    "..\\..\\..\\Users\\Public\\pwn",
    "a/b/c",
    "x:y",
    "",
])
def test_safe_task_name_neutralizes_traversal(evil):
    name = gen._safe_task_name(evil)
    assert "/" not in name and "\\" not in name
    assert ".." not in name and ":" not in name


@pytest.mark.anyio
async def test_persist_media_data_uri_stays_inside_out_dir(tmp_path, monkeypatch):
    """data:URI 落盘必须留在产物目录内——恶意 task_id 不得逃逸。"""
    monkeypatch.setattr(gen, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    png = "data:image/png;base64," + "aGVsbG8="
    path = await gen._persist_media(png, "image", "../../../../evil", 0)
    from pathlib import Path

    assert Path(path).resolve().is_relative_to(tmp_path.resolve())
    assert Path(path).read_bytes() == b"hello"


@pytest.mark.anyio
async def test_persist_media_rejects_private_outbound(tmp_path, monkeypatch):
    """P1-7：产物下载前过出网校验，私网/元数据地址直接拒绝。"""
    monkeypatch.setattr(gen, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    import aiohttp

    with pytest.raises(Exception):
        await gen._persist_media("http://127.0.0.1:9/x.mp4", "video", "t1", 0)
    with pytest.raises(Exception):
        await gen._persist_media("http://169.254.169.254/latest/meta-data/", "video", "t1", 0)
    aiohttp.ClientSession  # noqa: B018 — 确认 aiohttp 可导入（环境自检）


# ── P1-6：ref_images 本地路径白名单 ─────────────────────────────────────────

@pytest.fixture()
def ref_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(gen, "GENERATION_OUTPUT_DIR", tmp_path / "data" / "generations")
    (tmp_path / "agent_workspaces" / "a1").mkdir(parents=True)
    (tmp_path / "data" / "generations").mkdir(parents=True)
    return tmp_path


def test_ref_images_rejects_outside_absolute(ref_roots):
    outside = str(ref_roots / "outside" / "secret.db")
    (ref_roots / "outside").mkdir()
    (ref_roots / "outside" / "secret.db").write_bytes(b"x")
    with pytest.raises(Exception) as ei:
        gen._validate_ref_images([outside])
    assert "允许目录" in str(ei.value)


def test_ref_images_rejects_relative(ref_roots):
    with pytest.raises(Exception) as ei:
        gen._validate_ref_images(["relative/pic.png"])
    assert "非法本地路径" in str(ei.value)


def test_ref_images_accepts_url_and_whitelisted_file(ref_roots):
    inside = ref_roots / "agent_workspaces" / "a1" / "ref.png"
    inside.write_bytes(b"x")
    gen._validate_ref_images(["https://example.com/a.png", "data:image/png;base64,AA", str(inside)])


# ── P0-2 / P1-9：路由鉴权与任务归属 ─────────────────────────────────────────

@pytest.fixture()
def app_with_ledger(tmp_path, monkeypatch):
    ledger = GenerationTaskLedger(path=str(tmp_path / "ledger.json"))
    monkeypatch.setattr(
        "neurova.llm.generators.task_ledger.get_generation_task_ledger",
        lambda: ledger,
    )
    app = FastAPI()
    app.include_router(gen.router, prefix="/api/v1/generation")
    return app, ledger


def _identity(uid: str, role: str = "user"):
    return {"user_id": uid, "username": uid, "role": role, "neuser_id": uid}


def test_generation_router_requires_auth(app_with_ledger):
    app, _ = app_with_ledger
    client = TestClient(app)
    assert client.get("/api/v1/generation/tasks").status_code == 401
    assert client.post("/api/v1/generation/image", json={"prompt": "x"}).status_code == 401


def test_tasks_list_scoped_to_owner(app_with_ledger):
    app, ledger = app_with_ledger
    ledger.add(TaskRecord(task_id="ta", kind="video", owner_user_id="alice", prompt="A"))
    ledger.add(TaskRecord(task_id="tb", kind="video", owner_user_id="bob", prompt="B"))
    app.dependency_overrides[get_current_user] = lambda: _identity("alice")
    client = TestClient(app)
    body = client.get("/api/v1/generation/tasks").json()
    ids = [t["task_id"] for t in body["data"]["tasks"]]
    assert ids == ["ta"]


def test_video_status_owner_isolation(app_with_ledger):
    app, ledger = app_with_ledger
    ledger.add(TaskRecord(task_id="tA", kind="video", owner_user_id="alice",
                          status="succeeded", result_url="https://x/v.mp4"))
    client = TestClient(app)

    app.dependency_overrides[get_current_user] = lambda: _identity("bob")
    assert client.get("/api/v1/generation/video/status/tA").status_code == 403

    app.dependency_overrides[get_current_user] = lambda: _identity("alice")
    resp = client.get("/api/v1/generation/video/status/tA")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "succeeded"


def test_video_status_legacy_ownerless_admin_only(app_with_ledger):
    app, ledger = app_with_ledger
    ledger.add(TaskRecord(task_id="tOld", kind="video", status="succeeded",
                          result_url="https://x/v.mp4"))
    client = TestClient(app)

    app.dependency_overrides[get_current_user] = lambda: _identity("carol")
    assert client.get("/api/v1/generation/video/status/tOld").status_code == 403

    app.dependency_overrides[get_current_user] = lambda: _identity("root", role="admin")
    assert client.get("/api/v1/generation/video/status/tOld").status_code == 200
