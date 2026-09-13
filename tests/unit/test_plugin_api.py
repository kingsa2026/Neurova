"""插件管理 API 测试（现行进程内 store 契约）

2026-09-13 残留处理：原文件基于 P7（2026-09-12）删除的 PluginManager 注入架构
（`_get_plugin_manager` patch 面），11 例全部 setup error。现行实现为
`_PLUGINS` 进程内字典 store（假样例注入已删，列表反映真实注册动作）——
本文件按现契约重写，端点覆盖意图保留：列表/状态/详情 404/安装/启停/加载
卸载/卸载/市场预留。fixture 每例清空全局 store（防套件间污染）。
"""

import sys
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.api.endpoints import plugin as plugin_module
from neurova.interfaces.api_standard import APIError


@pytest.fixture()
def client():
    app = FastAPI()

    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.http_status,
            json={"code": exc.code, "message": exc.message, "data": exc.data},
        )

    api_v1 = APIRouter(prefix="/api/v1")
    # 现行 plugin router 无自带 prefix（注册表挂载 "/v1/plugins"）
    api_v1.include_router(plugin_module.router, prefix="/plugins")
    app.include_router(api_v1)
    # router 级 Depends(get_current_user)（auth 面）——注入登录态
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "tester", "username": "tester", "role": "user"}
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u
    plugin_module._PLUGINS.clear()
    yield TestClient(app)
    plugin_module._PLUGINS.clear()


BASE = "/api/v1/plugins"


class TestPluginAPI:
    def test_list_plugins_empty(self, client):
        r = client.get(BASE + "/")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_plugins_with_filter(self, client):
        client.post(f"{BASE}/p1/install", json={"source": "local"})
        client.post(f"{BASE}/p2/install", json={"source": "local"})
        r = client.get(BASE + "/?status=disabled")
        assert r.json()["data"]["total"] == 2
        r2 = client.get(BASE + "/?status=enabled")
        assert r2.json()["data"]["total"] == 0

    def test_install_then_get(self, client):
        r = client.post(f"{BASE}/myplugin/install", json={"source": "local", "config": {"a": 1}})
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "myplugin"
        r2 = client.get(f"{BASE}/myplugin")
        assert r2.json()["data"]["config"] == {"a": 1}

    def test_get_plugin_not_found(self, client):
        assert client.get(f"{BASE}/ghost").status_code == 404

    def test_enable_disable_flow(self, client):
        client.post(f"{BASE}/p1/install", json={"source": "local"})
        r = client.post(f"{BASE}/p1/enable")
        assert r.json()["data"]["status"] == "enabled"
        assert r.json()["data"]["loaded"] is True
        r2 = client.post(f"{BASE}/p1/disable")
        assert r2.json()["data"]["status"] == "disabled"

    def test_load_unload_flow(self, client):
        client.post(f"{BASE}/p1/install", json={"source": "local"})
        assert client.post(f"{BASE}/p1/load").json()["data"]["loaded"] is True
        assert client.post(f"{BASE}/p1/unload").json()["data"]["loaded"] is False

    def test_enable_unknown_404(self, client):
        assert client.post(f"{BASE}/ghost/enable").status_code == 404

    def test_uninstall(self, client):
        client.post(f"{BASE}/p1/install", json={"source": "local"})
        assert client.delete(f"{BASE}/p1/uninstall").status_code == 200
        assert client.get(f"{BASE}/p1").status_code == 404

    def test_status_counts(self, client):
        client.post(f"{BASE}/p1/install", json={"source": "local"})
        client.post(f"{BASE}/p1/enable", json={})
        r = client.get(BASE + "/status")
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["enabled"] == 1
        assert data["loaded"] == 1
        assert data["disabled"] == 0

    def test_market_reserved_not_implemented_semantics(self, client):
        """市场面为预留桩（诚实 message，不假实现）。"""
        r = client.get(BASE + "/market")
        assert r.status_code == 200
        assert "coming soon" in r.json()["message"].lower()
