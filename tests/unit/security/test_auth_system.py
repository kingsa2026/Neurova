"""
Neurova 认证系统测试

测试认证系统的各个组件：
1. JWT Token 生成和验证
2. 用户登录和注册
3. 验证码系统
4. 邀请码系统
5. Token 黑名单机制
"""

import os
import time
import tempfile
import unittest
from datetime import datetime, timedelta

import pytest
from unittest.mock import Mock, patch, MagicMock

# 导入测试模块
from neurova.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_token,
    hash_password,
    verify_password,
)
from neurova.auth.user_model import UserModel
from neurova.auth.verification_code import VerificationCodeModel, VerificationType
from neurova.auth.invitation_code import InvitationCodeModel, InvitationCodeType


class TestJWTToken(unittest.TestCase):
    """JWT Token 测试"""
    
    def test_create_access_token(self):
        """测试创建 Access Token"""
        data = {"sub": "user123", "username": "testuser"}
        token = create_access_token(data)
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_create_refresh_token(self):
        """测试创建 Refresh Token"""
        data = {"sub": "user123", "username": "testuser"}
        token = create_refresh_token(data)
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_decode_token(self):
        """测试解码 Token"""
        data = {"sub": "user123", "username": "testuser"}
        token = create_access_token(data)
        payload = decode_token(token)
        
        assert payload is not None
        assert payload["sub"] == "user123"
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"
    
    def test_verify_token(self):
        """测试验证 Token"""
        data = {"sub": "user123", "username": "testuser"}
        token = create_access_token(data)
        payload = verify_token(token, "access")
        
        assert payload is not None
        assert payload["sub"] == "user123"
        assert payload["type"] == "access"
    
    def test_verify_token_wrong_type(self):
        """测试验证 Token 类型不匹配"""
        data = {"sub": "user123", "username": "testuser"}
        token = create_access_token(data)
        payload = verify_token(token, "refresh")
        
        assert payload is None
    
    def test_decode_invalid_token(self):
        """测试解码无效 Token"""
        payload = decode_token("invalid-token")
        assert payload is None


class TestPasswordHash(unittest.TestCase):
    """密码哈希测试"""
    
    def test_hash_password(self):
        """测试密码哈希"""
        password = "test_password_123"
        hashed = hash_password(password)
        
        assert hashed is not None
        assert hashed != password
        assert len(hashed) > 0
    
    def test_verify_password(self):
        """测试密码验证"""
        password = "test_password_123"
        hashed = hash_password(password)
        
        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False


class TestUserModel(unittest.TestCase):
    """用户模型测试"""
    
    def setUp(self):
        """设置测试环境"""
        self._tmp_fd, self._tmp_path = tempfile.mkstemp(suffix='.db')
        os.close(self._tmp_fd)
        self.user_model = UserModel(self._tmp_path)
    
    def tearDown(self):
        """清理测试环境"""
        try:
            os.unlink(self._tmp_path)
        except OSError:
            pass
    
    def test_create_user(self):
        """测试创建用户"""
        user = self.user_model.create_user(
            username="testuser",
            password_hash="hashed_password",
            email="test@example.com"
        )
        
        assert user is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.role == "user"
        assert user.status == "active"
    
    def test_get_user_by_username(self):
        """测试通过用户名获取用户"""
        self.user_model.create_user(
            username="testuser",
            password_hash="hashed_password"
        )
        
        user = self.user_model.get_user_by_username("testuser")
        assert user is not None
        assert user.username == "testuser"
    
    def test_get_user_by_email(self):
        """测试通过邮箱获取用户"""
        self.user_model.create_user(
            username="testuser",
            password_hash="hashed_password",
            email="test@example.com"
        )
        
        user = self.user_model.get_user_by_email("test@example.com")
        assert user is not None
        assert user.email == "test@example.com"
    
    def test_authenticate_user(self):
        """测试用户认证"""
        password = "test_password_123"
        hashed = hash_password(password)
        
        self.user_model.create_user(
            username="testuser",
            password_hash=hashed
        )
        
        user = self.user_model.authenticate_user("testuser", password)
        assert user is not None
        assert user["username"] == "testuser"
    
    def test_authenticate_wrong_password(self):
        """测试错误密码认证"""
        password = "test_password_123"
        hashed = hash_password(password)
        
        self.user_model.create_user(
            username="testuser",
            password_hash=hashed
        )
        
        user = self.user_model.authenticate_user("testuser", "wrong_password")
        assert user is None


class TestVerificationCode(unittest.TestCase):
    """验证码测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.verification_model = VerificationCodeModel(":memory:")
    
    def test_create_code(self):
        """测试创建验证码"""
        code = self.verification_model.create_code(
            target="test@example.com",
            code_type=VerificationType.REGISTER,
            expires_in=300,
            length=6
        )
        
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()
    
    def test_verify_code(self):
        """测试验证验证码"""
        code = self.verification_model.create_code(
            target="test@example.com",
            code_type=VerificationType.REGISTER,
            expires_in=300,
            length=6
        )
        
        is_valid = self.verification_model.verify_code(
            target="test@example.com",
            code=code,
            code_type=VerificationType.REGISTER
        )
        
        assert is_valid is True
    
    def test_verify_wrong_code(self):
        """测试验证错误验证码"""
        self.verification_model.create_code(
            target="test@example.com",
            code_type=VerificationType.REGISTER,
            expires_in=300,
            length=6
        )
        
        is_valid = self.verification_model.verify_code(
            target="test@example.com",
            code="000000",
            code_type=VerificationType.REGISTER
        )
        
        assert is_valid is False
    
    def test_can_send_code(self):
        """测试检查是否可以发送验证码"""
        result = self.verification_model.can_send_code(
            target="test@example.com",
            code_type=VerificationType.REGISTER,
            cooldown=60
        )
        
        assert result["can_send"] is True
    
    def test_check_register_rate_limit(self):
        """测试检查注册限流"""
        result = self.verification_model.check_register_rate_limit("192.168.1.1")
        
        assert result["is_limited"] is False
        assert result["remaining_attempts"] > 0


class TestInvitationCode(unittest.TestCase):
    """邀请码测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.invitation_model = InvitationCodeModel(":memory:")
    
    def test_create_code(self):
        """测试创建邀请码"""
        invitation = self.invitation_model.create_code(
            code_type=InvitationCodeType.SINGLE_USE,
            max_uses=1,
            expires_in=86400
        )
        
        assert invitation is not None
        assert len(invitation.code) == 8
        assert invitation.code_type == InvitationCodeType.SINGLE_USE
    
    def test_validate_code(self):
        """测试验证邀请码"""
        invitation = self.invitation_model.create_code(
            code_type=InvitationCodeType.SINGLE_USE,
            max_uses=1
        )
        
        is_valid = self.invitation_model.validate_code(invitation.code)
        assert is_valid is True
    
    def test_use_code(self):
        """测试使用邀请码"""
        invitation = self.invitation_model.create_code(
            code_type=InvitationCodeType.SINGLE_USE,
            max_uses=1
        )
        
        result = self.invitation_model.use_code(
            code=invitation.code,
            used_by="user123"
        )
        
        assert result is not None
        assert result.current_uses == 1
        assert result.is_active is False
    
    def test_use_code_twice(self):
        """测试使用邀请码两次"""
        invitation = self.invitation_model.create_code(
            code_type=InvitationCodeType.SINGLE_USE,
            max_uses=1
        )
        
        # 第一次使用
        self.invitation_model.use_code(
            code=invitation.code,
            used_by="user123"
        )
        
        # 第二次使用
        result = self.invitation_model.use_code(
            code=invitation.code,
            used_by="user456"
        )
        
        assert result is None
    
    def test_multi_use_code(self):
        """测试多次使用邀请码"""
        invitation = self.invitation_model.create_code(
            code_type=InvitationCodeType.MULTI_USE,
            max_uses=3
        )
        
        # 使用3次
        for i in range(3):
            result = self.invitation_model.use_code(
                code=invitation.code,
                used_by=f"user{i}"
            )
            assert result is not None
        
        # 第4次使用
        result = self.invitation_model.use_code(
            code=invitation.code,
            used_by="user4"
        )
        assert result is None


class TestTokenBlacklist:
    """Token 黑名单测试

    契约更新（审计 §3.1-13，R4）：黑名单收口到 neurova/api/auth 的 **SQLite
    持久化单源**（重启/多 worker 不失效；容量由"写入时清除已过期行"约束）。
    endpoints/auth 的第二份进程内存黑名单（_blacklist_token_local/_token_blacklist）
    已退役，本测试改为钉单源契约。
    """

    def test_blacklist_register_and_hit(self):
        """登记→命中；未登记→不命中（endpoints 侧 is_token_blacklisted 走同一单源）。"""
        import time as _time

        from neurova.api import auth as auth_mod
        from neurova.api.endpoints.auth import is_token_blacklisted

        token = f"test_token_{_time.time()}"
        assert auth_mod.is_token_blacklisted_global(token) is False
        assert is_token_blacklisted(token) is False

        auth_mod.blacklist_token(token)
        assert auth_mod.is_token_blacklisted_global(token) is True
        assert is_token_blacklisted(token) is True

    def test_blacklist_persists_in_sqlite(self):
        """登记落 SQLite（数据根 auth_blacklist.db），跨连接可见——进程重启
        语义的最小可测形态。"""
        import sqlite3
        import time as _time

        from neurova.api import auth as auth_mod

        token = f"persist_token_{_time.time()}"
        auth_mod.blacklist_token(token)

        assert auth_mod._BLACKLIST_DB_PATH.endswith("auth_blacklist.db")
        conn = sqlite3.connect(auth_mod._BLACKLIST_DB_PATH)
        try:
            row = conn.execute(
                "SELECT exp FROM revoked_tokens WHERE token = ?", (token,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "撤销 token 必须落库（持久化单源）"
        assert float(row[0]) > _time.time() - 60

    def test_blacklist_expired_row_purged_on_write(self):
        """写入时惰性清除已过期行——容量有界，且不会把未过期项一起清掉
        （旧实现超容量整表 clear 的缺陷不再存在）。"""
        import sqlite3
        import time as _time

        from neurova.api import auth as auth_mod

        expired = f"expired_{_time.time()}"
        keep = f"keep_{_time.time()}"
        auth_mod.blacklist_token(expired, exp=_time.time() - 10)
        auth_mod.blacklist_token(keep)

        conn = sqlite3.connect(auth_mod._BLACKLIST_DB_PATH)
        try:
            gone = conn.execute(
                "SELECT 1 FROM revoked_tokens WHERE token = ?", (expired,)
            ).fetchone()
            kept = conn.execute(
                "SELECT 1 FROM revoked_tokens WHERE token = ?", (keep,)
            ).fetchone()
        finally:
            conn.close()
        assert gone is None, "已过期撤销项应在写入时被清除"
        assert kept is not None, "未过期撤销项不得被误清"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])