"""BUG AUDIT S-04 残余回归测试: 首账号注册的引导令牌环境门控。

缺陷: 首账号注册（count_users()==0）跳过验证码并直接 role=admin ——
服务端部署场景下任意访客可抢注管理员。

修复契约（环境门控, 保桌面默认行为）:
- 配置了引导令牌（环境变量 NEUROVA_BOOTSTRAP_ADMIN_TOKEN 非空,
  或 data/bootstrap_admin.ini 的 [bootstrap] token 键）时:
  首账号注册必须提供匹配 token（缺失/不匹配 → 403, hmac.compare_digest）;
- 两处均未配置 → 保持现状（首账号即管理员, 桌面首启向导不受影响）;
- 旧格式 bootstrap_admin.ini（仅 username/password, 无 token 键）→ 视为未配置令牌;
- 非首启注册（已有用户）不受门控影响。

策略与 test_first_user_admin.py 相同: 最小 app + 模块级模型打桩。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s04_0123456789abcdef")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import neurova.api.bootstrap_user as bootstrap_user_module
import neurova.api.endpoints.auth as auth_endpoint
from neurova.api.endpoints.auth import router

TOKEN_ENV = "NEUROVA_BOOTSTRAP_ADMIN_TOKEN"


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1/auth")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fake_models():
    from unittest.mock import MagicMock

    user_model = MagicMock()
    verification_model = MagicMock()
    verification_model.check_register_rate_limit.return_value = {"is_limited": False}

    created = []

    def _create_user(**kwargs):
        created.append(kwargs)
        u = MagicMock()
        u.id = 1
        u.username = kwargs.get("username", "u")
        u.role = kwargs.get("role", "user")
        return u

    user_model.create_user.side_effect = _create_user
    user_model.get_user_by_username.return_value = None
    user_model.get_user_by_email.return_value = None
    user_model.count_users.return_value = 0
    user_model.created_kwargs = created

    auth_endpoint._user_model = user_model
    auth_endpoint._verification_code_model = verification_model
    yield user_model, verification_model
    auth_endpoint._user_model = None
    auth_endpoint._verification_code_model = None


@pytest.fixture(autouse=True)
def clean_token_env(monkeypatch):
    """默认清除引导令牌配置, 各用例自行声明所需环境。"""
    monkeypatch.delenv(TOKEN_ENV, raising=False)


def _register(client, token=None):
    payload = {"username": "founder", "password": "Passw0rd!123"}
    if token is not None:
        payload["bootstrap_token"] = token
    return client.post("/v1/auth/register", json=payload)


class TestEnvTokenGate:
    def test_missing_token_403(self, client, fake_models, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok-123")
        resp = _register(client)
        assert resp.status_code == 403, resp.text
        assert fake_models[0].created_kwargs == [], "被拒注册不得创建用户"

    def test_wrong_token_403(self, client, fake_models, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok-123")
        resp = _register(client, token="tok-wrong")
        assert resp.status_code == 403, resp.text
        assert fake_models[0].created_kwargs == []

    def test_matching_token_200_and_admin(self, client, fake_models, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok-123")
        resp = _register(client, token="tok-123")
        assert resp.status_code == 200, resp.text
        assert fake_models[0].created_kwargs[0]["role"] == "admin"


class TestIniTokenGate:
    def _write_ini(self, tmp_path, content):
        ini = tmp_path / "bootstrap_admin.ini"
        ini.write_text(content, encoding="utf-8")
        return str(ini)

    def test_ini_token_missing_403(self, client, fake_models, monkeypatch, tmp_path):
        monkeypatch.setattr(
            bootstrap_user_module, "BOOTSTRAP_ADMIN_FILE", self._write_ini(tmp_path, "[bootstrap]\ntoken = tok-456\n")
        )
        resp = _register(client)
        assert resp.status_code == 403, resp.text

    def test_ini_token_matching_200(self, client, fake_models, monkeypatch, tmp_path):
        monkeypatch.setattr(
            bootstrap_user_module, "BOOTSTRAP_ADMIN_FILE", self._write_ini(tmp_path, "[bootstrap]\ntoken = tok-456\n")
        )
        resp = _register(client, token="tok-456")
        assert resp.status_code == 200, resp.text
        assert fake_models[0].created_kwargs[0]["role"] == "admin"

    def test_legacy_ini_without_token_keeps_open(self, client, fake_models, monkeypatch, tmp_path):
        """旧格式 ini（仅 username/password, 安装包约定）→ 视为未配置令牌, 行为不变"""
        monkeypatch.setattr(
            bootstrap_user_module,
            "BOOTSTRAP_ADMIN_FILE",
            self._write_ini(tmp_path, "[bootstrap]\nusername = admin\npassword = secret\n"),
        )
        resp = _register(client)
        assert resp.status_code == 200, resp.text
        assert fake_models[0].created_kwargs[0]["role"] == "admin"


class TestDesktopDefaultUnchanged:
    def test_no_token_configured_first_account_admin(self, client, fake_models):
        """未配置任何引导令牌 → 保持现状（桌面首启: 注册即管理员）"""
        resp = _register(client)
        assert resp.status_code == 200, resp.text
        assert fake_models[0].created_kwargs[0]["role"] == "admin"

    def test_env_token_ignored_when_users_exist(self, client, fake_models, monkeypatch):
        """非首启注册（已有用户）不受门控影响"""
        monkeypatch.setenv(TOKEN_ENV, "tok-123")
        fake_models[0].count_users.return_value = 1
        resp = client.post(
            "/v1/auth/register",
            json={
                "username": "follower",
                "password": "Passw0rd!123",
                "email": "f@example.com",
                "verification_code": "123456",
            },
        )
        assert resp.status_code == 200, resp.text
        assert fake_models[0].created_kwargs[0]["role"] == "user"
