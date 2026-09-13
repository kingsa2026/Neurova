"""社交平台凭据配置（web_reach social_exec 消费，复用 SSH 同一配置面/加密桶）

验收：
- 存储：set_platform_credentials 只接受该平台所需键、空值不覆盖；platform_status 脱敏
  （键名+是否已配，不回值）；clear 删除该平台全部所需键
- API：GET 状态、POST 保存、不支持平台 422、空值 422、DELETE 清除
"""

import pytest

from neurova.web_reach.credentials import UserCredentialStore


@pytest.fixture
def store(tmp_path):
    return UserCredentialStore(base_dir=str(tmp_path / "creds"), encryption_key="k" * 32)


class TestPlatformCredentials:
    def test_set_and_status(self, store):
        assert store.set_platform_credentials("u1", "twitter", {"twitter_auth_token": "A", "twitter_ct0": "B"})
        status = {p["platform"]: p for p in store.platform_status("u1")}
        tw = status["twitter"]
        assert tw["configured"] is True
        assert all(k["set"] for k in tw["keys"])
        # 脱敏：不回显值
        assert "A" not in str(status) and "B" not in str(status)

    def test_partial_not_configured(self, store):
        store.set_platform_credentials("u1", "twitter", {"twitter_auth_token": "A"})
        tw = {p["platform"]: p for p in store.platform_status("u1")}["twitter"]
        assert tw["configured"] is False  # 缺 ct0

    def test_ignores_unknown_keys(self, store):
        # github_token 不属于 twitter → 忽略，不污染
        store.set_platform_credentials("u1", "twitter", {"twitter_auth_token": "A", "github_token": "G"})
        assert store.get_credential("u1", "github_token") is None

    def test_empty_value_no_overwrite(self, store):
        store.set_platform_credentials("u1", "github", {"github_token": "keep"})
        store.set_platform_credentials("u1", "github", {"github_token": ""})  # 空不覆盖
        assert store.get_credential("u1", "github_token") == "keep"

    def test_unsupported_platform(self, store):
        assert store.set_platform_credentials("u1", "myspace", {"x": "y"}) is False

    def test_clear(self, store):
        store.set_platform_credentials("u1", "reddit", {"reddit_session": "S"})
        assert store.clear_platform_credentials("u1", "reddit") == 1
        assert store.get_credential("u1", "reddit_session") is None


class TestSocialCredentialAPI:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
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
        secret = "ghp_SECRETTOKEN999"
        r = client.post("/v1/settings/social-credentials", json={"platform": "github", "credentials": {"github_token": secret}})
        assert r.status_code == 200, r.text
        platforms = client.get("/v1/settings/social-credentials").json()["data"]["platforms"]
        gh = next(p for p in platforms if p["platform"] == "github")
        assert gh["configured"] is True
        assert secret not in str(platforms)  # 值脱敏（键名 github_token 不算泄漏）
        assert client.delete("/v1/settings/social-credentials/github").json()["data"]["cleared"] == 1

    def test_unsupported_platform_422(self, client):
        assert client.post("/v1/settings/social-credentials", json={"platform": "myspace", "credentials": {"a": "b"}}).status_code == 422

    def test_empty_credentials_422(self, client):
        assert client.post("/v1/settings/social-credentials", json={"platform": "github", "credentials": {"github_token": ""}}).status_code == 422
