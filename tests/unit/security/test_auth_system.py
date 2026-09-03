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


class TestTokenBlacklist(unittest.TestCase):
    """Token 黑名单测试"""
    
    def test_token_blacklist(self):
        """测试 Token 黑名单"""
        from neurova.api.endpoints.auth import _token_blacklist, is_token_blacklisted
        
        # 初始状态
        assert "test_token" not in _token_blacklist
        assert is_token_blacklisted("test_token") is False
        
        # 添加到黑名单
        _token_blacklist.add("test_token")
        assert is_token_blacklisted("test_token") is True
        
        # 从黑名单中移除
        _token_blacklist.discard("test_token")
        assert is_token_blacklisted("test_token") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])