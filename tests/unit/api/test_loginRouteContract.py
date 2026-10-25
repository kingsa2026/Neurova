# -*- coding: utf-8 -*-
"""`POST /v1/auth/login` 的回合契约（台账 §6-133 分流里判「补」的那一档）。

## 为什么这格不是顺手加的

`tests/auth/test_login_api.py` 是 §6-133 点名的 26 个「名字像覆盖、实则 0 用例」文件之一：
它对 `localhost:9527/api/v1/auth/login` 发一次真请求、把 token **print** 出来，
没有一条断言——所以"登录"这件事在 CI 里从来没有判据。复算现役替代时只找到：

- `tests/unit/api/test_global_auth_middleware.py:54` 断的是**白名单成员**（登录路径公开）；
- `tests/unit/api/test_api_auth.py:95` 断的是 **token 原语**（`create_token_pair` 的键）；
- `tests/e2e/test_mock_chat_e2e.py:147` 断的是登录成功，但**拿不到后端就 skip**。

三条都不断"用对的凭证登录 ⇒ 拿到能用、且带身份声明的 token"这一条链。
而这条链正是 P0-2 审计修复的落点（`auth.py:250-262`：token 必须带
`sub`/`neuser_id`/`user_id`，否则三层隔离第 2 层永远回退 `"default"`）——
一个会 skip 的 e2e 守不住这种回归。所以这个文件删不得，得补。

## 补出来的断言面，逐条对着生产代码

| 断言 | 生产落点 |
|---|---|
| 成功回 200 + `access_token`/`refresh_token` | `auth.py:216 @router.post("/login")`、`:272 TokenResponse` |
| token 里 `sub`/`neuser_id`/`user_id` 都是账号 id、`role` 随人 | `auth.py:252-262 identity_claims` |
| 口令错 ⇒ 401，且**不区分"用户不存在"与"口令错"** | `auth.py:230-236`（两句同一个 `Invalid credentials`） |
| 失败计数只在**用户存在**时才加 | `auth.py:233-235`（`if user_obj:`） |
| 停用 403 / 失败满 5 次锁定 403 | `auth.py:239-248` |
| 内部异常原文不回传 | `auth.py:279-283`（S-11） |
"""

import os
import uuid
from datetime import datetime, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

# 前提自给：本档**就地**钉住本轮的签名密钥，并把验签门一起对齐。
#
# 原先这两行 `setdefault("NEUROVA_JWT_SECRET_KEY", ...)` 实测对密钥**完全无效**：
# `neurova/api/auth.py:146` 读的是 `NEUROVA_JWT_SECRET`（无 `_KEY` 后缀），而
# `JWT_SECRET_KEY` 在 `auth.py:175` 导入期就烘死。真正生效的是下面那句直接赋常量——
# 它只覆盖了**签名侧**，`deps` 再导出的身份门是**函数对象**，读的是自己
# `__globals__` 里那份模块字典。进程里一旦出现第二份 auth 副本，两侧就各持一把密钥：
# 端点为登录签出令牌、门用另一把验，于是本档报 `InvalidSignatureError`。
# 与 `tests/unit/api/test_roleGateIdentitySourceIsStrict.py` 是同一处纪律。
os.environ["NEUROVA_JWT_SECRET"] = "test_secret_key_1234567890123456789012345678901234567890"
TEST_SECRET = os.environ["NEUROVA_JWT_SECRET"]

import neurova.api.endpoints.auth as authEndpoint  # noqa: E402
from neurova.api import auth as authModule  # noqa: E402
from neurova.api import deps as depsModule  # noqa: E402
from neurova.api.endpoints.auth import router  # noqa: E402


def _pinSecretToEveryGate() -> str:
    """把签名侧与全部验签门的密钥对齐到 `TEST_SECRET`，返回它。

    只改 `authModule.JWT_SECRET_KEY` 不够：身份门是函数对象，它们读的是自己
    `__globals__` 里的现值，改模块属性不会穿透过去。
    """
    if authModule.JWT_SECRET_KEY != TEST_SECRET:
        authModule.JWT_SECRET_KEY = TEST_SECRET
    for gate in (depsModule.strictIdentityGate, depsModule.get_current_user,
                 depsModule.get_optional_user):
        if gate.__globals__.get("JWT_SECRET_KEY") != TEST_SECRET:
            gate.__globals__["JWT_SECRET_KEY"] = TEST_SECRET
    return TEST_SECRET


_pinSecretToEveryGate()

ALGORITHM = authModule.JWT_ALGORITHM


def _user(**over):
    """`authenticate_user` 的返回形状（生产里是 dict，见 `auth.py:238` 起按 dict 取值）。"""
    data = {"id": 7, "username": "alice", "role": "user", "status": "active",
            "failed_attempts": 0}
    data.update(over)
    return data


@pytest.fixture()
def client():
    # 每个用例开始前重新对齐：端点这一轮签出的令牌，门必须在这一轮用同一把密钥验。
    _pinSecretToEveryGate()
    app = FastAPI()
    app.include_router(router, prefix="/v1/auth")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def userModel():
    """打桩 `auth.py:79` 那个 `_user_model` 单例槽（`lazySingleton` 的既有复位路径）。

    刻意走这条而不是 monkeypatch `_get_user_model` 本身：前者就是生产取用的那一格，
    换函数会让"取用侧"与"被测侧"不同源。
    """
    model = MagicMock()
    model.get_user_by_username.return_value = None
    model.authenticate_user.return_value = _user()
    model.increment_failed_attempts.return_value = True
    model.log_login.return_value = None

    previous = authEndpoint._user_model
    authEndpoint._user_model = model
    try:
        yield model
    finally:
        authEndpoint._user_model = previous


def _login(client, username="alice", password="Passw0rd!123"):
    _pinSecretToEveryGate()
    return client.post("/v1/auth/login", json={"username": username, "password": password})


class TestSuccessfulLoginCarriesIdentity:
    def test_returnsBothTokens(self, client, userModel):
        r = _login(client)

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["access_token"] and data["refresh_token"]
        assert data["token_type"] == "bearer"

    def test_accessTokenCarriesTheIdentityClaimsTheIsolationLayerNeeds(
            self, client, userModel):
        """P0-2 的实质：`neuser_id` 缺了，三层隔离第 2 层就永远回退 `"default"`。

        这条不能只断"字段存在"——`verify_access_token` 解不出来的人才会踩到这个坑，
        所以按真解码取真值断。
        """
        token = _login(client).json()["access_token"]

        payload = authModule.verify_access_token(token)

        assert payload, "签出来的 access_token 自己验不过——登录面与校验面不同源"
        assert payload["sub"] == "7"
        assert payload["neuser_id"] == "7"
        assert payload["user_id"] == "7"
        assert payload["role"] == "user"

    def test_roleComesFromTheUserRowNotAConstant(self, client, userModel):
        userModel.authenticate_user.return_value = _user(role="admin")

        payload = jwt.decode(_login(client).json()["access_token"], TEST_SECRET,
                             algorithms=[ALGORITHM])

        assert payload["role"] == "admin", (
            "登录把角色写死了——管理员会拿到一个 user token，角色门跟着失效")

    def test_refreshTokenDoesNotCarryRole(self, client, userModel):
        """刷新 token 只带身份不带权限：拿它当 access token 用的人不该有角色。"""
        token = _login(client).json()["refresh_token"]

        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])

        assert "role" not in payload, sorted(payload)


class TestRejectedLogins:
    def test_wrongPasswordIs401WithTheSameMessageAsUnknownUser(self, client, userModel):
        userModel.authenticate_user.return_value = None

        r = _login(client, username="alice", password="nope")

        assert r.status_code == 401, r.text
        assert "invalid credentials" in r.text.lower()

    def test_unknownUsernameGetsTheIdenticalResponse(self, client, userModel):
        """两个失败分支必须同形，否则登录面就成了"这个用户名存不存在"的oracle。"""
        userModel.authenticate_user.return_value = None

        known = _login(client, username="alice")
        userModel.get_user_by_username.return_value = MagicMock(id=7)
        unknown = _login(client, username="carol")

        assert known.status_code == unknown.status_code == 401
        assert known.json()["detail"] == unknown.json()["detail"]

    def test_failedAttemptsAreCountedOnlyWhenTheUserExists(self, client, userModel):
        userModel.authenticate_user.return_value = None
        userModel.get_user_by_username.return_value = MagicMock(id=7)

        _login(client, password="nope")

        userModel.increment_failed_attempts.assert_called_once_with(7)

    def test_noPhantomFailureRowForAnUnknownUsername(self, client, userModel):
        userModel.authenticate_user.return_value = None
        userModel.get_user_by_username.return_value = None

        _login(client, username="ghost")

        userModel.increment_failed_attempts.assert_not_called()

    def test_inactiveAccountIs403(self, client, userModel):
        userModel.authenticate_user.return_value = _user(status="inactive")

        r = _login(client)

        assert r.status_code == 403, r.text
        assert "inactive" in r.text.lower()

    def test_fiveFailedAttemptsLocksTheAccount(self, client, userModel):
        userModel.authenticate_user.return_value = _user(failed_attempts=5)

        r = _login(client)

        assert r.status_code == 403, r.text
        assert "locked" in r.text.lower()

    def test_lockedAccountIsCheckedAfterTheStatusCheck(self, client, userModel):
        """顺序也钉住：停用的人不该看到"locked"那句（会泄露"这账号还在被尝试"）。"""
        userModel.authenticate_user.return_value = _user(status="inactive", failed_attempts=9)

        r = _login(client)

        assert "inactive" in r.json()["detail"].lower()


class TestFailuresDoNotLeak:
    def test_internalErrorIsNotEchoedToTheClient(self, client, userModel):
        """S-11：`detail="Login failed"`，异常原文只进日志。"""
        userModel.authenticate_user.side_effect = RuntimeError("users.db is locked: /secret/path")

        r = _login(client)

        assert r.status_code == 500, r.text
        assert "users.db" not in r.text and "/secret/path" not in r.text, r.text

    def test_nothingIsWrittenToTheLoginLogOnFailure(self, client, userModel):
        userModel.authenticate_user.return_value = None

        _login(client, password="nope")

        userModel.log_login.assert_not_called()

    def test_successIsLoggedWithTheCallerContext(self, client, userModel):
        r = _login(client)

        assert r.status_code == 200
        kwargs = userModel.log_login.call_args.kwargs
        assert kwargs["user_id"] == 7
        assert kwargs["success"] is True

    def test_responseBodyCarriesNoCredentialMaterial(self, client, userModel):
        data = _login(client).json()

        assert set(data) == {"access_token", "refresh_token", "token_type", "expires_in"}, sorted(data)


class TestTheFixtureIsNotVacuous:
    """反向对照：桩没生效时这些格必须红——否则整档绿也只证明 MagicMock 自洽。"""

    def test_stubIsWhatTheEndpointReads(self, client, userModel):
        sentinel = "alice-" + uuid.uuid4().hex[:8]
        userModel.authenticate_user.return_value = _user(username=sentinel)

        payload = jwt.decode(_login(client).json()["access_token"], TEST_SECRET,
                             algorithms=[ALGORITHM])

        assert payload["username"] == sentinel, "端点没在读被打桩的那个 user_model（本档全部恒绿）"

    def test_expiresInMatchesTheTokensOwnExpiry(self, client, userModel):
        """响应里写的有效期必须就是 token 里那个 exp。

        断的不是某个魔法数字（那会把实现细节钉成契约），而是**同一个回复里两个读数互洽**——
        前端按 `expires_in` 安排刷新时，按它安排就会比 token 实际寿命早一步或晚一步。
        """
        data = _login(client).json()

        payload = jwt.decode(data["access_token"], TEST_SECRET, algorithms=[ALGORITHM])
        remaining = (datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
                     - datetime.now(timezone.utc)).total_seconds()

        assert abs(remaining - data["expires_in"]) <= 5, (
            "响应说能用 %ss，token 实际还剩 %ss —— 刷新时机按哪个都不对"
            % (data["expires_in"], round(remaining)))
