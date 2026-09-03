"""
店铺 REST 端点契约测试 — TDD 红灯先行。

范围（P4 API 端点，§5.3）：
- GET/POST /stores（列表过滤、创建+脱敏）
- GET/PUT/DELETE /stores/{store_id}
- POST /stores/{store_id}/test（探针：TikTok 取回 shop_cipher、无凭据报错）
- POST /stores/{store_id}/refresh（刷新 token 并回写）

使用 FastAPI TestClient + 最小 app（仅挂载 neurflow router）。
占位凭据均为无敏感含义片段。
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.llm.providers.secret_store import SecretStore

_AK = "aaaa" + "1111"
_SK = "bbbb" + "2222"
_AT = "cccc" + "3333"
_RT = "dddd" + "4444"


@pytest.fixture
def storage(tmp_path):
    st = NeurflowStorage(str(tmp_path / "test_neurflow.db"))
    yield st
    st.close()


@pytest.fixture
def secret_store(tmp_path):
    ss = SecretStore(master_key="test-master-key-004", storage_path=str(tmp_path / "secrets.json"))
    yield ss


@pytest.fixture
def client(storage, secret_store):
    """最小 app：仅挂载 neurflow router，注入临时存储与密钥库 + 认证用户 user_a"""
    from neurova.api.endpoints import neurflow_api as mod
    from neurova.collaboration.neurflow.store_connections import StoreConnectionManager

    manager = StoreConnectionManager(storage=storage, secret_store=secret_store)
    with patch.object(mod, "_get_store_manager", return_value=manager):
        from neurova.api.auth import get_current_user_or_default
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user_or_default] = lambda: {"user_id": "user_a"}
        with TestClient(app) as tc:
            yield tc


@pytest.fixture
def other_user_client(storage, secret_store):
    """模拟另一个认证用户 user_b"""
    from neurova.api.endpoints import neurflow_api as mod
    from neurova.collaboration.neurflow.store_connections import StoreConnectionManager

    manager = StoreConnectionManager(storage=storage, secret_store=secret_store)
    with patch.object(mod, "_get_store_manager", return_value=manager):
        from neurova.api.auth import get_current_user_or_default
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user_or_default] = lambda: {"user_id": "user_b"}
        with TestClient(app) as tc:
            yield tc


def _payload(name="淘宝主店", platform="taobao", credentials=None, **extra):
    data = {"platform": platform, "store_name": name, "credentials": credentials, **extra}
    return data


class TestStoreIsolation:
    def test_other_user_cannot_see_or_touch(self, client, other_user_client):
        sid = client.post("/stores", json=_payload(name="A的店", platform="taobao")).json()["store"]["store_id"]
        # 列表隔离
        assert other_user_client.get("/stores").json()["total"] == 0
        assert client.get("/stores").json()["total"] == 1
        # 详情 404
        assert other_user_client.get(f"/stores/{sid}").status_code == 404
        # 更新/删除 404
        assert other_user_client.put(f"/stores/{sid}", json={"store_name": "篡改"}).status_code == 404
        assert other_user_client.delete(f"/stores/{sid}").status_code == 404
        # user_a 数据不受影响
        assert client.get(f"/stores/{sid}").json()["store"]["store_name"] == "A的店"


class TestStoreCrud:
    def test_create_returns_masked_store(self, client, secret_store):
        resp = client.post("/stores", json=_payload(credentials={"app_key": _AK, "app_secret": _SK, "access_token": _AT}))
        assert resp.status_code == 200
        data = resp.json()["store"]
        assert data["store_id"].startswith("store_")
        assert data["platform"] == "taobao"
        assert data["app_key_masked"] == "****" + "1111"
        assert "aaaa" + "1111" not in resp.text

    def test_create_requires_platform_and_name(self, client):
        assert client.post("/stores", json={}).status_code == 400
        assert client.post("/stores", json={"platform": "taobao"}).status_code == 400

    def test_list_and_filter_by_platform(self, client):
        client.post("/stores", json=_payload(name="淘宝A", platform="taobao"))
        client.post("/stores", json=_payload(name="淘宝B", platform="taobao"))
        client.post("/stores", json=_payload(name="拼多多A", platform="pdd"))
        all_data = client.get("/stores").json()
        assert all_data["total"] == 3
        tb = client.get("/stores", params={"platform": "taobao"}).json()
        assert tb["total"] == 2

    def test_get_detail(self, client):
        sid = client.post("/stores", json=_payload()).json()["store"]["store_id"]
        detail = client.get(f"/stores/{sid}").json()["store"]
        assert detail["store_id"] == sid
        assert detail["store_name"] == "淘宝主店"

    def test_get_missing_404(self, client):
        assert client.get("/stores/store_missing").status_code == 404

    def test_update_store(self, client, secret_store):
        sid = client.post("/stores", json=_payload()).json()["store"]["store_id"]
        resp = client.put(f"/stores/{sid}", json={"store_name": "新名"})
        assert resp.status_code == 200
        assert resp.json()["store"]["store_name"] == "新名"
        # 更新也支持轮换凭据
        client.put(f"/stores/{sid}", json={"credentials": {"app_key": "eeee" + "5555"}})
        assert secret_store.get(f"STORE_{sid}_" + "APP_KEY") == "eeee" + "5555"

    def test_delete_store(self, client, secret_store):
        sid = client.post("/stores", json=_payload(credentials={"app_key": _AK})).json()["store"]["store_id"]
        assert client.delete(f"/stores/{sid}").status_code == 200
        assert client.get(f"/stores/{sid}").status_code == 404
        assert secret_store.get(f"STORE_{sid}_" + "APP_KEY") is None

    def test_delete_missing_404(self, client):
        assert client.delete("/stores/store_missing").status_code == 404


class TestStoreTestConnection:
    def test_unknown_store_404(self, client):
        assert client.post("/stores/store_missing/test").status_code == 404

    def test_no_credentials_returns_error_and_marks_store(self, client):
        sid = client.post("/stores", json=_payload(name="无凭据店", platform="taobao")).json()["store"]["store_id"]
        resp = client.post(f"/stores/{sid}/test")
        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_tiktok_probe_saves_shop_cipher(self, client, storage, secret_store, monkeypatch):
        from neurova.api.endpoints import neurflow_api as mod
        from neurova.collaboration.neurflow.store_connections import StoreConnectionManager

        sid = client.post(
            "/stores",
            json=_payload(name="抖区店", platform="tiktok", credentials={"app_key": _AK, "app_secret": _SK, "access_token": _AT}),
        ).json()["store"]["store_id"]

        fake = AsyncMock(return_value={"status": "success", "output": {"shops": [{"shop_cipher": "cipher9900", "shop_name": "抖区店"}]}})
        manager = StoreConnectionManager(storage=storage, secret_store=secret_store)
        with patch.object(mod, "_get_store_manager", return_value=manager), patch(
            "neurova.collaboration.neurflow.external_api.get_tiktok_shop_client"
        ) as getter:
            getter.return_value = type("T", (), {"fetch_shop_cipher": fake})()
            resp = client.post(f"/stores/{sid}/test")

        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["status"] == "active"
        store = manager.get_store(sid, user_id="user_a")
        assert store.extra.get("shop_cipher") == "cipher9900"
        assert store.status == "active"


class TestStoreRefresh:
    def test_refresh_returns_updated_token(self, client, storage, secret_store):
        from neurova.api.endpoints import neurflow_api as mod
        from neurova.collaboration.neurflow.store_connections import StoreConnectionManager

        sid = client.post(
            "/stores",
            json=_payload(name="淘宝主店", platform="taobao", credentials={"app_key": _AK, "app_secret": _SK, "refresh_token": _RT}),
        ).json()["store"]["store_id"]

        manager = StoreConnectionManager(storage=storage, secret_store=secret_store)
        fake = AsyncMock(return_value="new" + "token88")
        with patch.object(mod, "_get_store_manager", return_value=manager), patch(
            "neurova.collaboration.neurflow.external_api.get_taobao_top_client"
        ) as getter:
            getter.return_value = type("T", (), {"get_access_token": fake})()
            resp = client.post(f"/stores/{sid}/refresh")

        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "active"
        assert secret_store.get(f"STORE_{sid}_" + "ACCESS_TOKEN") == "new" + "token88"
        store = manager.get_store(sid, user_id="user_a")
        assert store.status == "active"
        assert store.token_expires_at > 0
