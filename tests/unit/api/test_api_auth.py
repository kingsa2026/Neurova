"""
neurova/api/auth.py 测试

覆盖:
- JWT Token 生成与验证 (create_access_token, create_refresh_token, create_token_pair, verify_*)
- AuthError 异常
- get_token_subject
- hash_password / verify_password
"""
import os
import uuid
import bcrypt
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import jwt

os.environ["NEUROVA_JWT_SECRET_KEY"] = "test_secret_key_1234567890123456789012345678901234567890"
TEST_SECRET = os.environ["NEUROVA_JWT_SECRET_KEY"]

from neurova.api import auth

if auth.JWT_SECRET_KEY != TEST_SECRET:
    auth.JWT_SECRET_KEY = TEST_SECRET

ALGORITHM = auth.JWT_ALGORITHM


def _make_token(subject: str = "testuser", token_type: str = "access",
                extra: dict = None, secret: str = None) -> str:
    payload = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
        "role": "user",
        "username": subject,
        "neuser_id": "default",
        "user_id": "default",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret or TEST_SECRET, algorithm=ALGORITHM)


# ================================================================
# Token 生成 (new API: create_access_token takes a dict)
# ================================================================

class TestCreateAccessToken:
    def test_basic_token(self):
        token = auth.create_access_token({"sub": "alice"})
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload["sub"] == "alice"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_with_extra_claims(self):
        token = auth.create_access_token({"sub": "admin_user", "role": "admin", "org": "neurova"})
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"
        assert payload["org"] == "neurova"

    def test_custom_expiry(self):
        token = auth.create_access_token({"sub": "bob"}, expires_delta=timedelta(seconds=30))
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert 25 <= (exp - datetime.now(timezone.utc)).total_seconds() <= 35

    def test_unique_jti(self):
        t1 = auth.create_access_token({"sub": "alice"})
        t2 = auth.create_access_token({"sub": "alice"})
        p1 = jwt.decode(t1, TEST_SECRET, algorithms=[ALGORITHM])
        p2 = jwt.decode(t2, TEST_SECRET, algorithms=[ALGORITHM])
        assert p1["jti"] != p2["jti"]


class TestCreateRefreshToken:
    def test_basic_refresh_token(self):
        token = auth.create_refresh_token({"sub": "alice"})
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload["sub"] == "alice"

    def test_long_expiry(self):
        token = auth.create_refresh_token({"sub": "alice"})
        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert timedelta(days=6) <= (exp - datetime.now(timezone.utc)) <= timedelta(days=8)


class TestCreateTokenPair:
    def test_returns_both_tokens(self):
        pair = auth.create_token_pair({"sub": "alice"})
        assert "access_token" in pair
        assert "refresh_token" in pair


# ================================================================
# Token 验证 (new API: verify_token returns Optional[Dict], not raises)
# ================================================================

class TestVerifyToken:
    def test_verify_valid_access_token(self):
        token = auth.create_access_token({"sub": "alice"})
        payload = auth.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "alice"

    def test_verify_expired_token_returns_none(self):
        token = auth.create_access_token({"sub": "alice"}, expires_delta=timedelta(seconds=-1))
        result = auth.verify_token(token)
        assert result is None

    def test_verify_garbage_token_returns_none(self):
        result = auth.verify_token("this.is.not.a.jwt.token")
        assert result is None


class TestGetTokenSubject:
    def test_valid_token(self):
        token = auth.create_access_token({"sub": "alice"})
        assert auth.get_token_subject(token) == "alice"

    def test_garbage_returns_none(self):
        result = auth.get_token_subject("bad.token.here")
        assert result is None


# ================================================================
# 密码哈希
# ================================================================

class TestHashPassword:
    def test_hash_format(self):
        hashed = auth.hash_password("mypassword")
        assert hashed.startswith("$2b$")

    def test_hash_is_deterministically_different(self):
        h1 = auth.hash_password("same")
        h2 = auth.hash_password("same")
        assert h1 != h2

    def test_verify_success(self):
        hashed = auth.hash_password("mypassword")
        assert auth.verify_password("mypassword", hashed) is True

    def test_verify_failure(self):
        hashed = auth.hash_password("correct")
        assert auth.verify_password("wrong", hashed) is False


# ================================================================
# JWT_ALGORITHM 常量
# ================================================================

class TestAuthConstants:
    def test_algorithm(self):
        assert auth.JWT_ALGORITHM == "HS256"

    def test_access_token_expire_minutes(self):
        assert auth.ACCESS_TOKEN_EXPIRE_MINUTES > 0


# ================================================================
# AuthError 异常
# ================================================================

class TestAuthError:
    def test_is_exception(self):
        assert issubclass(auth.AuthError, Exception)

    def test_raise_and_catch(self):
        with pytest.raises(auth.AuthError, match="test error"):
            raise auth.AuthError("test error")


# ================================================================
# 自动生成密钥的进程内稳定性（构建 cnb-9g5-1k5q8mego#003 那族红的根）
# ================================================================

class TestGeneratedSecretIsStableWithinTheProcess:
    """数据根不可写时，密钥仍必须"同一进程只有一个答案"。

    形态：`_write_secret_file` 落盘失败只打一行 warning 就返回，而 `_load_or_create_secret_key`
    此前每次都 `token_hex()` 现生成一枚**新**密钥。于是「谁在什么时候取过密钥」决定了
    他签出的 token 能不能被别处验过——受保护子集里出现 `Invalid or expired token` 的
    那几格正是这条链断在"取两次得到两枚"上。

    判据取**行为**：同一进程内多次取、以及模块常量与重算值，必须是同一枚。
    """

    def _withUnwritableDataRoot(self, monkeypatch, tmp_path):
        """把数据根指到不可写处，并清掉可能盖过它的环境密钥。"""
        unwritable = tmp_path / "no-such-dir" / "deeper"
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(unwritable))
        monkeypatch.delenv("NEUROVA_JWT_SECRET", raising=False)
        monkeypatch.setattr(auth, "_generatedSecretKey", None, raising=False)

    def testRepeatedReadsAgree(self, monkeypatch, tmp_path):
        self._withUnwritableDataRoot(monkeypatch, tmp_path)
        values = [auth._load_or_create_secret_key() for _ in range(3)]
        assert len(set(values)) == 1, (
            f"数据根不可写时，同一进程连取三次拿到 {len(set(values))} 枚不同密钥："
            "签与验会因此各用一枚（受保护子集里表现为 401 Invalid or expired token）"
        )

    def testModuleConstantMatchesAFreshRead(self, monkeypatch, tmp_path):
        """模块常量必须就是**本进程按入口取到的那一枚**。

        重放一次 import 期的取值：先把常量复位成"还没定过"的状态，再按生产入口取一次，
        两者必须相等。此前落盘失败会让这次重算拿到另一枚——常量是 A、重算得 B，
        于是任何重新取密钥的消费方都签出验不过的 token。
        """
        self._withUnwritableDataRoot(monkeypatch, tmp_path)
        monkeypatch.setattr(auth, "JWT_SECRET_KEY", None, raising=False)
        fresh = auth._load_or_create_secret_key()
        monkeypatch.setattr(auth, "JWT_SECRET_KEY", fresh, raising=False)
        assert auth._load_or_create_secret_key() == auth.JWT_SECRET_KEY, (
            "模块常量与按入口重算的值不是同一枚——任何一处重新取密钥的消费方都会拿到"
            "另一枚，签出的 token 在别处验不过"
        )

    def testTokenSignedByTheGateVerifiesOnTheSameGate(self, monkeypatch, tmp_path):
        """端到端：同一进程里签出来的 token，按同一条入口必须验得回。"""
        self._withUnwritableDataRoot(monkeypatch, tmp_path)
        token = auth.create_access_token({"sub": "probe", "role": "admin"})
        assert auth.verify_access_token(token), (
            "同一进程里 create_access_token 签出的 token 验不过——"
            "这正是受保护子集那几格 401 的形态"
        )
