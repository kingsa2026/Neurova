# -*- coding: utf-8 -*-
"""开放平台 API key 持久化 + 创建幂等 + 撤销防重放。

根因（2026-09 那批）：`/v1/openplatform` 端点用模块级内存 `_KEYS_STORE`——重启即全丢
（假保存族）。当时的修法是自己再写一份 JSON 落盘实现。

合并批（2026-10-06，教义第 7 条）：仓内已有 `api_key_manager.APIKeyManager` 承担同一
功能且更强（DCL 单例、原子写、防抖落盘、有回归测试），于是把开放平台特有的三项机制
（创建幂等、意图指纹、撤销 tombstone）并入那一份实现，本模块改用它——**两套账收成一套**。
本文件的断言随之从"私有存储的文件形状"改指"管理器那一份存储"；被验的行为不变。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import openplatform_keys as opk

BASE = "/api/v1/openplatform"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "openplatform_keys.json"
    monkeypatch.setenv("NEUROVA_OPENPLATFORM_KEYS_DB", str(db))
    opk.reset_openplatform_keys_store()

    app = FastAPI()
    app.include_router(opk.router, prefix=BASE)
    # 该路由挂在 neurova.api.auth.get_current_user（非 api.deps 同名物）——
    # override 必须打在真实依赖对象上
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
    return client.post(f"{BASE}/", json=body)


def _persistedRecords(client):
    """真相源记录列表（管理器写的是 {"keys": [...]}，不再是扁平 dict）"""
    data = json.loads(client._keys_db.read_text(encoding="utf-8"))
    return {r["key_id"]: r for r in data.get("keys", [])}


def test_created_key_survives_restart(client):
    r = _create(client)
    assert r.status_code == 200
    kid = r.json()["data"]["id"]
    assert client._keys_db.exists(), "必须落盘（内存 dict 那版根因即此）"
    persisted = _persistedRecords(client)
    assert kid in persisted
    assert "key_hash" in persisted[kid] and persisted[kid]["key_hash"] != kid
    # 模拟重启：丢开进程内实例重新装载
    opk.reset_openplatform_keys_store()
    lst = client.get(f"{BASE}/").json()["data"]["items"]
    assert [k["id"] for k in lst] == [kid]
    assert client.get(f"{BASE}/{kid}").status_code == 200


def test_created_key_carries_the_openplatform_namespace(client):
    """命名空间是产品线标识：开放平台的明文密钥仍以 `nrv_` 开头（并入通用实现后不丢）"""
    data = _create(client).json()["data"]

    assert data["key"].startswith("nrv_"), f"密钥前缀丢了：{data['key'][:8]!r}"


def test_legacy_flat_store_is_still_loaded(client):
    """存量兼容：旧实现写的是扁平 `{key_id: {...}}`。合并不得把已签发的密钥读丢。"""
    created = _create(client).json()["data"]
    legacy = {created["id"]: {
        "id": created["id"],
        "name": "legacy-key",
        "key_hash": "deadbeef" * 8,
        "user_id": "keyowner",
        "scopes": ["read"],
        "enabled": True,
        "revoked": False,
        "created_at": created["created_at"],
        "expires_at": created["expires_at"],
    }}
    opk.reset_openplatform_keys_store()
    client._keys_db.write_text(json.dumps(legacy), encoding="utf-8")

    opk.get_openplatformKeyManager()  # 触发装载
    lst = client.get(f"{BASE}/").json()["data"]["items"]

    assert [k["id"] for k in lst] == [created["id"]], "扁平存量文件里的密钥被读丢了"
    assert lst[0]["name"] == "legacy-key"


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
    assert client.post(f"{BASE}/{kid}/revoke").status_code == 200
    r = _create(client, creation_request_id="req-y")
    assert r.status_code == 409, "撤销后同请求重放不得复活凭据（tombstone 语义）"
    # 撤销行保留（tombstone，不物理删）
    persisted = _persistedRecords(client)
    assert kid in persisted
    assert persisted[kid]["is_active"] is False
    assert persisted[kid]["revoked_at"], "撤销时间未入档"


def test_response_never_leaks_key_hash(client):
    """旧实现把整条记录直出（含 key_hash）。合并后对外面只给展示字段。"""
    created = _create(client).json()["data"]
    kid = created["id"]

    for face in (created, client.get(f"{BASE}/{kid}").json()["data"],
                 client.get(f"{BASE}/").json()["data"]["items"][0]):
        assert "key_hash" not in face, "响应仍带存储哈希"


def test_corrupt_store_file_backed_up_not_silent(tmp_path, monkeypatch):
    db = tmp_path / "keys.json"
    db.write_text("{{{ not json", encoding="utf-8")
    monkeypatch.setenv("NEUROVA_OPENPLATFORM_KEYS_DB", str(db))

    opk.reset_openplatform_keys_store()
    opk.get_openplatformKeyManager()  # 装载即触发损坏处理

    # 损坏原件被 rename 走（留证），库空载可继续用
    assert not db.exists()
    backups = list(tmp_path.glob("keys.json.corrupt-*"))
    assert backups, "损坏文件必须留证（禁止静默清空）"
    assert backups[0].read_text(encoding="utf-8") == "{{{ not json"


def test_private_store_is_retired(client):
    """第 7 条判据：该功能在仓内只剩一处实现被消费——私有存储不得还留着"""
    assert not hasattr(opk, "_KEYS_STORE"), "私有密钥表仍在：与 APIKeyManager 双头存储"
    assert not hasattr(opk, "_save_locked"), "第二套落盘实现仍在"
    assert not hasattr(opk, "_gen_key"), "第二套密钥生成仍在"
