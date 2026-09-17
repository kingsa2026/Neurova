# -*- coding: utf-8 -*-
"""知识摄取异步链路（P1 #9）：worker 判定 + 端点契约。

契约：sync=false 入队即返（文件落暂存）；GET 任务状态（本人可见，他人 404
不泄露存在性）；done 附 item_ids；确定性失败直入 dead；sync=true 行为不降。
"""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.knowledge import ingest_queue as iq
from neurova.knowledge.ingest_worker import process_ingress_event


# ── worker 纯判定 ─────────────────────────────────────────────────

def test_worker_upload_done(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"content")
    ev = {"source": "upload", "storage_path": str(f), "filename": "a.txt",
          "agent_id": "ag", "user_id": "u1"}
    out = process_ingress_event(
        ev,
        importer=lambda data, fn, ag, user: ([{"knowledge_id": "k1"}], "ok"),
    )
    assert out["ok"] and out["item_ids"] == ["k1"]
    assert out["graph"] == "skipped_async"


def test_worker_extract_failed_no_retry(tmp_path):
    f = tmp_path / "a.ppt"
    f.write_bytes(b"x")
    ev = {"source": "upload", "storage_path": str(f), "filename": "a.ppt", "agent_id": "ag", "user_id": "u"}
    out = process_ingress_event(ev, importer=lambda d, fn, ag, u: ([], "unsupported_format"))
    assert out["ok"] is False and out["retry"] is False
    assert "extract_failed" in out["error"]


def test_worker_missing_file(tmp_path):
    ev = {"source": "upload", "storage_path": str(tmp_path / "gone"), "filename": "a", "agent_id": "ag", "user_id": "u"}
    out = process_ingress_event(ev, importer=lambda *a: ([{"knowledge_id": "x"}], "ok"))
    assert out["ok"] is False and out["status"] == "file_missing"


# ── 端点契约 ──────────────────────────────────────────────────────

@pytest.fixture()
def env(tmp_path, monkeypatch):
    queue = iq.KnowledgeIngressQueue(tmp_path / "ingress.db", files_dir=tmp_path / "files")
    monkeypatch.setattr(iq, "_queue", queue)
    app = FastAPI()
    from neurova.api.endpoints import knowledge as kn
    from neurova.api.auth import get_current_user_or_service

    app.dependency_overrides[get_current_user_or_service] = lambda: {"user_id": "u1", "role": "user"}
    app.include_router(kn.router, prefix="/api/v1/knowledge")
    client = TestClient(app)
    yield client, queue, monkeypatch
    queue.close()
    iq._queue = None


def test_import_async_returns_task_and_stages_file(env):
    client, queue, _ = env
    r = client.post(
        "/api/v1/knowledge/import?agent_id=ag&sync=false",
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "pending" and data["task_id"]
    row = queue.get(data["task_id"])
    from pathlib import Path

    assert Path(row["storage_path"]).exists()


def test_import_sync_default_unchanged(env, monkeypatch):
    """sync 缺省=现行为（只提升不下降）：仍走 _import_file_data 返回 items。"""
    client, queue, _ = env
    from neurova.api.endpoints import knowledge_ingestion as kn_ingestion

    # 拆分后真身在 knowledge_ingestion（2026-09-16 模块化），patch 聚合器无效
    monkeypatch.setattr(
        kn_ingestion, "_import_file_data",
        lambda data, fn, ag, user: ([{"knowledge_id": "k1", "content": "x"}], "ok"),
    )
    r = client.post("/api/v1/knowledge/import?agent_id=ag", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0 and body["data"]["items"][0]["knowledge_id"] == "k1"


def test_task_status_endpoints_owner_scoped(env):
    client, queue, _ = env
    t = queue.enqueue_upload("a.txt", b"x", "ag", "u1")
    tid = t["task_id"]
    r = client.get(f"/api/v1/knowledge/ingress-tasks/{tid}")
    assert r.status_code == 200 and r.json()["data"]["status"] == "pending"
    assert "storage_path" not in r.json()["data"]  # 绝对路径不外露
    # 他人不可见（不泄露存在性）
    from fastapi import FastAPI

    other = queue.enqueue_upload("b.txt", b"y", "ag", "u2")
    assert client.get(f"/api/v1/knowledge/ingress-tasks/{other['task_id']}").status_code == 404
    lst = client.get("/api/v1/knowledge/ingress-tasks").json()["data"]
    assert {x["task_id"] for x in lst["tasks"]} == {tid}
    assert lst["stats"]["pending"] == 2  # stats 是全局观测面


def test_drain_roundtrip_end_to_end(env, monkeypatch):
    """入队 → 直接手动走一轮 claim+process+ack → 任务 done + item_ids + 文件清理。"""
    client, queue, _ = env
    from neurova.api.endpoints import knowledge as kn

    monkeypatch.setattr(kn, "_import_file_data", lambda d, fn, ag, u: ([{"knowledge_id": "kZ"}], "ok"))
    r = client.post("/api/v1/knowledge/import?sync=false", files={"file": ("z.txt", b"zz", "text/plain")})
    tid = r.json()["data"]["task_id"]
    ev = queue.claim("w")
    out = process_ingress_event(ev, importer=kn._import_file_data)
    queue.ack(tid, out["item_ids"])
    got = client.get(f"/api/v1/knowledge/ingress-tasks/{tid}").json()["data"]
    assert got["status"] == "done"
    assert got["item_ids"] == ["kZ"]
    from pathlib import Path

    assert not Path(ev["storage_path"]).exists()
