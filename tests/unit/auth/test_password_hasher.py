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




class TestPasswordHasherDegradesWithoutBcrypt(unittest.TestCase):
    """bcrypt 缺席时模块必须仍可导入并按 PBKDF2 工作。

    缺陷（CI 实测，e2e-backend-boot 流水线红）：
    `neurova/auth/password_hasher.py` 曾在模块级硬 `import bcrypt`，而 e2e job
    按设计只装最小 import 面：`pip install -r requirements.txt --no-deps` +
    fastapi/uvicorn/...。requirements.txt 里写的是 `passlib[bcrypt]>=1.7.4`，
    但 --no-deps 不会解析 extra，实际只装 passlib 本体，bcrypt 必然缺席
    （已用 `pip download --no-deps 'passlib[bcrypt]'` 实测确认：只落 passlib 轮子）。

    于是 `tests/e2e/conftest.py` 的 `from neurova.auth.password_hasher import
    PasswordHasher` 在收集阶段就 ImportError，整条 boot 冒烟还没启动后端就
    exit 4 假红——门禁红的是"模块级硬导入与精简依赖前提冲突"，不是后端起不来。

    修复：模块级改为 try/except 可选导入 + 调用点降级 PBKDF2-SHA256，
    与 neurova/api/auth.py 的 hash_password 同格式同强度、可互认。

    本类用"屏蔽 bcrypt 导入"模拟 CI 环境，锁定降级行为不回归。
    """

    @staticmethod
    def _import_module_without_bcrypt():
        """在 bcrypt 不可导入的前提下重新加载目标模块，返回该模块。"""
        import builtins
        import importlib
        import sys

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "bcrypt" or name.startswith("bcrypt."):
                raise ImportError("No module named 'bcrypt'")
            return real_import(name, *args, **kwargs)

        saved = {
            k: v for k, v in sys.modules.items() if k.startswith("neurova.auth.password_hasher")
        }
        for k in saved:
            del sys.modules[k]
        builtins.__import__ = fake_import
        try:
            module = importlib.import_module("neurova.auth.password_hasher")
        finally:
            builtins.__import__ = real_import
            for k in list(sys.modules):
                if k.startswith("neurova.auth.password_hasher"):
                    del sys.modules[k]
            sys.modules.update(saved)
        return module

    def test_module_imports_without_bcrypt(self):
        """核心断言：bcrypt 缺席时 import 不得抛 ImportError（conftest 收集即红的那一步）。"""
        module = self._import_module_without_bcrypt()
        self.assertFalse(module.BCRYPT_AVAILABLE)
        self.assertIsNone(module.bcrypt)

    def test_pbkdf2_round_trip_when_bcrypt_absent(self):
        module = self._import_module_without_bcrypt()
        hasher = module.PasswordHasher()
        password = "Str0ng!Pass#2026"

        hashed = hasher.hash_password(password)
        self.assertTrue(hashed.startswith("pbkdf2:sha256:260000:"), hashed[:40])
        self.assertTrue(hasher.verify_password(password, hashed))
        self.assertFalse(hasher.verify_password("wrong-password", hashed))

    def test_hash_is_salted_when_bcrypt_absent(self):
        module = self._import_module_without_bcrypt()
        hasher = module.PasswordHasher()
        password = "same_password_twice"
        self.assertNotEqual(hasher.hash_password(password), hasher.hash_password(password))

    def test_pbkdf2_interops_with_api_auth(self):
        """降级产物必须能被 neurova.api.auth.verify_password 校验（同一格式）。"""
        module = self._import_module_without_bcrypt()
        from neurova.api.auth import verify_password as api_verify_password

        hasher = module.PasswordHasher()
        password = "Interop!Pass#2026"
        hashed = hasher.hash_password(password)

        self.assertTrue(api_verify_password(password, hashed))
        self.assertFalse(api_verify_password("nope", hashed))

    def test_rejects_unknown_and_unsalted_formats(self):
        """未知/无盐哈希一律拒绝，不静默回退到弱哈希。"""
        module = self._import_module_without_bcrypt()
        hasher = module.PasswordHasher()
        for bad in ("deadbeef", "pbkdf2:sha256:bad", "pbkdf2:sha256:1:2:3:4", "sha256$abc"):
            self.assertFalse(hasher.verify_password("pw", bad), bad)

    def test_non_hash_helpers_need_no_bcrypt(self):
        """generate_random_password / get_password_strength 不依赖 bcrypt 后端。"""
        module = self._import_module_without_bcrypt()
        hasher = module.PasswordHasher()
        generated = hasher.generate_random_password(16)
        self.assertTrue(hasher.is_password_strong(generated))
        self.assertTrue(hasher.get_password_strength(generated)["is_strong"])


if __name__ == "__main__":
    unittest.main()
