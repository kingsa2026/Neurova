"""P2.2 验证测试 — neu_token_manager 是完整实现, 非骨架

之前知识图谱错误判断 neurova/security/neu_token_manager.py 为骨架文件。
本测试验证该文件是完整实现且功能正常, 纠正知识图谱判断。

发现: 存在两个 NEUTokenManager 实现:
  1. neurova/auth.py — 更完整 (refresh token, blacklist, lifecycle)
  2. neurova/security/neu_token_manager.py — 被 api/app.py 实际使用

两者都是完整实现, 存在重复。本测试验证 security/ 版本的功能完整性。
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
    return NEUTokenManager(secret_key="test_secret_key_for_verification")


class TestNEUTokenManagerComplete:
    """验证 NEUTokenManager 是完整实现, 非骨架"""

    def test_can_instantiate(self, manager):
        """能正常实例化 (非骨架)"""
        assert manager is not None

    def test_generate_token_returns_non_empty_string(self, manager):
        """generate_token 应返回非空字符串"""
        token = manager.generate_token("user_123")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_validate_valid_token_returns_metadata(self, manager):
        """validate_token 对有效令牌应返回元数据"""
        token = manager.generate_token("user_123", metadata={"role": "admin"})
        result = manager.validate_token(token)
        assert result is not None
        assert result["user_id"] == "user_123"

    def test_validate_invalid_token_returns_none(self, manager):
        """validate_token 对无效令牌应返回 None"""
        result = manager.validate_token("invalid_token_string")
        assert result is None

    def test_revoke_token_works(self, manager):
        """revoke_token 应使令牌失效"""
        token = manager.generate_token("user_123")
        assert manager.revoke_token(token) is True
        assert manager.validate_token(token) is None

    def test_generate_api_key_returns_non_empty_string(self, manager):
        """generate_api_key 应返回非空字符串"""
        api_key = manager.generate_api_key("user_123", "test_key")
        assert isinstance(api_key, str)
        assert len(api_key) > 0

    def test_validate_api_key_returns_metadata(self, manager):
        """validate_api_key 对有效 key 应返回元数据"""
        api_key = manager.generate_api_key("user_123", "test_key", scopes=["read", "write"])
        result = manager.validate_api_key(api_key)
        assert result is not None
        assert result["user_id"] == "user_123"

    def test_validate_invalid_api_key_returns_none(self, manager):
        """validate_api_key 对无效 key 应返回 None"""
        result = manager.validate_api_key("invalid_api_key")
        assert result is None

    def test_revoke_api_key_works(self, manager):
        """revoke_api_key 应使 key 失效"""
        api_key = manager.generate_api_key("user_123", "test_key")
        assert manager.revoke_api_key(api_key) is True
        assert manager.validate_api_key(api_key) is None

    def test_list_api_keys_returns_list(self, manager):
        """list_api_keys 应返回列表"""
        manager.generate_api_key("user_123", "key1")
        manager.generate_api_key("user_123", "key2")
        keys = manager.list_api_keys("user_123")
        assert isinstance(keys, list)
        assert len(keys) >= 2

    def test_cleanup_expired_tokens_returns_int(self, manager):
        """cleanup_expired_tokens 应返回清理数量 (int)"""
        result = manager.cleanup_expired_tokens()
        assert isinstance(result, int)
        assert result >= 0


class TestNEUTokenManagerUsedByApp:
    """验证 NEUTokenManager 被 api/app.py 实际使用"""

    def test_app_imports_neu_token_manager(self):
        """api/app.py 应导入 NEUTokenManager"""
        import inspect

        from neurova.api import app

        source = inspect.getsource(app)
        assert "from neurova.security.neu_token_manager import NEUTokenManager" in source, (
            "api/app.py 应从 security.neu_token_manager 导入 NEUTokenManager"
        )

    def test_app_initializes_token_manager(self):
        """api/app.py 应初始化 token_manager"""
        import inspect

        from neurova.api import app

        source = inspect.getsource(app)
        assert "app_state.token_manager = NEUTokenManager" in source, (
            "api/app.py 应将 NEUTokenManager 实例赋给 app_state.token_manager"
        )
