# -*- coding: utf-8 -*-
"""P2-4 files_api 物理删除吞异常红测（全库断点审计 2026-11-12）。

缺陷：DELETE /files/{id} 先删记录（delete_file_record + _files_store.pop）
再 unlink，unlink 失败被 `except Exception: pass` 吞掉仍报成功——记录已删、
字节残留，重启后 hydrate 会"复活"无主文件。

修复口径（审计开方）：先 unlink 后删记录；unlink 失败＝删除失败，
保留记录并如实报错（不再吞）。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_files_delete_honest")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_files_delete_honest")

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import files_api


@pytest.fixture
def app(monkeypatch):
    application = FastAPI()
    application.include_router(files_api.router, prefix="/v1/files")
    application.dependency_overrides[files_api.get_current_user] = lambda: {
        "user_id": "u_owner", "username": "owner", "role": "user", "neuser_id": "ne_owner",
    }
    # 持久化面替身：本测试只判删除顺序与诚实性
    monkeypatch.setattr(files_api, "persist_file", lambda *a, **k: None)
    monkeypatch.setattr(files_api, "delete_file_record", lambda *a, **k: None)
    return application


@pytest.fixture
def owned_file(app):
    files_api._files_store.clear()
    files_api._files_store["f1"] = {
        "file_id": "f1", "user_id": "u_owner", "path": "/tmp/whatever.bin",
        "filename": "whatever.bin", "status": "ready",
    }
    yield "f1"
    files_api._files_store.clear()


def test_unlink_failure_keeps_record_and_reports(app, owned_file, monkeypatch):
    """unlink 失败：记录必须保留、响应必须如实失败（红态：吞异常报成功且记录已删）。"""

    def _boom(self, missing_ok=False):
        raise OSError("文件被占用（模拟 Windows 锁）")

    monkeypatch.setattr(Path, "unlink", _boom)
    client = TestClient(app)
    resp = client.delete("/v1/files/f1")
    assert resp.status_code >= 400, (
        f"unlink 失败必须如实报错，实得 {resp.status_code} {resp.json()}"
    )
    assert "f1" in files_api._files_store, (
        "unlink 失败后记录被删——重启 hydrate 会复活无主文件"
    )


def test_unlink_success_still_deletes(app, owned_file, monkeypatch):
    """正常路径不回归：unlink 成功 → 记录删除 → 200。"""
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: None)
    client = TestClient(app)
    resp = client.delete("/v1/files/f1")
    assert resp.status_code == 200
    assert "f1" not in files_api._files_store


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
