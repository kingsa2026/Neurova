"""
Marketplace API 注册回归测试（2026-08-31）

根因：前端 MarketplacePage 请求 GET /api/v1/marketplace/skills → 404。
  neurova/api/endpoints/marketplace.py（/skills、/skills/{id}/install、
  /installed 与前端契约 1:1）从未注册进 endpoints 注册表（__init__.py
  endpoint_modules 列表), 导致路由 404。模块文件存在于仓库多年。

契约：
1. marketplace 模块必须注册在 endpoint_modules（前缀 /v1/marketplace）——
   防止再被移除导致前台市场页 404;
2. 路由行为：GET /skills 返回 200 技能列表、GET /installed 200、
   GET /skills/{id} 200 或 503(导入器不可用时)。
"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import marketplace


def _load_endpoints_init() -> str:
    p = Path(__file__).resolve()
    # tests/unit/api → 仓库根
    root = p.parents[3]
    return (root / "neurova" / "api" / "endpoints" / "__init__.py").read_text(
        encoding="utf-8"
    )


class TestMarketplaceRegistered:
    def test_marketplace_in_endpoint_registry(self):
        src = _load_endpoints_init()
        assert "neurova.api.endpoints.marketplace" in src
        assert '"/v1/marketplace"' in src

    def test_marketplace_router_contract(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
        from neurova.skills.market_store import reset_market_store

        reset_market_store()
        app = FastAPI()
        app.include_router(marketplace.router, prefix="/api/v1/marketplace")
        # 2026-08-31 收紧: 市场端点须登录(读) — 认证后走完整契约
        from neurova.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u1", "username": "user1", "role": "user",
        }
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/v1/marketplace/skills")
            assert r.status_code == 200, r.text[:160]
            body = r.json()
            assert isinstance(body, list), body
            r2 = c.get("/api/v1/marketplace/installed")
            assert r2.status_code == 200, r2.text[:160]
            r3 = c.get("/api/v1/marketplace/skills/web-search")
            # 导入器可用时 200; 不可用时 503 (服务未提供)
            assert r3.status_code in (200, 503), r3.text[:160]
        reset_market_store()
