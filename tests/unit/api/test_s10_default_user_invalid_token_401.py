"""BUG AUDIT S-10 回归测试: get_current_user_or_default 无效凭证必须 401。

缺陷: 原实现对"无凭证"与"凭证无效(过期/伪造/黑名单)"都静默回落
_DEFAULT_USER → token 过期/伪造者变成共享 default 身份, 串改他人数据。

修复契约（桌面首启/登录前流程兼容）:
1. 完全无凭证 → 保留 _DEFAULT_USER 回落（200, user_id=default）;
2. 有凭证但无效（伪造/过期/已登出黑名单）→ 401;
3. 有效凭证 → 返回 token 内真实身份。

测试直接挂最小 FastAPI app, 不触发完整 lifespan。
"""
import os
from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s10_0123456789abcdef")

from neurova.api import auth as api_auth
from neurova.api.auth import blacklist_token, create_access_token, get_current_user_or_default


@pytest.fixture()
def client():
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user: dict = Depends(get_current_user_or_default)):
        return {"user_id": user.get("user_id"), "role": user.get("role")}

    return TestClient(app, raise_server_exceptions=False)


class TestNoCredentialFallsBackToDefault:
    def test_no_credentials_returns_default_user(self, client):
        """完全无凭证 → default 用户回落（桌面首启/登录前流程依赖, 行为不变）"""
        resp = client.get("/whoami")
        assert resp.status_code == 200, resp.text
        assert resp.json()["user_id"] == "default"


class TestInvalidCredentialsRejected:
    def test_forged_token_returns_401(self, client):
        """伪造 token（签名不合法）→ 401, 不再静默变 default"""
        resp = client.get("/whoami", headers={"Authorization": "Bearer not.a.valid.jwt"})
        assert resp.status_code == 401, resp.text

    def test_expired_token_returns_401(self, client):
        """过期 token → 401"""
        token = create_access_token(
            {"sub": "user-1", "username": "u1", "role": "user"},
            expires_delta=timedelta(seconds=-60),
        )
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, resp.text

    def test_blacklisted_token_returns_401(self, client):
        """已登出（黑名单）token → 401"""
        token = create_access_token({"sub": "user-1", "username": "u1", "role": "user"})
        blacklist_token(token)
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, resp.text


class TestValidCredentialsReturnIdentity:
    def test_valid_token_returns_real_identity(self, client):
        """有效 token → 真实身份而非 default"""
        token = create_access_token({"sub": "user-42", "username": "alice", "role": "user"})
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["user_id"] == "user-42"
