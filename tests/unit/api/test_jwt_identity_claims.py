"""JWT 身份声明测试

审计修复 (docs/audit/three-tier-isolation-audit.md P0-2 / Bug 6 / Bug 7):
- 登录/刷新/注册签发的 JWT 必须携带 neuser_id + user_id 声明,
  否则三层隔离的第 2 层 (neuser_id) 永远回退 "default", 事实上从未生效。
- get_current_user / get_optional_user / get_current_user_or_default
  返回值必须暴露 neuser_id, 旧 Token (无声明) 回退到 sub。
"""

import asyncio
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_jwt_claims_0123456789")

from fastapi.security import HTTPAuthorizationCredentials

from neurova.api import deps
from neurova.api import auth as auth_dep
from neurova.api.auth import create_access_token, create_refresh_token, decode_token
from neurova.api.endpoints import auth as auth_endpoint
from neurova.api.endpoints.auth import LoginRequest, RefreshRequest


class _FakeUserModel:
    """authenticate_user 返回固定用户 (id=42)"""

    def get_user_by_username(self, username):
        return {"id": 42, "username": "bob", "role": "user", "status": "active"}

    def authenticate_user(self, username, password):
        return {
            "id": 42,
            "username": "bob",
            "role": "user",
            "status": "active",
            "failed_attempts": 0,
        }

    def increment_failed_attempts(self, user_id):
        pass

    def log_login(self, **kwargs):
        pass

    def get_user_by_id(self, user_id):
        return SimpleNamespace(id=42, username="bob", role="user", status="active")


@pytest.fixture(autouse=True)
def fake_user_model(monkeypatch):
    monkeypatch.setattr(auth_endpoint, "_user_model", _FakeUserModel())


def _fake_request():
    return SimpleNamespace(client=None, headers={}, state=SimpleNamespace(request_id="test-req"))


class TestLoginWritesIdentityClaims:
    def test_login_token_contains_neuser_and_user_claims(self):
        resp = asyncio.run(
            auth_endpoint.login(_fake_request(), LoginRequest(username="bob", password="pw"))
        )
        payload = decode_token(resp.access_token)
        assert payload["neuser_id"] == "42"
        assert payload["user_id"] == "42"
        assert payload["sub"] == "42"

    def test_refresh_token_keeps_identity_claims(self):
        refresh = create_refresh_token(
            {"sub": "42", "username": "bob", "neuser_id": "42", "user_id": "42"}
        )
        resp = asyncio.run(
            auth_endpoint.refresh_token(_fake_request(), RefreshRequest(refresh_token=refresh))
        )
        payload = decode_token(resp.access_token)
        assert payload["neuser_id"] == "42"
        assert payload["user_id"] == "42"


class TestCurrentUserExposesNeuserId:
    def test_deps_get_current_user_returns_neuser_id(self):
        token = create_access_token(
            {"sub": "42", "username": "bob", "role": "user", "neuser_id": "42", "user_id": "42"}
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = asyncio.run(deps.get_current_user(creds))
        assert user["neuser_id"] == "42"
        assert user["user_id"] == "42"

    def test_deps_get_current_user_legacy_token_falls_back_to_sub(self):
        """存量 Token 无 neuser_id 声明: 回退 sub, 不再永远 default"""
        token = create_access_token({"sub": "42", "username": "bob", "role": "user"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = asyncio.run(deps.get_current_user(creds))
        assert user["neuser_id"] == "42"

    def test_deps_get_optional_user_returns_neuser_id(self):
        token = create_access_token(
            {"sub": "42", "username": "bob", "role": "user", "neuser_id": "42", "user_id": "42"}
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = asyncio.run(deps.get_optional_user(creds))
        assert user["neuser_id"] == "42"

    def test_auth_get_current_user_or_default_returns_neuser_id(self):
        token = create_access_token(
            {"sub": "42", "username": "bob", "role": "user", "neuser_id": "42", "user_id": "42"}
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = asyncio.run(auth_dep.get_current_user_or_default(creds))
        assert user["neuser_id"] == "42"
