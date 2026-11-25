# -*- coding: utf-8 -*-
"""PLUG-03（2026-11-25 全仓审计·批次C）：技能版本更新写操作越权。

审计实形（以当前代码复核）：`skill_version_api` 路由只挂 router 级登录门，
`POST /update`、`/auto-update`、`/sync-from-public` 三个写端点任何登录用户
可调，经 `MarketImporter.import_skill(force=True)` 重装**全局共享**的
`data/skills`（`get_market_importer` 单例，全部 agent 共用一份安装根）——
等于任何登录用户都能改全局技能资产。写口收口到仓内既有属主/管理员单源门
`requireAgentOwner`（与 marketplace install_skill 同一判据，教义第 6 条）；
读面（check / check-all / notifications / startup-check）维持登录即可。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_version_api
from tests.auth_headers import overrideIdentity

BASE = "/api/v1/skill-versions"
USER = {"user_id": "7", "username": "alice", "role": "user", "neuser_id": "7"}
ADMIN = {"user_id": "9", "username": "root", "role": "admin", "neuser_id": "9"}

WRITE_ENDPOINTS = [
    ("POST", f"{BASE}/update"),
    ("POST", f"{BASE}/auto-update"),
    ("POST", f"{BASE}/sync-from-public"),
]
# 这三个端点的 `request` 形参无类型标注，FastAPI 按必填 query 参数处理——
# 既有契约原样保留，用例带一个空值过 422，才能打到真实处理逻辑。
REQ_PARAMS = {"request": ""}


def _call(client, method, url, **kw):
    return client.request(method, url, params=REQ_PARAMS, **kw)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from neurova.skills import library_service as lib
    from neurova.skills.market_importer import reset_market_importer

    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path))
    lib.reset_libraries_for_tests()
    reset_market_importer()
    import neurova.skills.market_store as ms

    monkeypatch.setattr(
        ms, "get_market_store",
        lambda: ms.MarketStore(catalog_path=tmp_path / "catalog.json"),
    )

    app = FastAPI()
    app.include_router(skill_version_api.router, prefix=BASE)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    reset_market_importer()
    lib.reset_libraries_for_tests()


@pytest.mark.parametrize("method,url", WRITE_ENDPOINTS)
def test_write_endpoints_reject_non_admin(method, url, client):
    """非管理员调写端点 → 403（修复前：200 并真实触发全局重装）。"""
    overrideIdentity(client.app, USER)
    r = _call(client, method, url, json={"skill_id": "any-skill"})
    assert r.status_code == 403, (
        f"{method} {url} 非管理员应 403，实际 {r.status_code}: {r.text[:160]}")


@pytest.mark.parametrize("method,url", WRITE_ENDPOINTS)
def test_write_endpoints_still_require_login(method, url, client):
    """未登录 → 401（router 级登录门保持）。"""
    r = _call(client, method, url, json={"skill_id": "any-skill"})
    assert r.status_code == 401, (
        f"{method} {url} 未登录应 401，实际 {r.status_code}: {r.text[:160]}")


@pytest.mark.parametrize("method,url", WRITE_ENDPOINTS)
def test_admin_passes_write_gate(method, url, client, monkeypatch):
    """管理员放行（反向控制格：门不得把管理员一起锁死）。"""
    overrideIdentity(client.app, ADMIN)
    monkeypatch.setattr(
        skill_version_api, "_run_update",
        lambda skill_id, target: {"ok": True, "new_version": "9.9.9"})
    r = _call(client, method, url, json={"skill_id": "any-skill"})
    assert r.status_code == 200, r.text
    assert r.json().get("code") == 0, r.text


def test_default_agent_owner_passes_write_gate(client, monkeypatch):
    """属主语义：default agent 的属主本人可更新（requireAgentOwner 单源判据）。"""
    overrideIdentity(client.app, USER)
    import neurova.api.agent_access as aa

    monkeypatch.setattr(aa, "agentOwnerById", lambda agent_id: "7")
    monkeypatch.setattr(
        skill_version_api, "_run_update",
        lambda skill_id, target: {"ok": True, "new_version": "9.9.9"})
    r = _call(client, "POST", f"{BASE}/update", json={"skill_id": "any-skill"})
    assert r.status_code == 200, r.text
    assert r.json().get("code") == 0, r.text


def test_non_owner_non_admin_rejected_even_if_agent_owned(client, monkeypatch):
    """default agent 属主是别人时，普通用户仍 403（owner 判据不是摆设）。"""
    overrideIdentity(client.app, USER)
    import neurova.api.agent_access as aa

    monkeypatch.setattr(aa, "agentOwnerById", lambda agent_id: "999")
    r = _call(client, "POST", f"{BASE}/update", json={"skill_id": "any-skill"})
    assert r.status_code == 403, r.text


def test_read_endpoints_stay_login_only(client):
    """读面维持登录即可（反向控制格：收口只落在写端点）。"""
    overrideIdentity(client.app, USER)
    assert client.post(f"{BASE}/check-all").status_code == 200
    # notifications 的 `request` 形参同为无标注 query 参数（既有契约），带空值过 422
    assert client.get(f"{BASE}/notifications", params={"request": ""}).status_code == 200
