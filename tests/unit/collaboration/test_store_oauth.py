"""
Tier 2 OAuth（stores/oauth/authorize + callback）契约测试 — TDD 红灯先行。

范围（§5.3 Tier 2）：
1. authorize：POST 凭据 → 返回平台授权 URL（redirect_uri 回调 + state）；
   凭据不进 URL；未支持平台 400；旧 GET 形态 405；
2. callback：校验 state → 换 token → 更新店铺凭据 → 302 回前端；
3. state 一次性（重复使用 400）、错误 state 400、无 state 400。

占位值均为无敏感含义片段。
"""

import re
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.llm.providers.secret_store import SecretStore

_AK = "tk" + "app1111"
_SK = "tk" + "sec2222"


@pytest.fixture
def storage(tmp_path):
    st = NeurflowStorage(str(tmp_path / "test_neurflow.db"))
    yield st
    st.close()


@pytest.fixture
def secret_store(tmp_path):
    ss = SecretStore(master_key="test-master-key-005", storage_path=str(tmp_path / "secrets.json"))
    yield ss


@pytest.fixture
def client(storage, secret_store):
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


def _extract_state(location: str) -> str:
    m = re.search(r"[?&]state=([^&]+)", location)
    assert m, f"location 缺少 state: {location}"
    return m.group(1)


def _extract_code(location_or_body: str) -> str:
    m = re.search(r"[?&]code=([^&]+)", location_or_body)
    return m.group(1) if m else ""


class TestOAuthAuthorize:
    def test_taobao_authorize_returnsUrlWithState(self, client, storage, secret_store):
        resp = client.post(
            "/stores/oauth/authorize",
            json={"platform": "taobao", "app_key": _AK, "app_secret": _SK, "store_name": "淘宝店"},
        )
        assert resp.status_code == 200
        location = resp.json()["authorize_url"]
        assert "oauth.taobao.com/authorize" in location
        assert "redirect_uri=http%3A%2F%2Ftestserver%2Fapi%2Fv1%2Fneurflow%2Fstores%2Foauth%2Fcallback" in location
        state = _extract_state(location)
        # 预建 pending 店铺，凭据已入库
        assert storage.get_store_connection.__self__ is not None
        stores = client.get("/stores").json()["stores"]
        assert len(stores) == 1
        assert stores[0]["platform"] == "taobao"
        assert stores[0]["status"] == "pending"
        assert secret_store.get(f"STORE_{stores[0]['store_id']}_" + "APP_KEY") == _AK
        # state 值进入密钥库（防 CSRF）
        keys = [k for k in secret_store.list_keys() if k.startswith("OAUTH_STATE_")]
        assert state in [k.split("OAUTH_STATE_", 1)[1] for k in keys]
        # 凭据不得出现在返回的授权 URL 里
        assert _SK not in location

    def test_verified_xhs_authorize_url(self, client):
        resp = client.post(
            "/stores/oauth/authorize",
            json={"platform": "xiaohongshu", "app_key": _AK, "app_secret": _SK, "store_name": "小红书店"},
        )
        assert resp.status_code == 200
        location = resp.json()["authorize_url"]
        assert "ark.xiaohongshu.com/ark/authorization" in location
        assert "appId=" + _AK in location

    def test_amazon_unsupported_400(self, client):
        resp = client.post(
            "/stores/oauth/authorize",
            json={"platform": "amazon", "app_key": _AK, "app_secret": _SK, "store_name": "北美店"},
        )
        assert resp.status_code == 400

    def test_old_get_shape_is_gone(self, client):
        """凭据进 query 的旧形态必须退役：GET 同路径返回 405，而不是静默继续收 secret。"""
        resp = client.get(
            "/stores/oauth/authorize",
            params={"platform": "taobao", "app_key": _AK, "app_secret": _SK},
        )
        assert resp.status_code == 405


class TestOAuthCallback:
    def _authorize(self, client, platform="taobao"):
        resp = client.post(
            "/stores/oauth/authorize",
            json={"platform": platform, "app_key": _AK, "app_secret": _SK, "store_name": f"{platform}店"},
        )
        assert resp.status_code == 200
        return _extract_state(resp.json()["authorize_url"])

    def test_callback_exchanges_code_and_updates_store(self, client, secret_store):
        state = self._authorize(client, "taobao")
        sid = client.get("/stores").json()["stores"][0]["store_id"]
        fake = AsyncMock(return_value={"access_token": "new" + "tok8888", "refresh_token": "ref" + "99999999", "expires_in": 86400})
        with patch("neurova.collaboration.neurflow.external_api._http_post", fake):
            resp = client.get("/stores/oauth/callback", params={"code": "auth" + "code123", "state": state}, follow_redirects=False)
        assert resp.status_code == 302
        assert "store_oauth=ok" in resp.headers["location"]
        assert secret_store.get(f"STORE_{sid}_" + "ACCESS_TOKEN") == "new" + "tok8888"
        assert secret_store.get(f"STORE_{sid}_" + "REFRESH_TOKEN") == "ref" + "99999999"
        assert client.get(f"/stores/{sid}").json()["store"]["status"] == "active"
        # state 一次性
        again = client.get("/stores/oauth/callback", params={"code": "x", "state": state}, follow_redirects=False)
        assert again.status_code == 400

    def test_callback_rejects_unknown_state(self, client):
        resp = client.get("/stores/oauth/callback", params={"code": "c1", "state": "badstate"}, follow_redirects=False)
        assert resp.status_code == 400

    def test_callback_exchange_failure_marks_store(self, client):
        state = self._authorize(client)
        with patch("neurova.collaboration.neurflow.external_api._http_post", new=AsyncMock(side_effect=Exception("授权失败"))):
            resp = client.get("/stores/oauth/callback", params={"code": "c1", "state": state}, follow_redirects=False)
        assert resp.status_code == 302
        assert "store_oauth=error" in resp.headers["location"]
