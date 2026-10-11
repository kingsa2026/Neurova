"""插件端点的 HTTP 契约面（台账 §6-150 改判后的现行契约）

沿革：本文件 2026-09-13 那版按 `_PLUGINS` 进程内字典 store 写（11 例）——那份 store
让 install/enable/load 只翻布尔，读数与"插件代码是否被执行"完全脱钩。
用户 2026-10-11 改裁「做插件体系并接线」后，端点改读 `PluginManager`，于是：

- `install` 的源必须在**插件根**内（越界 400、远程 501），不再接受 `"local"` 这种随意字符串；
- `enable` **不再顺带把 loaded 置真**（启用是门，装载是另一步，两步都会留痕）；
- `load` 在未启用时回 409 并带成因，不再假装成功；
- 详情/列表/状态三个读面都来自 manager，`routes_mounted` 恒 `false` 并带成因
  （P1 只接通装载，插件声明的路由没挂进运行中的 app）。

装配类断言（"exec 真发生""越界真拒"）在 `tests/unit/plugins/test_pluginLoadIsReal.py`；
本文件只管 HTTP 语义与响应形状，两档不重复钉同一件事。
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
from neurova.plugins.plugin_manager import get_plugin_manager, reset_plugin_manager

BASE = "/api/v1/plugins"


def _writePluginInto(root: Path, name: str) -> Path:
    import json

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "description": "d", "author": "qa",
                    "entry_point": "main.py", "dependencies": []}),
        encoding="utf-8")
    (directory / "main.py").write_text(
        "class {}:\n"
        "    def on_initialize(self):\n        self.started = False\n"
        "    def on_enable(self):\n        self.started = True\n".format(name.capitalize()),
        encoding="utf-8")
    return directory


@pytest.fixture()
def client(tmp_path):
    """每例一套隔离插件根 + 全新 manager（全局单例不复用，防套件间污染）。"""
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    reset_plugin_manager()
    get_plugin_manager(str(root))

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
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "tester", "username": "tester", "role": "user"}
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u

    test_client = TestClient(app)
    test_client.pluginRoot = root
    yield test_client
    reset_plugin_manager()


def _install(client, name):
    directory = _writePluginInto(client.pluginRoot, name)
    return client.post(f"{BASE}/{name}/install", json={"source": str(directory)})


class TestPluginAPI:
    def test_list_plugins_empty(self, client):
        r = client.get(BASE + "/")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_plugins_with_filter(self, client):
        assert _install(client, "p1").status_code == 200, client.get(BASE + "/").text
        _install(client, "p2")

        assert client.get(BASE + "/?status=disabled").json()["data"]["total"] == 2
        assert client.get(BASE + "/?status=enabled").json()["data"]["total"] == 0

    def test_install_then_get(self, client):
        r = _install(client, "myplugin")

        assert r.status_code == 200, r.text
        assert r.json()["data"]["id"] == "myplugin"
        assert r.json()["data"]["routes_mounted"] is False

    def test_installNameMustMatchTheManifest(self, client):
        """路径里的 id 与 manifest 的 name 不一致时报 400，不静默改名。"""
        directory = _writePluginInto(client.pluginRoot, "realname")

        r = client.post(f"{BASE}/othername/install", json={"source": str(directory)})

        assert r.status_code == 400, r.text
        assert "manifest" in r.text or "name" in r.text, r.text

    def test_get_plugin_not_found(self, client):
        assert client.get(f"{BASE}/ghost").status_code == 404

    def test_enable_disable_flow(self, client):
        _install(client, "p1")

        enabled = client.post(f"{BASE}/p1/enable").json()["data"]
        assert enabled["status"] == "enabled"
        assert enabled["loaded"] is False, (
            "启用把 loaded 也置真了——那是旧布尔实现留下的假象：启用是门，装载才是执行")

        assert client.post(f"{BASE}/p1/disable").json()["data"]["status"] == "disabled"

    def test_load_unload_flow(self, client):
        _install(client, "p1")

        refused = client.post(f"{BASE}/p1/load")
        assert refused.status_code == 409, refused.text

        assert client.post(f"{BASE}/p1/enable").status_code == 200
        assert client.post(f"{BASE}/p1/load").json()["data"]["loaded"] is True
        assert client.post(f"{BASE}/p1/unload").json()["data"]["loaded"] is False

    def test_enable_unknown_404(self, client):
        assert client.post(f"{BASE}/ghost/enable").status_code == 404

    def test_uninstall(self, client):
        _install(client, "p1")

        assert client.delete(f"{BASE}/p1/uninstall").status_code == 200
        assert client.get(f"{BASE}/p1").status_code == 404

    def test_status_counts(self, client):
        _install(client, "p1")
        client.post(f"{BASE}/p1/enable")
        client.post(f"{BASE}/p1/load")

        data = client.get(BASE + "/status").json()["data"]
        assert data == {"total": 1, "enabled": 1, "loaded": 1, "disabled": 0}, data

    def test_market_reserved_not_implemented_semantics(self, client):
        """市场面仍是预留桩（诚实 message，不假实现）。"""
        r = client.get(BASE + "/market")

        assert r.status_code == 200
        assert "coming soon" in r.json()["message"].lower()

    def test_discoverOnlyScansThePluginRoot(self, client):
        _writePluginInto(client.pluginRoot, "found")

        data = client.post(BASE + "/discover", json={"directory": None}).json()["data"]

        assert [p["name"] for p in data["plugins"]] == ["found"], data
        escaped = client.post(BASE + "/discover", json={"directory": "../.."}).status_code
        assert escaped == 400, "扫描面本身不能指到根外"
