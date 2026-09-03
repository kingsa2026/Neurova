"""
市场来源筛选 + 分页信封测试（2026-08-31）

契约:
1. GET /skills?source=aliyun 只返回该来源条目; source=local 返回本地（含无 source 字段的种子）;
2. GET /skills?with_total=true 返回 {items, total} 信封（默认仍为裸数组，兼容旧契约）;
3. source + with_total 组合可用; offset/limit 分页切片正确;
4. 未知 source 返回空列表（而非报错）。
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


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    reset_market_store()
    a = FastAPI()
    a.include_router(marketplace.router, prefix="/api/v1/marketplace")
    with TestClient(a, raise_server_exceptions=False) as c:
        # 种子: 2 local + 2 aliyun + 3 xfyun
        from neurova.skills.market_store import get_market_store

        store = get_market_store()
        for sid, src in [
            ("aliyun--a1", "aliyun"),
            ("aliyun--a2", "aliyun"),
            ("xfyun--x1", "xfyun"),
            ("xfyun--x2", "xfyun"),
            ("xfyun--x3", "xfyun"),
        ]:
            store.create(
                {
                    "skill_id": sid, "source": src, "name": sid, "description": "d",
                    "author": src, "version": "1.0.0", "category": "agent",
                    "tags": [], "downloads": 1, "rating": 0.0,
                    "download_url": "https://skills.aliyun.com/api/public/skills/x/download",
                    "updated_at": 0,
                }
            )
        yield a, c
    reset_market_store()


def _auth(c):
    c.app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    return c


class TestSourceFilter:
    def test_filter_aliyun(self, app):
        a, c = app
        _auth(c)
        skills = c.get("/api/v1/marketplace/skills?source=aliyun").json()
        assert isinstance(skills, list)
        assert {s["skill_id"] for s in skills} == {"aliyun--a1", "aliyun--a2"}
        assert all(s["source"] == "aliyun" for s in skills)

    def test_filter_local_includes_seeds(self, app):
        a, c = app
        _auth(c)
        skills = c.get("/api/v1/marketplace/skills?source=local").json()
        ids = {s["skill_id"] for s in skills}
        assert {"web-search", "code-analysis"} <= ids
        assert all(s["source"] == "local" for s in skills)

    def test_filter_xfyun(self, app):
        a, c = app
        _auth(c)
        skills = c.get("/api/v1/marketplace/skills?source=xfyun").json()
        assert {s["skill_id"] for s in skills} == {"xfyun--x1", "xfyun--x2", "xfyun--x3"}

    def test_unknown_source_empty(self, app):
        a, c = app
        _auth(c)
        assert c.get("/api/v1/marketplace/skills?source=nope").json() == []

    def test_no_filter_returns_all(self, app):
        a, c = app
        _auth(c)
        skills = c.get("/api/v1/marketplace/skills").json()
        assert len(skills) == 7  # 2 种子 + 5 远端


class TestPaginationEnvelope:
    def test_with_total_envelope(self, app):
        a, c = app
        _auth(c)
        body = c.get("/api/v1/marketplace/skills?source=xfyun&with_total=true").json()
        assert isinstance(body, dict)
        assert body["total"] == 3
        assert {s["skill_id"] for s in body["items"]} == {"xfyun--x1", "xfyun--x2", "xfyun--x3"}

    def test_offset_limit_slice(self, app):
        a, c = app
        _auth(c)
        body = c.get("/api/v1/marketplace/skills?source=xfyun&with_total=true&offset=1&limit=1").json()
        assert body["total"] == 3
        assert len(body["items"]) == 1
        assert body["items"][0]["skill_id"] == "xfyun--x2"

    def test_default_still_bare_list(self, app):
        a, c = app
        _auth(c)
        skills = c.get("/api/v1/marketplace/skills").json()
        assert isinstance(skills, list)  # 旧契约不破坏
