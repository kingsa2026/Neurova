"""growth 域拆分后路由完备性契约（2026-09-16 模块化重构回归钉）。

growth.py 由单文件拆为聚合器 + 子路由模块（personality_router /
constitution_router），本文件钉死两条不变量：
1. 全部 23 条路由拆分后仍可路由（拆分不得丢路由）；
2. 拆分是纯结构迁移：每条路由路径与方法集逐一对应。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_growth_routes_012345")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import growth as growth_api

# 拆分前 growth.py 的 23 条路由快照（路径, 方法）——FastAPI 每个装饰器一条记录，
# 拆分后必须逐一保持（23 条即全部 @router 装饰器）
_EXPECTED_ROUTES = {
    ("", "GET"),
    ("/capabilities", "GET"),
    ("/reflection", "GET"), ("/reflection", "POST"),
    ("/reflection/stats", "GET"),
    ("/questions", "GET"), ("/questions", "POST"),
    ("/questions/next", "GET"),
    ("/questions/{question_id}/answer", "PUT"),
    ("/proactive", "GET"), ("/proactive", "POST"),
    ("/motivation", "GET"), ("/motivation", "PUT"),
    ("/personality", "GET"), ("/personality", "PUT"),
    ("/personality/traits", "GET"),
    ("/personality/evolve", "POST"),
    ("/constitution", "GET"), ("/constitution", "PUT"),
    ("/constitution/rules", "GET"), ("/constitution/rules", "POST"),
    ("/constitution/rules/{rule_id}", "PUT"), ("/constitution/rules/{rule_id}", "DELETE"),
}


def _router_routes(router):
    """收集 (相对路径, 方法)——raw router 路径即相对路径，每条装饰器一条记录"""
    out = set()
    for r in router.routes:
        m = getattr(r, "methods", None)
        p = getattr(r, "path", "")
        if m and not p.startswith(("/openapi", "/docs")):
            for method in m - {"HEAD", "OPTIONS"}:
                out.add((p, method))
    return out


def test_all_23_routes_live_after_split():
    """拆分后聚合 router 必须仍暴露全部 23 条路由（丢路由即红）"""
    assert _router_routes(growth_api.router) == _EXPECTED_ROUTES


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import types

    monkeypatch.setattr(growth_api, "_PERSONALITY_DIR", str(tmp_path / "personality"))
    monkeypatch.setattr(growth_api, "_CONSTITUTION_DIR", str(tmp_path / "constitution"))
    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance",
                        lambda agent_id="default", *a, **k: types.SimpleNamespace(
                            personality="", constitution=""))
    app = FastAPI()
    app.include_router(growth_api.router, prefix="/api/v1/growth")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/growth/personality"),
    ("put", "/api/v1/growth/personality"),
    ("get", "/api/v1/growth/personality/traits"),
    ("post", "/api/v1/growth/personality/evolve"),
    ("get", "/api/v1/growth/constitution"),
    ("put", "/api/v1/growth/constitution"),
    ("get", "/api/v1/growth/constitution/rules"),
    ("post", "/api/v1/growth/constitution/rules"),
])
def test_personality_constitution_routes_not_404(client, method, path):
    """子模块路由经聚合仍可路由：405/422/200 都行，404 不可接受"""
    r = getattr(client, method)(path, params={"agent_id": "a1"},
                                **({"json": {}} if method in {"put", "post"} else {}))
    assert r.status_code != 404, f"{method.upper()} {path} 拆分后丢失路由"
