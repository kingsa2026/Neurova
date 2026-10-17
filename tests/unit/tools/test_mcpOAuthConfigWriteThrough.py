# -*- coding: utf-8 -*-
"""MCP OAuth 配置写侧闭环（断点①）。

缺陷形状：读侧三处消费者（`mcp_client.call_tool` 取 token、
`POST /mcp-servers/{id}/oauth/authorize`、`GET /mcp-servers` 的 `oauth_grant`）
都在取 `config.oauth`，但 `mcp_config._ALLOWED_KEYS` 从未含 `oauth`，注册请求体
也没有该字段 ⇒ 生产里这个键**存不进去**。来历：`git log -S '"oauth"'` 在
mcp_config.py 零命中，读取面是 931453e2 / 247ecbb7 两笔带进来的半成品。

第二层缺陷：那两笔把读取写成 `entry["config"]["oauth"]`（`mcp_client` 的运行时
包装形状），而 `SharedConfigManager` 落的是 `validate_mcp_server_config` 的**扁平**
返回值——即便键能存进去，读侧照样取不到。故本档 entry 一律由生产写入口产出，
测试不自造形状（旧夹具 `tests/unit/api/test_mcp_oauth_endpoint.py` 自造了包装形状，
于是九格全绿而线上那条路一个都没通过）。
"""

import pytest

from neurova.tool_layers.mcp_config import validate_mcp_server_config

AUTHORIZATION_CODE_OAUTH = {
    "grant_type": "authorization_code",
    "authorization_url": "https://idp.example.com/authorize",
    "token_url": "https://idp.example.com/token",
    "client_id": "cid",
    "client_secret": "csecret",
    "scope": "mcp",
}

CLIENT_CREDENTIALS_OAUTH = {
    "grant_type": "client_credentials",
    "token_url": "https://idp.example.com/token",
    "client_id": "cid",
    "client_secret": "csecret",
}


def _entry(oauth):
    """走生产写入口产出记录（shared_config 存的即是这份扁平字典）。"""
    return validate_mcp_server_config({
        "id": "remote-ac",
        "name": "Remote AC",
        "transport": "http",
        "url": "https://remote.example.com/mcp",
        "oauth": oauth,
    })


class TestOauthSubSchema:
    def test_oauthCarriedIntoNormalizedConfig(self):
        entry = _entry(dict(AUTHORIZATION_CODE_OAUTH))
        assert entry["oauth"]["grant_type"] == "authorization_code"
        assert entry["oauth"]["token_url"] == "https://idp.example.com/token"

    def test_absentOauthNormalizesToEmptyDict(self):
        entry = validate_mcp_server_config({
            "id": "plain", "transport": "http", "url": "https://remote.example.com/mcp",
        })
        assert entry["oauth"] == {}

    def test_emptyOauthDictMeansUnconfigured(self):
        # 不启用 OAuth 时注册请求体的缺省形状正是 oauth={}（前端与 pydantic default_factory
        # 都这么给）。把它按"配了一半"拦下来 ⇒ 所有普通注册恒 400——本批第一版踩过这条，
        # 打红 tests/unit/api/test_tool_layers_auth.py 一整档，故钉成常驻判据。
        entry = _entry({})
        assert entry["oauth"] == {}

    def test_plainRegistrationWithoutOauthStillReachesPersistence(self):
        # 反向闸：允许 oauth 键不得改变任何既有注册形态的行为
        entry = validate_mcp_server_config({
            "id": "stdio-one", "transport": "stdio", "command": "npx", "args": ["-y", "srv"],
        })
        assert entry["oauth"] == {}
        assert entry["command"] == "npx"

    def test_nonDictOauthRejected(self):
        # 断的是**类型**报错而非「未知字段」——否则 oauth 一旦被允许键收留，
        # 这格会从「未知字段 ['oauth']」换成「oauth 必须为字典」，而 match="oauth"
        # 两边都命中，等于没测（现值就是这种假绿）
        with pytest.raises(ValueError, match="oauth 必须为"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": "https://idp.example.com/token",
            })

    def test_missingTokenUrlRejected(self):
        # TokenCache.get_or_create 取 oauth_config["token_url"]，缺则调用期 KeyError
        with pytest.raises(ValueError, match="token_url"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": {"grant_type": "client_credentials", "client_id": "cid"},
            })

    def test_clientCredentialsWithoutClientIdRejected(self):
        # get_or_create 取 oauth_config["client_id"]，静默存进去等于埋一颗调用期雷
        with pytest.raises(ValueError, match="client_id"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": {"grant_type": "client_credentials", "token_url": "https://t"},
            })

    def test_authorizationCodeWithoutAuthorizationUrlRejected(self):
        with pytest.raises(ValueError, match="authorization_url"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": {
                    "grant_type": "authorization_code",
                    "token_url": "https://idp.example.com/token",
                    "client_id": "cid",
                },
            })

    def test_authorizationCodeWithDcrEndpointAndNoClientIdAccepted(self):
        # run_authorization_code_flow 允许「无 client_id + 有 registration_endpoint」走 DCR
        entry = _entry({
            "grant_type": "authorization_code",
            "authorization_url": "https://idp.example.com/authorize",
            "token_url": "https://idp.example.com/token",
            "registration_endpoint": "https://idp.example.com/register",
        })
        assert entry["oauth"]["registration_endpoint"] == "https://idp.example.com/register"

    def test_authorizationCodeWithoutClientIdOrDcrRejected(self):
        with pytest.raises(ValueError, match="registration_endpoint"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": {
                    "grant_type": "authorization_code",
                    "authorization_url": "https://idp.example.com/authorize",
                    "token_url": "https://idp.example.com/token",
                },
            })

    def test_nonLoopbackRedirectUriRejected(self):
        # RFC 8252：环回回调是本仓既有约束，配置期就该拦住（mcp_oauth 同款谓词）
        with pytest.raises(ValueError, match="redirect_uri"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": dict(AUTHORIZATION_CODE_OAUTH, redirect_uri="https://evil.example.com/cb"),
            })

    def test_grantTypeOutsideTwoValuesRejected(self):
        with pytest.raises(ValueError, match="grant_type"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": dict(CLIENT_CREDENTIALS_OAUTH, grant_type="password"),
            })

    def test_unknownOauthKeyRejected(self):
        # 与外层同规：未知键显式拒绝，不静默丢弃
        with pytest.raises(ValueError, match="refresh_token"):
            validate_mcp_server_config({
                "id": "s", "transport": "http", "url": "https://r.example.com",
                "oauth": dict(CLIENT_CREDENTIALS_OAUTH, refresh_token="rt"),
            })

    def test_normalizedOauthIsDeepCopy(self):
        source = dict(CLIENT_CREDENTIALS_OAUTH)
        entry = _entry(source)
        entry["oauth"]["client_secret"] = "tampered"
        assert source["client_secret"] == "csecret"

    def test_clientSecretGoesToDiskThroughTheRealManager(self, tmp_path):
        # 曾经这格直接调 sealSecrets 验纯函数——生产 _save_config 走的是另一条窄通道，
        # 于是它绿而活体量到磁盘上是明文。判据必须走真写入口（`SharedConfigManager`）。
        # 收口后的完整口径与存量兼容面由
        # tests/unit/security/test_configCredentialSealingOneChannel.py 承担。
        import json

        from neurova.shared_config import SharedConfigManager

        path = str(tmp_path / "shared_config.json")
        manager = SharedConfigManager(path)
        assert manager.add_mcp_server(_entry(dict(AUTHORIZATION_CODE_OAUTH)))
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        assert "csecret" not in raw, "client_secret 明文落盘"
        # 默认配置本就带一条 catalog 条目，按下标取会撞上它——按 id 找自己那条
        from neurova.security.secret_store import _ENC_PREFIX

        stored = next(s for s in json.loads(raw)["mcp_servers"] if s["id"] == "remote-ac")
        assert stored["oauth"]["client_secret"].startswith(_ENC_PREFIX)


class TestRegisterPayloadCarriesOauth:
    """请求体 → 持久化 的透传（此前 MCPServerConnectRequest 无该字段，pydantic 静默丢）。"""

    @pytest.fixture
    def manager(self, monkeypatch):
        class RecordingManager:
            def __init__(self):
                self.saved = []

            def add_mcp_server(self, server):
                from neurova.tool_layers.mcp_config import validate_mcp_server_config

                try:
                    validated = validate_mcp_server_config(server)
                except ValueError:
                    return False
                self.saved.append(validated)
                return True

            def get_mcp_server(self, sid):
                return next((s for s in self.saved if s.get("id") == sid), None)

            def list_mcp_servers(self):
                return list(self.saved)

        mgr = RecordingManager()
        monkeypatch.setattr(
            "neurova.shared_config.get_shared_config_manager", lambda: mgr
        )
        return mgr

    @pytest.fixture
    def client(self, manager):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import tool_layers

        async def _never_connect(server_id, config):
            return True

        class StubClient:
            connect_server = staticmethod(_never_connect)

            @staticmethod
            def get_server_status(server_id):
                return {"connected": True, "tool_count": 0}

        monkey_target = "neurova.tool_layers.mcp_client.get_mcp_client"
        import unittest.mock as mock

        with mock.patch(monkey_target, return_value=StubClient()):
            app = FastAPI()
            app.include_router(tool_layers.router, prefix="/v1/tool-layers")
            app.dependency_overrides[tool_layers.get_current_user] = lambda: {
                "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "1",
            }
            yield TestClient(app)

    def test_registerPersistsOauthSubConfig(self, client, manager):
        resp = client.post("/v1/tool-layers/mcp-servers", json={
            "name": "remote-ac",
            "url": "https://remote.example.com/mcp",
            "transport": "http",
            "oauth": dict(AUTHORIZATION_CODE_OAUTH),
        })
        assert resp.status_code == 200, resp.text
        assert manager.saved, "注册没有把配置交给持久化（oauth 被请求体丢弃）"
        assert manager.saved[0]["oauth"]["grant_type"] == "authorization_code"

    def test_registerWithPrivateTokenUrlRejectedForNonAdmin(self, manager):
        # 新增的出网目标不得绕过既有 SSRF 门（token_url 是本批引入的攻击面）
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import unittest.mock as mock

        from neurova.api.endpoints import tool_layers

        async def _never_connect(server_id, config):
            return True

        class StubClient:
            connect_server = staticmethod(_never_connect)

            @staticmethod
            def get_server_status(server_id):
                return {"connected": False, "tool_count": 0}

        with mock.patch(
            "neurova.tool_layers.mcp_client.get_mcp_client", return_value=StubClient()
        ):
            app = FastAPI()
            app.include_router(tool_layers.router, prefix="/v1/tool-layers")
            app.dependency_overrides[tool_layers.get_current_user] = lambda: {
                "user_id": "u2", "username": "u", "role": "user", "neuser_id": "2",
            }
            resp = TestClient(app).post("/v1/tool-layers/mcp-servers", json={
                "name": "link-local",
                "url": "https://remote.example.com/mcp",
                "transport": "http",
                "oauth": dict(CLIENT_CREDENTIALS_OAUTH, token_url="http://169.254.169.254/token"),
            })
        assert resp.status_code == 400
        assert not manager.saved


class TestReadersConsumePersistedShape:
    """读侧必须吃 shared_config 的扁平记录，不再按运行时包装形状取。"""

    def testListExposesOauthGrantFromProducedEntry(self):
        from neurova.api.endpoints.tool_layers import _server_info_from_config

        entry = _entry(dict(AUTHORIZATION_CODE_OAUTH))
        info = _server_info_from_config(entry, {"connected": True, "tool_count": 0})
        assert info.oauth_grant == "authorization_code"

    def testAuthorizeEndpointReadsProducedEntry(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import tool_layers

        entry = _entry(dict(AUTHORIZATION_CODE_OAUTH))

        class FakeManager:
            def get_mcp_server(self, sid):
                return entry if sid == entry["id"] else None

            def list_mcp_servers(self):
                return [entry]

        monkeypatch.setattr(
            "neurova.shared_config.get_shared_config_manager", lambda: FakeManager()
        )

        seen = {}

        async def _fake_flow(server_id, oauth_config, timeout_s=300.0):
            seen["server_id"] = server_id
            seen["token_url"] = oauth_config.get("token_url")
            return "ep-token"

        monkeypatch.setattr(
            "neurova.tool_layers.mcp_oauth.run_authorization_code_flow", _fake_flow
        )

        app = FastAPI()
        app.include_router(tool_layers.router, prefix="/v1/tool-layers")
        app.dependency_overrides[tool_layers.get_current_user] = lambda: {
            "user_id": "u1", "username": "u", "role": "user", "neuser_id": "1",
        }
        resp = TestClient(app).post("/v1/tool-layers/mcp-servers/remote-ac/oauth/authorize")

        assert resp.status_code == 200, resp.text
        assert seen == {"server_id": "remote-ac", "token_url": "https://idp.example.com/token"}
