"""P2.2 架构重复修复 — 统一 NEUTokenManager 接口测试

修复两个 NEUTokenManager 实现的架构重复:
  - neurova/auth.py (死代码, 被同名包遮蔽, 无法导入)
  - neurova/security/neu_token_manager.py (被 api/app.py 使用)

合并方案: 在 security/neu_token_manager.py 中实现统一接口,
合并 auth.py 的安全特性 (HMAC-SHA256签名, refresh token, 黑名单, 线程安全)
和 security/ 的 API Key 管理功能。

向后兼容: NEUTokenManager() 无参构造必须继续工作 (api/app.py 依赖)。
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from neurova.security.neu_token_manager import NEUTokenManager


@pytest.fixture
def manager():
    """提供独立的 NEUTokenManager 实例"""
    return NEUTokenManager(secret_key="test_secret_key_for_unified_interface")


# ────── 向后兼容: 无参构造 ──────


class TestBackwardCompatibility:
    """验证 api/app.py 的 NEUTokenManager() 无参调用仍可工作"""

    def test_no_args_constructor(self):
        """无参构造必须成功 (api/app.py:251 依赖)"""
        m = NEUTokenManager()
        assert m is not None

    def test_secret_key_only(self):
        """仅 secret_key 参数"""
        m = NEUTokenManager(secret_key="my_secret")
        assert m is not None

    def test_full_args(self):
        """完整参数 (auth.py 风格)"""
        m = NEUTokenManager(
            secret_key="secret",
            access_token_ttl=1800,
            refresh_token_ttl=86400,
            issuer="test_issuer",
        )
        assert m is not None


# ────── 简单令牌 (security/ 原有功能) ──────


class TestSimpleToken:
    """验证简单令牌功能 (security/ 原有, 保持兼容)"""

    def test_generate_token_returns_string(self, manager):
        token = manager.generate_token("user_123")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_validate_valid_token(self, manager):
        token = manager.generate_token("user_123", metadata={"role": "admin"})
        result = manager.validate_token(token)
        assert result is not None
        assert result["user_id"] == "user_123"

    def test_validate_invalid_token(self, manager):
        result = manager.validate_token("invalid_token")
        assert result is None

    def test_revoke_token(self, manager):
        token = manager.generate_token("user_123")
        assert manager.revoke_token(token) is True
        assert manager.validate_token(token) is None


# ────── JWT 签名令牌对 (auth.py 安全特性) ──────


class TestJWTTokenPair:
    """验证 JWT 签名令牌对功能 (从 auth.py 合并)"""

    def test_generate_tokens_returns_tuple(self, manager):
        """generate_tokens 应返回 (access_token, refresh_token, token_info)"""
        result = manager.generate_tokens("user_123")
        assert isinstance(result, tuple)
        assert len(result) == 3
        access_token, refresh_token, token_info = result
        assert isinstance(access_token, str)
        assert isinstance(refresh_token, str)
        assert isinstance(token_info, dict)
        assert len(access_token) > 0
        assert len(refresh_token) > 0

    def test_generate_tokens_with_extra_claims(self, manager):
        """generate_tokens 应支持 extra_claims"""
        access, refresh, info = manager.generate_tokens(
            "user_123", extra_claims={"role": "admin", "scope": "read"}
        )
        # 验证 JWT 令牌可以解码出 extra_claims
        payload = manager.validate_token(access)
        assert payload is not None
        assert payload.get("role") == "admin"
        assert payload.get("scope") == "read"

    def test_jwt_token_has_three_parts(self, manager):
        """JWT 令牌应有 header.payload.signature 三部分"""
        access, _, _ = manager.generate_tokens("user_123")
        parts = access.split(".")
        assert len(parts) == 3

    def test_validate_jwt_token(self, manager):
        """validate_token 应能验证 JWT 令牌"""
        access, _, _ = manager.generate_tokens("user_123")
        payload = manager.validate_token(access)
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["type"] == "access"

    def test_validate_tampered_jwt_returns_none(self, manager):
        """篡改的 JWT 令牌应验证失败"""
        access, _, _ = manager.generate_tokens("user_123")
        # 篡改 payload 部分
        parts = access.split(".")
        tampered = f"{parts[0]}.tampered_payload.{parts[2]}"
        assert manager.validate_token(tampered) is None

    def test_revoke_jwt_token(self, manager):
        """revoke_token 应能撤销 JWT 令牌 (加入黑名单)"""
        access, _, _ = manager.generate_tokens("user_123")
        assert manager.revoke_token(access) is True
        assert manager.validate_token(access) is None


# ────── Refresh Token (auth.py 安全特性) ──────


class TestRefreshToken:
    """验证刷新令牌功能 (从 auth.py 合并)"""

    def test_refresh_tokens_returns_new_pair(self, manager):
        """refresh_tokens 应返回新的令牌对"""
        access, refresh, _ = manager.generate_tokens("user_123")
        result = manager.refresh_tokens(refresh)
        assert result is not None
        new_access, new_refresh, new_info = result
        assert new_access != access
        assert new_refresh != refresh

    def test_refresh_with_access_token_fails(self, manager):
        """用访问令牌刷新应失败"""
        access, _, _ = manager.generate_tokens("user_123")
        result = manager.refresh_tokens(access)
        assert result is None

    def test_refresh_revokes_old_access_token(self, manager):
        """刷新后旧访问令牌应被撤销"""
        access, refresh, _ = manager.generate_tokens("user_123")
        manager.refresh_tokens(refresh)
        assert manager.validate_token(access) is None


# ────── 黑名单 (auth.py 安全特性) ──────


class TestBlacklist:
    """验证令牌黑名单功能 (从 auth.py 合并)"""

    def test_revoke_token_by_jti(self, manager):
        """revoke_token_by_jti 应将 JTI 加入黑名单"""
        access, _, info = manager.generate_tokens("user_123")
        access_jti = info["access_jti"]
        assert manager.revoke_token_by_jti(access_jti) is True
        assert manager.is_token_blacklisted(access_jti) is True
        assert manager.validate_token(access) is None

    def test_is_token_blacklisted_false_for_unknown(self, manager):
        """未知 JTI 不在黑名单中"""
        assert manager.is_token_blacklisted("unknown_jti") is False

    def test_revoke_already_revoked_returns_false(self, manager):
        """重复撤销应返回 False"""
        access, _, info = manager.generate_tokens("user_123")
        jti = info["access_jti"]
        assert manager.revoke_token_by_jti(jti) is True
        assert manager.revoke_token_by_jti(jti) is False


# ────── API Key 管理 (security/ 原有功能) ──────


class TestAPIKeyManagement:
    """验证 API Key 管理功能 (security/ 原有, 保持兼容)"""

    def test_generate_api_key(self, manager):
        api_key = manager.generate_api_key("user_123", "test_key")
        assert isinstance(api_key, str)
        assert len(api_key) > 0

    def test_validate_api_key(self, manager):
        api_key = manager.generate_api_key("user_123", "test_key", scopes=["read"])
        result = manager.validate_api_key(api_key)
        assert result is not None
        assert result["user_id"] == "user_123"
        assert "read" in result["scopes"]

    def test_validate_invalid_api_key(self, manager):
        assert manager.validate_api_key("invalid_key") is None

    def test_revoke_api_key(self, manager):
        api_key = manager.generate_api_key("user_123", "test_key")
        assert manager.revoke_api_key(api_key) is True
        assert manager.validate_api_key(api_key) is None

    def test_list_api_keys(self, manager):
        manager.generate_api_key("user_123", "key1")
        manager.generate_api_key("user_123", "key2")
        keys = manager.list_api_keys("user_123")
        assert isinstance(keys, list)
        assert len(keys) >= 2


# ────── 清理 (合并两者) ──────


class TestCleanup:
    """验证清理功能 (合并两者)"""

    def test_cleanup_expired_tokens_returns_int(self, manager):
        """cleanup_expired_tokens 清理简单令牌 (security/ 兼容)"""
        result = manager.cleanup_expired_tokens()
        assert isinstance(result, int)

    def test_cleanup_expired_returns_int(self, manager):
        """cleanup_expired 清理黑名单和刷新令牌 (auth/ 兼容)"""
        result = manager.cleanup_expired()
        assert isinstance(result, int)

    def test_cleanup_removes_expired_blacklist_entries(self, manager):
        """cleanup_expired 应清理过期的黑名单条目"""
        # 生成并撤销一个令牌
        access, _, info = manager.generate_tokens("user_123")
        jti = info["access_jti"]
        manager.revoke_token_by_jti(jti, expires_at=time.time() - 1)  # 已过期
        assert manager.is_token_blacklisted(jti) is False  # 过期后自动清理

    def test_cleanup_removes_expired_refresh_tokens(self, manager):
        """cleanup_expired 应清理过期的刷新令牌"""
        # 使用极短的 TTL 创建令牌
        m = NEUTokenManager(
            secret_key="short_ttl_test",
            access_token_ttl=1,
            refresh_token_ttl=1,
        )
        _, refresh, info = m.generate_tokens("user_123")
        time.sleep(2)  # 等待过期
        cleaned = m.cleanup_expired()
        assert cleaned >= 1


# ────── 线程安全 (auth.py 安全特性) ──────


class TestThreadSafety:
    """验证线程安全 (从 auth.py 合并)"""

    def test_concurrent_generate_tokens(self, manager):
        """并发生成令牌不应出错"""
        import threading

        results = []
        errors = []

        def worker():
            try:
                for _ in range(10):
                    access, refresh, _ = manager.generate_tokens("user_concurrent")
                    results.append((access, refresh))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 50  # 5 threads * 10 iterations

    def test_concurrent_validate_and_revoke(self, manager):
        """并发验证和撤销不应出错"""
        import threading

        # 预生成令牌
        tokens = []
        for _ in range(20):
            access, _, _ = manager.generate_tokens("user_concurrent")
            tokens.append(access)

        errors = []

        def validator():
            try:
                for token in tokens:
                    manager.validate_token(token)
            except Exception as e:
                errors.append(e)

        def revoker():
            try:
                for token in tokens:
                    manager.revoke_token(token)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=validator) for _ in range(3)]
        threads += [threading.Thread(target=revoker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ────── 死代码验证 ──────


class TestDeadCodeRemoval:
    """验证 neurova/auth.py 已被删除 (死代码清理)"""

    def test_auth_py_not_exists(self):
        """neurova/auth.py 应被删除 (被同名包遮蔽的死代码)"""
        auth_py_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "neurova", "auth.py"
        )
        assert not os.path.exists(auth_py_path), (
            f"neurova/auth.py 应被删除 (死代码), 但仍存在: {auth_py_path}"
        )

    def test_auth_package_still_exists(self):
        """neurova/auth/ 包应仍然存在 (包含 user_model 等子模块)"""
        auth_pkg_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "neurova", "auth", "__init__.py"
        )
        assert os.path.exists(auth_pkg_path), "neurova/auth/ 包应仍然存在"

    def test_cannot_import_NEUTokenManager_from_auth(self):
        """from neurova.auth import NEUTokenManager 应失败 (包不导出此类)"""
        try:
            from neurova.auth import NEUTokenManager as _AuthNEU
            # 如果能导入, 说明清理不彻底
            assert False, "不应能从 neurova.auth 导入 NEUTokenManager"
        except ImportError:
            # 预期行为
            pass
