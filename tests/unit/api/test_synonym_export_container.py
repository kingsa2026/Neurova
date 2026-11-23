# -*- coding: utf-8 -*-
"""同义词导入/导出路径 containment 守卫（CodeQL py/path-injection 处置）。

/save 与 /load 的 file_path 原先直达任意路径读写（认证用户可覆盖数据根下
任意 JSON、可探测任意文件存在性）。修复后路径必须位于数据根的
synonym_exports 导出目录内；目录内的导出/导回 round-trip 照常可用。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import synonym_api


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(synonym_api.router, prefix="/synonyms")
    app.dependency_overrides[synonym_api.get_current_user] = lambda: {
        "user_id": "u-syn", "username": "syn", "role": "user"}
    return TestClient(app)


def test_save_outside_export_dir_is_refused(client, tmp_path):
    evil = tmp_path / "evil.json"
    resp = client.post("/synonyms/save", params={"file_path": str(evil)})
    assert resp.status_code == 400, resp.text
    assert "导出目录" in resp.json().get("detail", "")


def test_load_outside_export_dir_is_refused(client, tmp_path):
    evil = tmp_path / "evil.json"
    evil.write_text('{"word": ["x"]}', encoding="utf-8")
    resp = client.post("/synonyms/load", params={"file_path": str(evil)})
    assert resp.status_code == 400, resp.text
    assert "导出目录" in resp.json().get("detail", "")


def test_roundtrip_inside_export_dir_works(client):
    base = synonym_api._exportBase()
    target = base / "exported.json"
    resp = client.post("/synonyms/save", params={"file_path": str(target)})
    assert resp.status_code == 200, resp.text
    assert target.exists(), "目录内的导出必须照常落盘"

    # 造一个合法导出文件再导回
    target.write_text(json.dumps({"词": ["同义"]}), encoding="utf-8")
    resp = client.post("/synonyms/load", params={"file_path": str(target)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
