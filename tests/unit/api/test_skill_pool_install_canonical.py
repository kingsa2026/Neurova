"""
TDD Red: 技能安装 404 修复（2026-09-09）

根因: SkillMarketPage「安装」按钮 → skillPoolApi.installSkill →
POST /v1/skill-pool/{skill_id}/install —— 该路由在 skill_pool_api.py
**不存在**（只有 /public/{skill_id}/install），恒 404。ADR 0013 把
读侧（列表/详情）收敛到 marketplace catalog 同源时漏迁写侧。

同时 /v1/skill-pool/public/{skill_id}/install 是僵尸端点：查无人填充的
内存 dict _public_skills，且安装只改内存不落盘，与 marketplace
canonical 安装链路（catalog → 下载导入 → 联邦注册）脱节。

契约锁定:
1. skill-pool 前缀的 POST /{skill_id}/install 必须存在且委托 canonical
   安装链路（market_store 命中 → 200；未命中 → 404 带 detail）；
2. /public/{skill_id}/install 同样委托 canonical（不再读僵尸 dict）；
3. agent_id 经请求体透传（联邦注册按目标 agent 落盘）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api
from neurova.api.deps import get_current_user
from neurova.skills.market_store import reset_market_store

USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
BASE = "/api/v1/skill-pool"

CATALOG_ENTRY = {
    "skill_id": "web-search",
    "name": "Web Search",
    "version": "1.0.0",
    "description": "Search the web",
    "author": "neurova",
    "download_url": "",
    "category": "utility",
    "tags": [],
    "rating": 4.5,
    "downloads": 100,
    "source": "builtin",
}


def _ensure_catalog_has_web_search() -> None:
    """内置技能包会自动种子 web-search；仅在缺失时补种（只补缺不覆盖）。"""
    from neurova.skills.market_store import get_market_store

    if get_market_store().get("web-search") is None:
        get_market_store().create(CATALOG_ENTRY)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    reset_market_store()

    a = FastAPI()
    a.include_router(skill_pool_api.router, prefix=BASE)
    with TestClient(a, raise_server_exceptions=False) as c:
        c.app.dependency_overrides[get_current_user] = lambda: USER
        yield a, c

    reset_market_store()


class TestInstallUnderSkillPoolPrefix:
    def test_install_delegates_to_canonical_chain(self, app):
        """POST /skill-pool/{id}/install 必须走 canonical 安装链（catalog 命中 → 200）"""
        _, c = app
        _ensure_catalog_has_web_search()

        resp = c.post(f"{BASE}/web-search/install", json={"agent_id": "default"})
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["code"] == 0, body

    def test_install_unknown_skill_returns_404_with_detail(self, app):
        """catalog 未命中的技能 404（canonical 行为），而非僵尸 dict 的无差别 404"""
        _, c = app
        resp = c.post(f"{BASE}/no-such-skill/install", json={"agent_id": "default"})
        assert resp.status_code == 404, resp.text[:200]
        assert "not found" in resp.json().get("detail", "").lower()

    def test_public_install_also_delegates(self, app):
        """旧前缀 /public/{id}/install 保留但委托 canonical（不再读僵尸 _public_skills）"""
        _, c = app
        _ensure_catalog_has_web_search()

        resp = c.post(f"{BASE}/public/web-search/install", json={"agent_id": "default"})
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()["code"] == 0, resp.json()


class TestUninstallAgentIdPassthrough:
    def test_uninstall_accepts_agent_id_query(self, app, tmp_path, monkeypatch):
        """DELETE /marketplace/skills/{id}/install 须接受 agent_id Query 并透传联邦注销。

        回归背景：SkillMarketPage 卸载分支原走 /skill-pool/private/{id}/push
        （取消推送语义，对市场技能假成功不落盘）。
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neurova.api.endpoints import marketplace
        from neurova.api.deps import get_current_user as _gcu

        monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog2.json"))
        reset_market_store()

        a = FastAPI()
        a.include_router(marketplace.router, prefix="/api/v1/marketplace")
        with TestClient(a, raise_server_exceptions=False) as c:
            c.app.dependency_overrides[_gcu] = lambda: USER

            # 未安装 → canonical 404（证明请求确实进入 canonical 卸载链，
            # 而不是被别处吞掉）
            r = c.delete("/api/v1/marketplace/skills/no-such/install", params={"agent_id": "default"})
            assert r.status_code == 404, r.text[:200]
            assert "not installed" in r.json().get("detail", "").lower()

        reset_market_store()
