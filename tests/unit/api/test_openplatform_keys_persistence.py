# -*- coding: utf-8 -*-
"""开放平台 API key 持久化 + 创建幂等 + 撤销防重放（Yuxi 对比 P2 #12）。

根因：/v1/openplatform 端点用模块级内存 `_KEYS_STORE`——**重启即全丢**
（假保存族；仓库另有 api_key_manager.py 孤岛库但无生产消费方）。
对位 Yuxi api_key_repository：创建幂等（creation_request_id + intent 指纹）、
撤销保留 tombstone 拒绝同 request_id 复活重放、DB 只存哈希（已有不降）。
"""
import json

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.api.endpoints import openplatform_keys as opk


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "openplatform_keys.json"
    monkeypatch.setenv("NEUROVA_OPENPLATFORM_KEYS_DB", str(db))
    opk.reset_openplatform_keys_store()
    app = create_app(enable_memory=False, enable_channels=False)
    # 该路由挂在 neurova.api.auth.get_current_user（非 api.deps 同名物）——
    # override 必须打在真实依赖对象上
    from neurova.api import auth as auth_mod

    app.dependency_overrides[auth_mod.get_current_user] = lambda: {
        "user_id": "keyowner",
        "username": "keyowner",
    }
    c = TestClient(app)
    c._keys_db = db  # 供用例直读文件
    yield c
    opk.reset_openplatform_keys_store()


def _create(client, **over):
    body = {"name": "ci-key", "scopes": ["read"], "expires_in_days": 30}
    body.update(over)
    return client.post("/api/v1/openplatform/", json=body)


def test_created_key_survives_restart(client):
    r = _create(client)
    assert r.status_code == 200
    kid = r.json()["data"]["id"]
    assert client._keys_db.exists(), "必须落盘（当前内存 dict 的根因即此）"
    persisted = json.loads(client._keys_db.read_text(encoding="utf-8"))
    assert kid in persisted
    assert "key_hash" in persisted[kid] and persisted[kid]["key_hash"] != kid
    # 模拟重启：清进程态重新装载
    opk.reset_openplatform_keys_store()
    lst = client.get("/api/v1/openplatform/").json()["data"]["items"]
    assert [k["id"] for k in lst] == [kid]
    assert client.get(f"/api/v1/openplatform/{kid}").status_code == 200


def test_creation_idempotent_by_request_id(client):
    r1 = _create(client, creation_request_id="req-abc")
    r2 = _create(client, creation_request_id="req-abc")
    assert r1.status_code == 200 and r2.status_code == 200
    d1, d2 = r1.json()["data"], r2.json()["data"]
    assert d1["id"] == d2["id"], "同 request_id 不得产生第二把密钥"
    assert "key" in d1 and d1.get("replayed") is not True
    assert d2.get("replayed") is True and "key" not in d2, "重放不得再吐明文"


def test_same_request_id_different_intent_rejected(client):
    assert _create(client, creation_request_id="req-x").status_code == 200
    r = _create(client, creation_request_id="req-x", name="totally-different")
    assert r.status_code == 409, "同 request_id 不同创建意图 = 客户端 bug，必须显式拒绝"


def test_revoked_tombstone_blocks_replay(client):
    kid = _create(client, creation_request_id="req-y").json()["data"]["id"]
    assert client.post(f"/api/v1/openplatform/{kid}/revoke").status_code == 200
    r = _create(client, creation_request_id="req-y")
    assert r.status_code == 409, "撤销后同请求重放不得复活凭据（Yuxi tombstone 语义）"
    # 撤销行保留（tombstone，不物理删）
    persisted = json.loads(client._keys_db.read_text(encoding="utf-8"))
    assert kid in persisted and persisted[kid]["revoked"] is True


def test_corrupt_store_file_backed_up_not_silent(tmp_path, monkeypatch):
    db = tmp_path / "keys.json"
    db.write_text("{{{ not json", encoding="utf-8")
    monkeypatch.setenv("NEUROVA_OPENPLATFORM_KEYS_DB", str(db))
    opk.reset_openplatform_keys_store()
    opk._ensure_loaded()
    # 损坏原件被 rename 走（留证），库空载可继续用
    assert not db.exists()
    backups = list(tmp_path.glob("keys.json.corrupt-*"))
    assert backups, "损坏文件必须留证（禁止静默清空）"
    assert backups[0].read_text(encoding="utf-8") == "{{{ not json"
