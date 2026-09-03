"""
BE-API-001 (P0) 安全修复测试: 无盐 SHA-256 密码验证漏洞

验证 verify_password 不再接受无盐 SHA-256 哈希。
无盐 SHA-256 可被彩虹表破解，必须拒绝。
"""

import hashlib
import os

import bcrypt
import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")
from neurova.api import auth


class TestVerifyPasswordRejectsUnsaltedSha256:
    """verify_password 必须拒绝无盐 SHA-256 哈希"""

    def test_unsalted_sha256_hash_rejected(self):
        """无盐 SHA-256 哈希应验证失败，不能作为回退"""
        password = "my_password_123"
        unsalted_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
        # 修复后：无盐 SHA-256 必须被拒绝
        assert auth.verify_password(password, unsalted_sha256) is False

    def test_unsalted_sha256_wrong_password_also_rejected(self):
        """即使密码错误，无盐 SHA-256 也应拒绝（不能部分接受）"""
        unsalted_sha256 = hashlib.sha256("any_password".encode("utf-8")).hexdigest()
        assert auth.verify_password("any_password", unsalted_sha256) is False
        assert auth.verify_password("wrong_password", unsalted_sha256) is False

    def test_bcrypt_hash_still_works(self):
        """bcrypt 哈希应正常验证"""
        password = "my_secure_password"
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        assert auth.verify_password(password, hashed) is True
        assert auth.verify_password("wrong", hashed) is False

    def test_pbkdf2_hash_still_works(self):
        """PBKDF2-SHA256 哈希应正常验证（bcrypt 不可用时的回退）"""
        import base64
        import secrets

        password = "my_pbkdf2_password"
        salt = secrets.token_bytes(16)
        iterations = 260000
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        hashed = f"pbkdf2:sha256:{iterations}:{base64.b64encode(salt).decode()}:{base64.b64encode(dk).decode()}"
        assert auth.verify_password(password, hashed) is True
        assert auth.verify_password("wrong", hashed) is False

    def test_empty_or_invalid_hash_rejected(self):
        """空或无效哈希应拒绝"""
        assert auth.verify_password("password", "") is False
        assert auth.verify_password("password", "not_a_valid_hash") is False
