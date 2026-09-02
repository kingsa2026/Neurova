"""
首个注册用户即管理员 + setup-status 端点测试（桌面壳首启向导后端契约）

背景: 打包后的桌面版没有任何用户, 首启向导要求:
- GET /v1/auth/setup-status → {"needs_setup": bool} 公开端点（无用户=true）
- POST /v1/auth/register 在无任何用户时 role=admin（首个注册者即管理员）
- 有用户后注册 role=user
- 无邮箱注册成功（向导不收集邮箱/验证码）

策略: 用最小 FastAPI app 挂载 auth router; 模块级 _user_model/_verification_code_model
全局打桩, 不触碰真实 users.db。
"""
import os

os.environ["NEUROVA_JWT_SECRET_KEY"] = "test_secret_key_1234567890123456789012345678901234567890"

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neurova.api.endpoints.auth as auth_endpoint
from neurova.api.endpoints.auth import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1/auth")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fake_models():
    """打桩 user_model + verification_code_model, 记录 create_user 调用参数"""
    user_model = MagicMock()
    verification_model = MagicMock()
    verification_model.check_register_rate_limit.return_value = {"is_limited": False}

    created = []

    def _make_user(kwargs):
        u = MagicMock()
        u.id = 1
        u.username = kwargs.get("username", "u")
        u.role = kwargs.get("role", "user")
        return u

    def _create_user(**kwargs):
        created.append(kwargs)
        return _make_user(kwargs)

    user_model.create_user.side_effect = _create_user
    user_model.get_user_by_username.return_value = None
    user_model.get_user_by_email.return_value = None
    user_model.created_kwargs = created

    auth_endpoint._user_model = user_model
    auth_endpoint._verification_code_model = verification_model
    yield user_model, verification_model
    auth_endpoint._user_model = None
    auth_endpoint._verification_code_model = None


class TestFirstUserAdmin:
    def test_first_registered_user_becomes_admin(self, client, fake_models):
        """无任何用户时注册 → role=admin（注册即管理员）"""
        user_model, _ = fake_models
        user_model.count_users.return_value = 0

        resp = client.post(
            "/v1/auth/register",
            json={"username": "founder", "password": "Passw0rd!123"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 0
        assert len(user_model.created_kwargs) == 1
        assert user_model.created_kwargs[0]["role"] == "admin"

    def test_second_registered_user_is_normal_user(self, client, fake_models):
        """已有用户时注册 → role=user（仅首个管理员）"""
        user_model, _ = fake_models
        user_model.count_users.return_value = 1

        resp = client.post(
            "/v1/auth/register",
            json={"username": "follower", "password": "Passw0rd!123"},
        )
        assert resp.status_code == 200, resp.text
        assert user_model.created_kwargs[0]["role"] == "user"

    def test_register_response_carries_tokens(self, client, fake_models):
        """注册响应带 token（向导注册后直接登录, 无需二次输密码）"""
        user_model, _ = fake_models
        user_model.count_users.return_value = 0

        resp = client.post(
            "/v1/auth/register",
            json={"username": "founder", "password": "Passw0rd!123"},
        )
        data = resp.json()["data"]
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["username"] == "founder"


class TestNoEmailRegister:
    def test_register_without_email_succeeds(self, client, fake_models):
        """向导无邮箱/验证码: 不传 email 也能注册成功"""
        user_model, verification_model = fake_models
        user_model.count_users.return_value = 0

        resp = client.post(
            "/v1/auth/register",
            json={"username": "noemail", "password": "Passw0rd!123"},
        )
        assert resp.status_code == 200, resp.text
        assert user_model.created_kwargs[0]["email"] is None
        # 全程不触邮件验证
        verification_model.create_code.assert_not_called()
        verification_model.verify_code.assert_not_called()


class TestSetupStatus:
    def test_setup_status_public_no_users(self, client, fake_models):
        """公开端点（无鉴权）: 无用户 → needs_setup=true"""
        user_model, _ = fake_models
        user_model.count_users.return_value = 0

        resp = client.get("/v1/auth/setup-status")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["needs_setup"] is True

    def test_setup_status_false_when_users_exist(self, client, fake_models):
        """已有用户 → needs_setup=false（已完成初始化）"""
        user_model, _ = fake_models
        user_model.count_users.return_value = 2

        resp = client.get("/v1/auth/setup-status")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["needs_setup"] is False
