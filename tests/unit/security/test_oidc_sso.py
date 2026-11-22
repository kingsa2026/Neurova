"""S7 通用 OIDC SSO 红绿判据。

契约（任务卡 S7）：
- GET /api/v1/auth/oidc/status        → 公开暴露 {enabled}（未配置 IdP 时 enabled=False）
- GET /api/v1/auth/oidc/authorize     → 302 到 IdP authorize 端点（带 state+nonce，
  state 落短时存储）；未配置 → 503 诚实报缺
- GET /api/v1/auth/oidc/callback      → code 换 token → 校验 id_token（HS256，
  client_secret 即密钥；v1 选型理由见 auth_oidc.py 注释）→ 按 sub 供应用户
  （先按 oidc_sub 找人 → 无则按 email 绑定现有号 → 再无则建号，首用户即 admin）
  → 签发本仓 JWT 对（复用 neurova/api/auth.py 的签发函数）
- state / nonce 校验失败一律拒绝；sub 变化不串号
- users 表经 db_migration 注册表（domain=auth_oidc）获得 oidc_sub 列 + 索引

测试装配：进程内起极简假 IdP（真 HTTP socket，ThreadingHTTPServer），
签 HS256 id_token；后端用真 auth_oidc 路由 + tmp 真账本（UserModel）。
"""

import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET", "s7-oidc-sso-test-0123456789abcdef")

from neurova.api.endpoints import auth as AUTH  # noqa: E402
from neurova.api.endpoints import auth_oidc as OIDC  # noqa: E402
from neurova.auth.user_model import UserModel  # noqa: E402
from neurova.core import db_migration  # noqa: E402

ISSUER_PATH = "/.well-known/openid-configuration"
TOKEN_PATH = "/token"
JWKS_PATH = "/jwks"
CLIENT_ID = "neurova-test-client"
CLIENT_SECRET = "s7-client-secret-0123456789abcdef"


class FakeIdP:
    """极简 OIDC Provider：发现文档 + token 端点，签 HS256 id_token。

    仅服务本测试：不实现 authorize 端点本身（authorize 的 302 只校验
    Location，不真跳）；code 由用例经 issueCode() 预置。
    """

    def __init__(self, *, useRs256: bool = False):
        self.codes: dict = {}
        self._lock = threading.Lock()
        # RS256 模式：生成两把 RSA 私钥——_rsaKey 进 JWKS（正卡），
        # _altRsaKey 不进 JWKS（错签名用例里的"别人的钥匙"）。
        self.useRs256 = useRs256
        self.kid = "idp-rs-key-1"
        self._rsaKey = None
        self._altRsaKey = None
        if useRs256:
            from cryptography.hazmat.primitives.asymmetric import rsa

            self._rsaKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._altRsaKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._makeHandler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.port = self._server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def issuer(self) -> str:
        return self.base

    def jwksKeys(self) -> list:
        """JWKS 公钥集合（n/e 走 base64url 无 padding）；HS256 模式下为空集。"""
        if not self.useRs256:
            return []
        import base64

        numbers = self._rsaKey.public_key().public_numbers()

        def b64urlUint(value: int) -> str:
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        return [{
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": b64urlUint(numbers.n),
            "e": b64urlUint(numbers.e),
        }]

    def issueCode(self, sub: str, email: str = "", nonce: str = "", *,
                  tamperKey: str = "", extraClaims: dict | None = None,
                  alg: str = "HS256", kid: str | None = None,
                  wrongSigner: bool = False) -> str:
        """预置一个授权码；换 token 时以此签 id_token。

        tamperKey 非空时用错钥签名（HS256）；alg/kid/wrongSigner 控制 RS256
        签发形态：kid=None 用本 IdP 正牌 kid、kid="" 表示 header 不带 kid、
        wrongSigner=True 用未入 JWKS 的另一把钥签名。
        """
        code = "code-" + uuid.uuid4().hex
        with self._lock:
            self.codes[code] = {
                "sub": sub,
                "email": email,
                "nonce": nonce,
                "tamperKey": tamperKey,
                "extraClaims": extraClaims or {},
                "alg": alg,
                "kid": kid,
                "wrongSigner": wrongSigner,
            }
        return code

    def _makeHandler(self):
        idp = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # 静默访问日志
                pass

            def _json(self, payload: dict, status: int = 200):
                import json as _json

                body = _json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if urlparse(self.path).path == ISSUER_PATH:
                    algs = ["HS256", "RS256"] if idp.useRs256 else ["HS256"]
                    self._json({
                        "issuer": idp.issuer(),
                        "authorization_endpoint": idp.base + "/authorize",
                        "token_endpoint": idp.base + TOKEN_PATH,
                        "jwks_uri": idp.base + JWKS_PATH,
                        "id_token_signing_alg_values_supported": algs,
                    })
                elif urlparse(self.path).path == JWKS_PATH:
                    self._json({"keys": idp.jwksKeys()})
                else:
                    self._json({"error": "not_found"}, 404)

            def do_POST(self):
                if urlparse(self.path).path != TOKEN_PATH:
                    self._json({"error": "not_found"}, 404)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                code = (form.get("code") or [""])[0]
                with idp._lock:
                    entry = idp.codes.pop(code, None)
                if entry is None:
                    self._json({"error": "invalid_grant"}, 400)
                    return
                now = int(time.time())
                claims = {
                    "iss": idp.issuer(),
                    "sub": entry["sub"],
                    "aud": CLIENT_ID,
                    "exp": now + 300,
                    "iat": now,
                    "nonce": entry["nonce"],
                }
                if entry["email"]:
                    claims["email"] = entry["email"]
                claims.update(entry["extraClaims"])
                alg = entry.get("alg") or "HS256"
                if alg == "RS256":
                    signKey = idp._altRsaKey if entry.get("wrongSigner") else idp._rsaKey
                    headers: dict = {}
                    kidParam = entry.get("kid")
                    if kidParam is None:
                        headers["kid"] = idp.kid
                    elif kidParam:
                        headers["kid"] = kidParam  # "" → header 刻意不带 kid
                    id_token = jwt.encode(claims, signKey, algorithm="RS256", headers=headers)
                elif alg == "none":
                    id_token = jwt.encode(claims, None, algorithm="none")
                else:
                    key = entry["tamperKey"] or CLIENT_SECRET
                    id_token = jwt.encode(claims, key, algorithm="HS256")
                self._json({
                    "access_token": "idp-access-" + uuid.uuid4().hex,
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "id_token": id_token,
                })

        return Handler


@pytest.fixture()
def idp():
    server = FakeIdP()
    server.start()
    yield server
    server.stop()


@pytest.fixture()
def rsIdp():
    server = FakeIdP(useRs256=True)
    server.start()
    yield server
    server.stop()


@pytest.fixture()
def env(idp, tmp_path, monkeypatch):
    """真 OIDC 路由 + 真 auth 路由（/me）+ tmp 真账本 + 假 IdP（HS256）环境变量。"""
    yield from _oidcEnv(idp, tmp_path, monkeypatch)


@pytest.fixture()
def rsEnv(rsIdp, tmp_path, monkeypatch):
    """同 env，但 IdP 以 RS256 签 id_token 并暴露 JWKS 端点。"""
    yield from _oidcEnv(rsIdp, tmp_path, monkeypatch)


def _oidcEnv(idp, tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_OIDC_ISSUER", idp.issuer())
    monkeypatch.setenv("NEUROVA_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("NEUROVA_OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.delenv("NEUROVA_OIDC_SCOPES", raising=False)
    monkeypatch.delenv("NEUROVA_OIDC_REDIRECT_URI", raising=False)

    model = UserModel(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(AUTH, "_user_model", model)

    for cacheName in ("_discoveryCache", "_jwksCache"):
        cache = getattr(OIDC, cacheName, None)
        if cache is not None:
            cache.clear()

    app = FastAPI()
    app.include_router(OIDC.router, prefix="/api/v1/auth/oidc")
    app.include_router(AUTH.router, prefix="/api/v1/auth")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"client": client, "model": model, "idp": idp}


def _authorize(client: TestClient):
    return client.get("/api/v1/auth/oidc/authorize", follow_redirects=False)


def _stateAndNonceFrom(location: str):
    q = parse_qs(urlparse(location).query)
    return (q.get("state", [""])[0], q.get("nonce", [""])[0])


def _completeLogin(env, sub: str, email: str = "", *, tamperKey: str = "",
                   stateOverride: str = "", nonceOverride: str | None = None,
                   codeOverride: str = "", codeKwargs: dict | None = None):
    """走完整链路：authorize → 假 IdP 发码 → callback。返回 (callback 响应, state)。

    codeKwargs 透传给 issueCode（RS256 用例的 alg/kid/wrongSigner 走这里）。
    """
    client = env["client"]
    resp = _authorize(client)
    assert resp.status_code in (302, 307), resp.text
    state, nonce = _stateAndNonceFrom(resp.headers["location"])
    if stateOverride:
        state = stateOverride
    if nonceOverride is not None:
        nonce = nonceOverride
    code = codeOverride or env["idp"].issueCode(sub=sub, email=email, nonce=nonce,
                                                tamperKey=tamperKey, **(codeKwargs or {}))
    cb = client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )
    return cb, state


class TestOidcStatus:
    def test_enabledWhenConfigured(self, env):
        resp = env["client"].get("/api/v1/auth/oidc/status")
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is True

    def test_disabledWhenUnconfigured(self, env, monkeypatch):
        monkeypatch.delenv("NEUROVA_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("NEUROVA_OIDC_CLIENT_ID", raising=False)
        monkeypatch.delenv("NEUROVA_OIDC_CLIENT_SECRET", raising=False)
        resp = env["client"].get("/api/v1/auth/oidc/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False


class TestOidcFullFlow:
    def test_authorizeRedirectsToIdpWithStateAndNonce(self, env):
        resp = _authorize(env["client"])
        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert location.startswith(env["idp"].base + "/authorize"), location
        q = parse_qs(urlparse(location).query)
        assert q["response_type"] == ["code"]
        assert q["client_id"] == [CLIENT_ID]
        assert q["scope"] == ["openid profile email"]
        assert q["state"] and q["nonce"], "必须带 state 与 nonce"

    def test_authorize503WhenUnconfigured(self, env, monkeypatch):
        monkeypatch.delenv("NEUROVA_OIDC_ISSUER", raising=False)
        resp = _authorize(env["client"])
        assert resp.status_code == 503, resp.text
        assert "NEUROVA_OIDC_ISSUER" in resp.text or "issuer" in resp.text.lower()

    def test_callbackIssuesRepoJwtAndMeWorks(self, env):
        cb, _ = _completeLogin(env, sub="sub-alice-1", email="alice@example.com")
        assert cb.status_code == 200, cb.text
        data = cb.json().get("data") or cb.json()
        assert data.get("access_token") and data.get("refresh_token")

        me = env["client"].get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
        )
        assert me.status_code == 200, me.text
        assert me.json()["username"] == "alice"

        user = env["model"].get_user_by_oidc_sub("sub-alice-1")
        assert user is not None, "id_token sub 必须落库（oidc_sub）"
        assert user.email == "alice@example.com"

    def test_firstOidcUserBecomesAdmin(self, env):
        cb, _ = _completeLogin(env, sub="sub-founder", email="founder@example.com")
        assert cb.status_code == 200, cb.text
        user = env["model"].get_user_by_oidc_sub("sub-founder")
        assert user.role == "admin", "系统无用户时 OIDC 首个供应用户即管理员"

    def test_sameSubReusesSameAccount(self, env):
        cb1, _ = _completeLogin(env, sub="sub-stable", email="stable@example.com")
        cb2, _ = _completeLogin(env, sub="sub-stable", email="stable@example.com")
        assert cb1.status_code == cb2.status_code == 200
        id1 = env["model"].get_user_by_oidc_sub("sub-stable").id
        me2 = env["client"].get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {(cb2.json().get('data') or cb2.json())['access_token']}"},
        )
        assert me2.status_code == 200
        assert str(me2.json()["user_id"]) == str(id1), "同一 sub 必须落回同一账号"
        assert env["model"].count_users() == 1

    def test_emailBindsExistingAccount(self, env):
        """无 sub 命中时按 email 绑定现有号（不建新号）。"""
        model = env["model"]
        from neurova.api.auth import hash_password

        model.create_user(username="legacy-alice",
                          password_hash=hash_password("Legacy-Pw-0001"),
                          email="alice@example.com", role="user")
        cb, _ = _completeLogin(env, sub="sub-new-bind", email="alice@example.com")
        assert cb.status_code == 200, cb.text
        assert model.count_users() == 1, "email 命中现有号时不得另建账号"
        bound = model.get_user_by_oidc_sub("sub-new-bind")
        assert bound is not None and bound.username == "legacy-alice"

    def test_subChangeDoesNotCrossAccounts(self, env):
        """sub 变化（无 email 命中）必须落到不同账号，不得串进他人会话。"""
        cb1, _ = _completeLogin(env, sub="sub-userA", email="a@example.com")
        cb2, _ = _completeLogin(env, sub="sub-userB", email="b@example.com")
        assert cb1.status_code == cb2.status_code == 200
        tokA = (cb1.json().get("data") or cb1.json())["access_token"]
        tokB = (cb2.json().get("data") or cb2.json())["access_token"]
        meA = env["client"].get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokA}"})
        meB = env["client"].get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokB}"})
        assert meA.json()["user_id"] != meB.json()["user_id"], "不同 sub 必须是不同账号"
        assert meA.json()["username"] == "a"
        assert meB.json()["username"] == "b"

    def test_stateReplayRejected(self, env):
        """state 一次性：重放同一 state 的 callback 必须拒绝。"""
        client = env["client"]
        resp = _authorize(client)
        state, nonce = _stateAndNonceFrom(resp.headers["location"])
        code = env["idp"].issueCode(sub="sub-once", email="once@example.com", nonce=nonce)
        first = client.get("/api/v1/auth/oidc/callback",
                           params={"code": code, "state": state}, follow_redirects=False)
        assert first.status_code == 200, first.text
        replay = client.get("/api/v1/auth/oidc/callback",
                            params={"code": code, "state": state}, follow_redirects=False)
        assert replay.status_code in (400, 401), "已消费的 state 重放必须被拒绝"

    def test_unknownStateRejected(self, env):
        code = env["idp"].issueCode(sub="sub-x", email="x@example.com", nonce="n")
        cb = env["client"].get("/api/v1/auth/oidc/callback",
                               params={"code": code, "state": "forged-state"},
                               follow_redirects=False)
        assert cb.status_code in (400, 401), cb.text

    def test_badNonceRejected(self, env):
        cb, _ = _completeLogin(env, sub="sub-nonce", email="nonce@example.com",
                               nonceOverride="attacker-nonce")
        assert cb.status_code in (400, 401), "id_token nonce 与 authorize 发出的不一致必须拒绝"

    def test_tamperedIdTokenRejected(self, env):
        cb, _ = _completeLogin(env, sub="sub-tamper", email="tamper@example.com",
                               tamperKey="wrong-key-0123456789abcdef")
        assert cb.status_code in (400, 401), "签名校验失败（错钥 id_token）必须拒绝"


class TestOidcMigration:
    def test_usersTableHasOidcSubColumnAndIndex(self, tmp_path):
        model = UserModel(db_path=str(tmp_path / "users.db"))
        import sqlite3

        conn = sqlite3.connect(model.db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            indexes = {r[1] for r in conn.execute("PRAGMA index_list(users)").fetchall()}
        finally:
            conn.close()
        assert "oidc_sub" in cols
        assert "idx_users_oidc_sub" in indexes

    def test_registeredInMigrationRegistry(self):
        assert db_migration.latest_version("auth_oidc") >= 1, \
            "oidc_sub 列迁移必须登记进 db_migration 注册表（domain=auth_oidc）"


class TestOidcSqliteState:
    """卡 1：authorize state 落 users.db（oidc_states 表，多 worker 共享）。"""

    def test_stateCrossesWorkerInstances(self, idp, tmp_path, monkeypatch):
        """同一 users.db、两个独立 app 实例：A authorize → B callback 成功。"""
        import hashlib
        import sqlite3

        monkeypatch.setenv("NEUROVA_OIDC_ISSUER", idp.issuer())
        monkeypatch.setenv("NEUROVA_OIDC_CLIENT_ID", CLIENT_ID)
        monkeypatch.setenv("NEUROVA_OIDC_CLIENT_SECRET", CLIENT_SECRET)
        model = UserModel(db_path=str(tmp_path / "users.db"))
        monkeypatch.setattr(AUTH, "_user_model", model)

        def buildApp():
            app = FastAPI()
            app.include_router(OIDC.router, prefix="/api/v1/auth/oidc")
            return app

        with TestClient(buildApp(), raise_server_exceptions=False) as workerA, \
                TestClient(buildApp(), raise_server_exceptions=False) as workerB:
            resp = workerA.get("/api/v1/auth/oidc/authorize", follow_redirects=False)
            assert resp.status_code in (302, 307), resp.text
            state, nonce = _stateAndNonceFrom(resp.headers["location"])

            # state 必须落 SQLite 的 oidc_states 表，且只存 sha256 摘要、不落原文
            conn = sqlite3.connect(model.db_path)
            try:
                rows = conn.execute("SELECT state_hash, nonce FROM oidc_states").fetchall()
            finally:
                conn.close()
            assert len(rows) == 1, "state 必须持久化进 oidc_states 表"
            assert rows[0][0] == hashlib.sha256(state.encode()).hexdigest(), \
                "表里必须是 sha256(state)，不是原文"
            assert rows[0][1] == nonce
            assert state not in str(rows), "state 原文不得落库"

            code = idp.issueCode(sub="sub-worker", email="worker@example.com", nonce=nonce)
            cb = workerB.get("/api/v1/auth/oidc/callback",
                             params={"code": code, "state": state}, follow_redirects=False)
            assert cb.status_code == 200, f"另一 worker 实例必须能消费同一 state：{cb.text}"

    def test_expiredStateRejected(self, env):
        """TTL 600s：created_at 拨老后的 state 必须拒绝。"""
        import sqlite3

        client, model = env["client"], env["model"]
        resp = _authorize(client)
        assert resp.status_code in (302, 307), resp.text
        state, nonce = _stateAndNonceFrom(resp.headers["location"])
        code = env["idp"].issueCode(sub="sub-expired", email="expired@example.com", nonce=nonce)

        conn = sqlite3.connect(model.db_path)
        try:
            conn.execute("UPDATE oidc_states SET created_at = created_at - 601")
            conn.commit()
        finally:
            conn.close()

        cb = client.get("/api/v1/auth/oidc/callback",
                        params={"code": code, "state": state}, follow_redirects=False)
        assert cb.status_code in (400, 401), "过期 state 必须被拒绝"


class TestOidcRs256Jwks:
    """卡 2：id_token RS256/JWKS 验签（kid 匹配；错 kid/错签名/错 alg 拒绝）。"""

    def test_rs256IdTokenAcceptedEndToEnd(self, rsEnv):
        cb, _ = _completeLogin(rsEnv, sub="sub-rs-alice", email="rs-alice@example.com",
                               codeKwargs={"alg": "RS256"})
        assert cb.status_code == 200, cb.text
        data = cb.json().get("data") or cb.json()
        assert data.get("access_token") and data.get("refresh_token")
        me = rsEnv["client"].get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
        )
        assert me.status_code == 200, me.text
        assert me.json()["username"] == "rs-alice"

    def test_rs256MissingKidRejected(self, rsEnv):
        cb, _ = _completeLogin(rsEnv, sub="sub-rs-nokid", email="nokid@example.com",
                               codeKwargs={"alg": "RS256", "kid": ""})
        assert cb.status_code in (400, 401), "header 不带 kid 必须诚实拒绝"

    def test_rs256WrongKidRejected(self, rsEnv):
        cb, _ = _completeLogin(rsEnv, sub="sub-rs-badkid", email="badkid@example.com",
                               codeKwargs={"alg": "RS256", "kid": "rotated-away-key"})
        assert cb.status_code in (400, 401), "kid 与 JWKS 公钥不匹配必须拒绝"

    def test_rs256WrongSignatureRejected(self, rsEnv):
        cb, _ = _completeLogin(rsEnv, sub="sub-rs-badsig", email="badsig@example.com",
                               codeKwargs={"alg": "RS256", "wrongSigner": True})
        assert cb.status_code in (400, 401), "未入 JWKS 的私钥签名必须拒绝"

    def test_unsupportedAlgRejected(self, rsEnv):
        cb, _ = _completeLogin(rsEnv, sub="sub-rs-alg", email="badalg@example.com",
                               codeKwargs={"alg": "none"})
        assert cb.status_code in (400, 401), "alg=none 等未支持算法必须诚实拒绝"
