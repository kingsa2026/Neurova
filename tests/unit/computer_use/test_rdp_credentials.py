"""RDP 直连凭据授权面（§6-592 接通批）。

验收：
- 凭据存储：set/get（单记录 rdp::endpoint JSON，加密落盘）/status（脱敏不回
  token）/delete，按用户分桶
- rdp_provider：默认 resolver 读 get_rdp_endpoint 真实接通；未配置 fail-closed
- API：POST 校验 host+首次 token（空 token 不覆盖已设值）、GET 脱敏、DELETE；
  按当前用户分桶
"""

import pytest

from neurova.web_reach.credentials import UserCredentialStore


@pytest.fixture
def store(tmp_path):
    return UserCredentialStore(base_dir=str(tmp_path / "creds"), encryption_key="k" * 32)


class TestRdpEndpointCredentials:
    def test_set_get_roundtrip(self, store):
        assert store.set_rdp_endpoint("u1", host="10.0.0.5", port=8765, token="tk-secret")
        ep = store.get_rdp_endpoint("u1")
        assert ep["host"] == "10.0.0.5" and ep["port"] == 8765 and ep["token"] == "tk-secret"

    def test_per_user_isolation(self, store):
        store.set_rdp_endpoint("u1", host="h1", token="t1")
        assert store.get_rdp_endpoint("u2") == {}

    def test_status_masked(self, store):
        store.set_rdp_endpoint("u1", host="10.0.0.5", port=8766, token="tk-secret")
        st = store.rdp_status("u1")
        assert st["configured"] is True
        assert st["host"] == "10.0.0.5" and st["port"] == 8766 and st["token_set"] is True
        assert "tk-secret" not in str(st), "status 不得回显 token"

    def test_status_unconfigured(self, store):
        st = store.rdp_status("nobody")
        assert st["configured"] is False and st["token_set"] is False

    def test_delete(self, store):
        store.set_rdp_endpoint("u1", host="h1", token="t")
        assert store.delete_rdp_endpoint("u1") is True
        assert store.get_rdp_endpoint("u1") == {}
        assert store.rdp_status("u1")["configured"] is False

    def test_delete_unconfigured(self, store):
        assert store.delete_rdp_endpoint("nobody") is False

    def test_empty_host_rejected(self, store):
        assert store.set_rdp_endpoint("u1", host="  ", token="t") is False

    def test_blank_token_no_overwrite(self, store):
        store.set_rdp_endpoint("u1", host="h1", token="keep")
        store.set_rdp_endpoint("u1", host="h2", token="")
        ep = store.get_rdp_endpoint("u1")
        assert ep["host"] == "h2" and ep["token"] == "keep", "空 token 只更新 host，不覆盖已设值"


class TestRdpProviderResolver:
    def test_default_resolver_reads_credentials(self, monkeypatch):
        from neurova.computer_use.rdp_provider import RdpDirectProvider

        class FakeStore:
            def get_rdp_endpoint(self, uid):
                return {"host": "192.168.1.9", "port": 8765, "token": "sec"}

        monkeypatch.setattr(
            "neurova.web_reach.credentials.get_credential_store", lambda *a, **k: FakeStore()
        )
        prov = RdpDirectProvider()
        s = prov.create("u1")
        assert s.base_url == "http://192.168.1.9:8765"
        assert s.token == "sec"

    def test_unconfigured_resolver_none(self, monkeypatch):
        from neurova.computer_use.rdp_provider import RdpDirectProvider

        class FakeStore:
            def get_rdp_endpoint(self, uid):
                return {}

        monkeypatch.setattr(
            "neurova.web_reach.credentials.get_credential_store", lambda *a, **k: FakeStore()
        )
        assert RdpDirectProvider()._resolve("u1") is None


class TestRdpCredentialAPI:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from neurova.api.endpoints.settings import router
        from neurova.api.deps import get_current_user
        from neurova.web_reach import credentials as cred

        # 隔离到 tmp：API 测试不得写真实 data/web_reach_credentials
        cred._credential_store_instance = UserCredentialStore(
            base_dir=str(tmp_path / "creds"), encryption_key="k" * 32
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "api-u", "role": "user"}
        yield TestClient(app)
        cred._credential_store_instance = None

    def test_post_get_delete(self, client):
        r = client.post(
            "/v1/settings/rdp-credentials",
            json={"host": "10.0.0.5", "port": 8765, "token": "tk-secret"},
        )
        assert r.status_code == 200, r.text
        st = client.get("/v1/settings/rdp-credentials").json()["data"]
        assert st["configured"] is True and st["host"] == "10.0.0.5" and st["port"] == 8765
        assert st["token_set"] is True
        assert "tk-secret" not in str(st), "GET 不得回显 token"
        assert client.delete("/v1/settings/rdp-credentials").json()["data"]["deleted"] is True
        assert client.get("/v1/settings/rdp-credentials").json()["data"]["configured"] is False

    def test_post_requires_host(self, client):
        assert client.post(
            "/v1/settings/rdp-credentials", json={"host": "", "token": "t"}
        ).status_code in (422, 400)

    def test_post_requires_token_first_time(self, client):
        assert client.post("/v1/settings/rdp-credentials", json={"host": "h"}).status_code == 422

    def test_token_blank_keeps_existing(self, client):
        client.post("/v1/settings/rdp-credentials", json={"host": "h1", "token": "keep"})
        r = client.post("/v1/settings/rdp-credentials", json={"host": "h2"})
        assert r.status_code == 200, r.text
        st = client.get("/v1/settings/rdp-credentials").json()["data"]
        assert st["host"] == "h2" and st["token_set"] is True

    def test_delete_unconfigured_404(self, client):
        assert client.delete("/v1/settings/rdp-credentials").status_code == 404
