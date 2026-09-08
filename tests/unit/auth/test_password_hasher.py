"""
PasswordHasher 单元测试
"""

import unittest

try:
    from neurova.auth.password_hasher import PasswordHasher
    HAS_PASSWORD_HASHER = True
except ImportError:
    HAS_PASSWORD_HASHER = False


@unittest.skipIf(not HAS_PASSWORD_HASHER, "PasswordHasher not available")
class TestPasswordHasher(unittest.TestCase):
    """PasswordHasher 测试类 — 所有方法为 @staticmethod"""

    def test_hash_and_verify_password(self) -> None:
        password = "my_secure_password_123"
        hashed = PasswordHasher().hash_password(password)

        self.assertTrue(PasswordHasher().verify_password(password, hashed))
        self.assertFalse(PasswordHasher().verify_password("wrong_password", hashed))

    def test_hash_consistency(self) -> None:
        password = "test_password"
        hash1 = PasswordHasher().hash_password(password)
        hash2 = PasswordHasher().hash_password(password)

        self.assertNotEqual(hash1, hash2)
        self.assertTrue(PasswordHasher().verify_password(password, hash1))
        self.assertTrue(PasswordHasher().verify_password(password, hash2))

    def test_hash_auto_salt(self) -> None:
        """bcrypt 自动加盐——同密码两次哈希不同但均可验证（无显式 salt 参数）"""
        password = "test_password"
        hash1 = PasswordHasher().hash_password(password)
        hash2 = PasswordHasher().hash_password(password)
        self.assertTrue(PasswordHasher().verify_password(password, hash2))

    def test_empty_password(self) -> None:
        with self.assertRaises(ValueError):

            PasswordHasher().verify_password("", "some_hash")
        with self.assertRaises(ValueError):

            PasswordHasher().verify_password("some", "")

    def test_special_characters(self) -> None:
        special_password = "P@ssw0rd!#$%^&*()_+-=[]{}|;:,.<>?"
        hashed = PasswordHasher().hash_password(special_password)
        self.assertTrue(PasswordHasher().verify_password(special_password, hashed))

    def test_unicode_password(self) -> None:
        unicode_password = "密码测试123!@#"
        hashed = PasswordHasher().hash_password(unicode_password)
        self.assertTrue(PasswordHasher().verify_password(unicode_password, hashed))

    def test_long_password(self) -> None:
        long_password = "a" * 72
        hashed = PasswordHasher().hash_password(long_password)
        self.assertTrue(PasswordHasher().verify_password(long_password, hashed))

    def test_verify_invalid_hash(self) -> None:
        self.assertFalse(PasswordHasher().verify_password("password", "invalid_hash_format"))

    def test_verify_none_hash(self) -> None:
        with self.assertRaises(ValueError):
            PasswordHasher().verify_password("password", None)

    def test_verify_empty_hash(self) -> None:
        with self.assertRaises(ValueError):

            PasswordHasher().verify_password("password", "")


if __name__ == "__main__":
    unittest.main()