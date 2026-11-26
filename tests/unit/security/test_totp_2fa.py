"""S8 TOTP 两步验证（2FA）红绿判据。

契约（任务卡 S8）：
- neurova/security/totp.py：RFC 6238 TOTP（HMAC-SHA1，默认 6 位，窗口 ±1），
  stdlib 自实现（hmac/hashlib/base64/struct），带 RFC 6238 测试向量
- users 表迁移（domain=auth_2fa）：totp_secret TEXT、two_factor_enabled
  INTEGER DEFAULT 0、recovery_codes_hash TEXT
- POST /api/v1/auth/2fa/setup    （需登录）生成 base32 secret + otpauth URL，暂存未启用
- POST /api/v1/auth/2fa/enable   （需登录）验码通过才启用，返回一次性恢复码明文
- POST /api/v1/auth/2fa/disable  （需登录）验码后关闭
- 登录链：密码通过且 two_factor_enabled → 200 {two_factor_required, challenge_token}
  （短时 JWT，scope 限 2fa，5 分钟，不当普通 token）；POST /api/v1/auth/2fa/verify
  {challenge_token, code} 验 TOTP 或恢复码（单次）→ 发正式 token 对
- 未启用 2FA 的用户登录链路零影响；challenge_token 不能当普通 token 用
"""

import base64
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET", "s8-totp-2fa-test-0123456789abcdef")

from neurova.api.endpoints import auth as AUTH  # noqa: E402
from neurova.api.endpoints import auth_2fa as AUTH2  # noqa: E402
from neurova.auth.user_model import UserModel  # noqa: E402
from neurova.core import db_migration  # noqa: E402
from neurova.security import totp as TOTP  # noqa: E402
from neurova.api.auth import hash_password  # noqa: E402

USER_PW = "Two-Fa-Pw-0001"


# ── RFC 6238 / RFC 4226 测试向量 ──────────────────────────────────────────

RFC_SECRET_ASCII = b"12345678901234567890"
#: RFC 6238 附录 B（SHA1，8 位，T0=0，X=30）
RFC6238_SHA1_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


class TestRfc6238Vectors:
    def test_rfc6238Sha1EightDigitVectors(self):
        for t, expected in RFC6238_SHA1_VECTORS:
            got = TOTP.totpAt(RFC_SECRET_ASCII, t, step=30, digits=8)
            assert got == expected, f"T={t}: 期望 {expected}，实得 {got}"

    def test_defaultSixDigitsUsesMod1e6(self):
        """6 位码 = 同一截断整数 mod 10^6（RFC 8 位向量的数值取模，非前 6 字符）。"""
        for t, expected8 in RFC6238_SHA1_VECTORS:
            expected6 = str(int(expected8) % (10 ** 6)).zfill(6)
            got = TOTP.totpAt(RFC_SECRET_ASCII, t, digits=6)
            assert got == expected6, f"T={t}: 期望 {expected6}，实得 {got}"

    def test_verifyAcceptsWindowNeighbors(self):
        """窗口 ±1：上一步/当前/下一步的码都通过；±2 之外的码拒绝。"""
        secret = TOTP.generateTotpSecret()
        raw = base64.b32decode(secret)
        now = 1_700_000_000
        current = TOTP.hotp(raw, now // 30, digits=6)
        prev = TOTP.hotp(raw, now // 30 - 1, digits=6)
        nxt = TOTP.hotp(raw, now // 30 + 1, digits=6)
        far = TOTP.hotp(raw, now // 30 + 2, digits=6)
        assert TOTP.verifyTotp(secret, current, now=now)
        assert TOTP.verifyTotp(secret, prev, now=now)
        assert TOTP.verifyTotp(secret, nxt, now=now)
        assert not TOTP.verifyTotp(secret, far, now=now)

    def test_verifyRejectsWrongAndMalformedCodes(self):
        secret = TOTP.generateTotpSecret()
        assert not TOTP.verifyTotp(secret, "000000", now=1_700_000_000)
        assert not TOTP.verifyTotp(secret, "abcdef", now=1_700_000_000)
        assert not TOTP.verifyTotp(secret, "", now=1_700_000_000)
        assert not TOTP.verifyTotp(secret, "12345", now=1_700_000_000)

    def test_generatedSecretIsBase32NoPadding(self):
        secret = TOTP.generateTotpSecret()
        assert "=" not in secret
        base64.b32decode(secret)  # 不抛即合法
        assert TOTP.generateTotpSecret() != TOTP.generateTotpSecret()

    def test_otpauthUrlShape(self):
        url = TOTP.otpauthUrl("JBSWY3DPEHPK3PXP", accountName="alice", issuer="Neurova")
        assert url.startswith("otpauth://totp/")
        assert "secret=JBSWY3DPEHPK3PXP" in url
        assert "issuer=Neurova" in url


# ── 端点与登录链 ──────────────────────────────────────────────────────────

@pytest.fixture()
def env2(tmp_path, monkeypatch):
    """真 auth + 2FA 路由 + tmp 真账本。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    model = UserModel(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(AUTH, "_user_model", model)

    app = FastAPI()
    app.include_router(AUTH.router, prefix="/api/v1/auth")
    app.include_router(AUTH2.router, prefix="/api/v1/auth/2fa")

    username = "twoFaUser"
    model.create_user(username=username, password_hash=hash_password(USER_PW), role="user")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"client": client, "model": model, "username": username}


def _login(env2):
    return env2["client"].post(
        "/api/v1/auth/login",
        json={"username": env2["username"], "password": USER_PW},
    )


def _codeFromSecret(secretB32: str, now: float | None = None) -> str:
    """按 setup 返回的 base32 secret 计算当前 TOTP 码（totpAt 吃原始字节）。"""
    import base64 as _b64

    key = _b64.b32decode(secretB32 + "=" * (-len(secretB32) % 8))
    return TOTP.totpAt(key, time.time() if now is None else now)


def _setupAndEnable(env2):
    """登录 → setup → 用 TOTP 码 enable。返回 (headers, recovery_codes)。"""
    client = env2["client"]
    login = _login(env2)
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    setup = client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_url"].startswith("otpauth://totp/")

    code = _codeFromSecret(secret)
    enable = client.post("/api/v1/auth/2fa/enable", json={"code": code}, headers=headers)
    assert enable.status_code == 200, enable.text
    recovery = enable.json().get("recovery_codes")
    assert isinstance(recovery, list) and len(recovery) == 10
    return headers, recovery, secret


def _accessHeadersAfterChallenge(env2, secret):
    client = env2["client"]
    login = _login(env2)
    assert login.status_code == 200, login.text
    challenge = login.json()["challenge_token"]
    verified = client.post(
        "/api/v1/auth/2fa/verify",
        json={"challenge_token": challenge, "code": _codeFromSecret(secret)},
    )
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['access_token']}"}


class TestTwoFactorEndpoints:
    def test_setupRequiresLogin(self, env2):
        resp = env2["client"].post("/api/v1/auth/2fa/setup")
        assert resp.status_code in (401, 403), "未登录不得进入 2FA 设置"

    def test_setupStagesSecretWithoutEnabling(self, env2):
        client, model = env2["client"], env2["model"]
        login = _login(env2)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        setup = client.post("/api/v1/auth/2fa/setup", headers=headers)
        assert setup.status_code == 200
        assert setup.json()["secret"] and setup.json()["otpauth_url"]
        user = model.get_user_by_username(env2["username"])
        assert user.totp_secret, "secret 应暂存"
        assert not user.two_factor_enabled, "setup 不得直接启用"

    def test_enableWithWrongCodeRejected(self, env2):
        client = env2["client"]
        login = _login(env2)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        setup = client.post("/api/v1/auth/2fa/setup", headers=headers)
        secret = setup.json()["secret"]
        bad = client.post("/api/v1/auth/2fa/enable", json={"code": "000000"}, headers=headers)
        assert bad.status_code in (400, 401), "错码不得启用"
        user = env2["model"].get_user_by_username(env2["username"])
        assert not user.two_factor_enabled

    def test_enableThenLoginChallengeThenVerify(self, env2):
        client, model = env2["client"], env2["model"]
        _setupAndEnable(env2)
        assert model.get_user_by_username(env2["username"]).two_factor_enabled

        # 密码通过 → 挑战（不发正式 token）
        login = _login(env2)
        assert login.status_code == 200, login.text
        body = login.json()
        assert body.get("two_factor_required") is True
        assert body.get("challenge_token")
        assert "access_token" not in body, "2FA 未完成前不得发正式 token"

        # challenge + 正确 TOTP 码 → 正式 token 对
        secret = model.get_user_by_username(env2["username"]).totp_secret
        code = _codeFromSecret(secret)
        verify = client.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": body["challenge_token"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        tokens = verify.json()
        assert tokens.get("access_token") and tokens.get("refresh_token")

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert me.status_code == 200
        assert me.json()["username"] == env2["username"]

    def test_verifyWithWrongCodeRejected(self, env2):
        client = env2["client"]
        _setupAndEnable(env2)
        login = _login(env2)
        challenge = login.json()["challenge_token"]
        verify = client.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": challenge, "code": "000000"},
        )
        assert verify.status_code in (400, 401), "错码必须拒绝"
        assert "access_token" not in verify.json()

    def test_verifyReplayRejected(self, env2):
        """同一 challenge+code 重放必须拒绝（challenge 一次性）。"""
        client, model = env2["client"], env2["model"]
        _setupAndEnable(env2)
        login = _login(env2)
        challenge = login.json()["challenge_token"]
        code = _codeFromSecret(model.get_user_by_username(env2["username"]).totp_secret)
        first = client.post("/api/v1/auth/2fa/verify", json={"challenge_token": challenge, "code": code})
        assert first.status_code == 200
        replay = client.post("/api/v1/auth/2fa/verify", json={"challenge_token": challenge, "code": code})
        assert replay.status_code in (400, 401), "challenge 消费后重放必须拒绝"

    def test_recoveryCodeWorksOnce(self, env2):
        client, model = env2["client"], env2["model"]
        _, recovery, _ = _setupAndEnable(env2)

        # 第一条恢复码：可用一次
        login1 = _login(env2)
        v1 = client.post("/api/v1/auth/2fa/verify",
                         json={"challenge_token": login1.json()["challenge_token"],
                               "code": recovery[0]})
        assert v1.status_code == 200, v1.text
        assert v1.json().get("access_token")
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {v1.json()['access_token']}"},
        )
        assert me.status_code == 200, me.text

        # 同一条恢复码：重放拒绝
        login2 = _login(env2)
        v2 = client.post("/api/v1/auth/2fa/verify",
                         json={"challenge_token": login2.json()["challenge_token"],
                               "code": recovery[0]})
        assert v2.status_code in (400, 401), "恢复码必须单次有效"

        # 第二条恢复码：仍可用
        login3 = _login(env2)
        v3 = client.post("/api/v1/auth/2fa/verify",
                         json={"challenge_token": login3.json()["challenge_token"],
                               "code": recovery[1]})
        assert v3.status_code == 200, v3.text

    def test_challengeTokenNotUsableAsNormalToken(self, env2):
        client = env2["client"]
        _setupAndEnable(env2)
        challenge = _login(env2).json()["challenge_token"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {challenge}"})
        assert me.status_code in (401, 403), "challenge_token 不得当 access token 用"

    def test_normalAccessTokenNotAcceptedAsChallenge(self, env2):
        client = env2["client"]
        headers, _, _ = _setupAndEnable(env2)
        token = headers["Authorization"].removeprefix("Bearer ")
        # setup 阶段的普通 access token 直接打 verify，必须被拒（scope/type 不符）。
        verify = client.post(
            "/api/v1/auth/2fa/verify", json={"challenge_token": token, "code": "123456"}
        )
        assert verify.status_code in (400, 401), "普通 access token 不得当 challenge 用"

    def test_passwordChangeInvalidatesOutstandingChallenge(self, env2):
        client, model = env2["client"], env2["model"]
        _, _, secret = _setupAndEnable(env2)
        login = _login(env2)
        challenge = login.json()["challenge_token"]
        user = model.get_user_by_username(env2["username"])
        model.update_user(user.id, password_hash=hash_password("Changed-TwoFa-Pw-0002"))

        verify = client.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": challenge, "code": _codeFromSecret(secret)},
        )
        assert verify.status_code in (400, 401), verify.text

    def test_revocationDuringChallengeUserReadRejected(self, env2, monkeypatch):
        client, model = env2["client"], env2["model"]
        _, _, secret = _setupAndEnable(env2)
        login = _login(env2)
        challenge = login.json()["challenge_token"]
        user = model.get_user_by_username(env2["username"])
        originalGetUser = model.get_user_by_id

        def revokeThenRead(userId):
            model.revoke_user_tokens(userId)
            return originalGetUser(userId)

        monkeypatch.setattr(model, "get_user_by_id", revokeThenRead)
        verify = client.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": challenge, "code": _codeFromSecret(secret)},
        )
        assert verify.status_code in (400, 401), verify.text

    def test_disabledUserLoginUnaffected(self, env2):
        """未启用 2FA 的用户：登录链路零影响（直接发正式 token 对）。"""
        client, model = env2["client"], env2["model"]
        model.create_user(username="plainUser", password_hash=hash_password(USER_PW), role="user")
        resp = client.post("/api/v1/auth/login", json={"username": "plainUser", "password": USER_PW})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("access_token") and body.get("refresh_token")
        assert "two_factor_required" not in body

    def test_disableTurnsOffChallenge(self, env2):
        client, model = env2["client"], env2["model"]
        _, _, secret = _setupAndEnable(env2)
        headers = _accessHeadersAfterChallenge(env2, secret)
        code = _codeFromSecret(secret)
        off = client.post("/api/v1/auth/2fa/disable", json={"code": code}, headers=headers)
        assert off.status_code == 200, off.text
        user = model.get_user_by_username(env2["username"])
        assert not user.two_factor_enabled
        assert not user.totp_secret

        # 关闭后登录直接发 token，不再挑战
        resp = _login(env2)
        assert resp.status_code == 200
        assert resp.json().get("access_token")
        assert "two_factor_required" not in resp.json()


class TestTwoFactorMigration:
    def test_usersTableHasTwoFactorColumns(self, tmp_path):
        model = UserModel(db_path=str(tmp_path / "users.db"))
        import sqlite3

        conn = sqlite3.connect(model.db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        finally:
            conn.close()
        assert {"totp_secret", "two_factor_enabled", "recovery_codes_hash"} <= cols

    def test_registeredInMigrationRegistry(self):
        assert db_migration.latest_version("auth_2fa") >= 1, \
            "2FA 列迁移必须登记进 db_migration 注册表（domain=auth_2fa）"
