"""
市场远端源同步端点测试（2026-08-31）

契约:
1. POST /marketplace/sync 仅 admin（未认证 401 / 用户 403 / admin 200）;
2. 未知 source 400;
3. sync 后 catalog 带 source 条目，浏览/详情端点透出 source 字段;
4. 本地条目 source 默认 "local";
5. 上游失败降级为 errors 计数，端点仍 200。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import marketplace
from neurova.api.deps import get_current_user
from neurova.skills.market_store import reset_market_store

MOCK_USER = {"user_id": "u1", "username": "user1", "role": "user"}
MOCK_ADMIN = {"user_id": "admin1", "username": "adminuser", "role": "admin"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    reset_market_store()
    a = FastAPI()
    a.include_router(marketplace.router, prefix="/api/v1/marketplace")
    with TestClient(a, raise_server_exceptions=False) as c:
        yield a, c
    reset_market_store()


def _auth(c, role):
    user = MOCK_ADMIN if role == "admin" else MOCK_USER
    c.app.dependency_overrides[get_current_user] = lambda: user
    return c


def _fake_sync(monkeypatch, result=None):
    """把 market_sources.sync_source 换成假实现（不打真网）"""
    from neurova.skills import market_sources as ms

    calls = []

    def fake(source_key, store):
        calls.append(source_key)
        store.create(
            {
                "skill_id": f"{source_key}--demo",
                "source": source_key,
                "name": "Demo",
                "description": "远端同步条目",
                "author": source_key,
                "version": "1.0.0",
                "category": "agent",
                "tags": [],
                "downloads": 12,
                "rating": 0.0,
                "download_url": "https://skills.aliyun.com/api/public/skills/demo/download",
                "updated_at": 0,
            }
        )
        return result or {"source": source_key, "created": 1, "updated": 0, "removed": 0, "errors": 0}

    monkeypatch.setattr(ms, "sync_source", fake)
    return calls


class TestSyncEndpoint:
    def test_unauthorized_401(self, app):
        a, c = app
        assert c.post("/api/v1/marketplace/sync").status_code == 401

    def test_user_forbidden_403(self, app):
        a, c = app
        _auth(c, "user")
        assert c.post("/api/v1/marketplace/sync").status_code == 403

    def test_admin_sync_all(self, app, monkeypatch):
        a, c = app
        _auth(c, "admin")
        calls = _fake_sync(monkeypatch)
        r = c.post("/api/v1/marketplace/sync")
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["code"] == 0
        assert set(calls) == {"aliyun", "xfyun"}
        # 同步条目进入浏览列表且带 source
        skills = c.get("/api/v1/marketplace/skills").json()
        sources = {s["skill_id"]: s["source"] for s in skills}
        assert sources.get("aliyun--demo") == "aliyun"
        assert sources.get("web-search") == "local"

    def test_admin_sync_single_source(self, app, monkeypatch):
        a, c = app
        _auth(c, "admin")
        calls = _fake_sync(monkeypatch)
        r = c.post("/api/v1/marketplace/sync?source=aliyun")
        assert r.status_code == 200
        assert calls == ["aliyun"]

    def test_unknown_source_400(self, app):
        a, c = app
        _auth(c, "admin")
        assert c.post("/api/v1/marketplace/sync?source=nope").status_code == 400

    def test_upstream_failure_still_200(self, app, monkeypatch):
        a, c = app
        _auth(c, "admin")
        from neurova.skills import market_sources as ms

        monkeypatch.setattr(
            ms, "sync_source",
            lambda k, s: {"source": k, "created": 0, "updated": 0, "removed": 0, "errors": 1},
        )
        r = c.post("/api/v1/marketplace/sync?source=aliyun")
        assert r.status_code == 200
        assert r.json()["data"]["results"][0]["errors"] == 1

    def test_detail_exposes_source(self, app, monkeypatch):
        a, c = app
        _auth(c, "admin")
        _fake_sync(monkeypatch)
        c.post("/api/v1/marketplace/sync?source=xfyun")
        r = c.get("/api/v1/marketplace/skills/xfyun--demo")
        assert r.status_code == 200
        assert r.json()["source"] == "xfyun"
