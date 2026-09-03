"""
测试 security 模块的实现
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestUserRole:
    """测试 UserRole 枚举"""
    
    def test_user_roles(self):
        """测试用户角色枚举"""
        from neurova.security.auth_system import UserRole
        
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.USER.value == "user"
        assert UserRole.GUEST.value == "guest"
        assert UserRole.MODERATOR.value == "moderator"


class TestUserStatus:
    """测试 UserStatus 枚举"""
    
    def test_user_statuses(self):
        """测试用户状态枚举"""
        from neurova.security.auth_system import UserStatus
        
        assert UserStatus.ACTIVE.value == "active"
        assert UserStatus.INACTIVE.value == "inactive"
        assert UserStatus.SUSPENDED.value == "suspended"
        assert UserStatus.PENDING.value == "pending"


class TestApprovalMode:
    """测试 ApprovalMode 枚举"""
    
    def test_approval_modes(self):
        """测试审批模式枚举"""
        from neurova.security.auth_system import ApprovalMode
        
        assert ApprovalMode.AUTO.value == "auto"
        assert ApprovalMode.MANUAL.value == "manual"
        assert ApprovalMode.SEMI_AUTO.value == "semi_auto"


class TestPasswordHasher:
    """测试 PasswordHasher 类"""
    
    def test_hash_password(self):
        """测试密码哈希"""
        from neurova.security.auth_system import PasswordHasher
        
        hasher = PasswordHasher()
        password = "test_password"
        
        hashed = hasher.hash(password)
        
        assert isinstance(hashed, str)
        assert len(hashed) > 0
        assert hashed != password
    
    def test_verify_password(self):
        """测试密码验证"""
        from neurova.security.auth_system import PasswordHasher
        
        hasher = PasswordHasher()
        password = "test_password"
        
        hashed = hasher.hash(password)
        
        assert hasher.verify(password, hashed) is True
        assert hasher.verify("wrong_password", hashed) is False


class TestAuditEventType:
    """测试 AuditEventType 枚举"""
    
    def test_audit_event_types(self):
        """测试审计事件类型枚举"""
        from neurova.security.audit_logger import AuditEventType
        
        assert AuditEventType.AUTH_LOGIN.value == "auth_login"
        assert AuditEventType.AUTH_LOGOUT.value == "auth_logout"
        assert AuditEventType.AUTH_FAILED.value == "auth_failed"
        assert AuditEventType.CONFIG_CHANGE.value == "config_change"
        assert AuditEventType.PERMISSION_CHANGE.value == "permission_change"


class TestAuditSeverity:
    """测试 AuditSeverity 枚举"""
    
    def test_audit_severities(self):
        """测试审计严重级别枚举"""
        from neurova.security.audit_logger import AuditSeverity
        
        assert AuditSeverity.LOW.value == "low"
        assert AuditSeverity.MEDIUM.value == "medium"
        assert AuditSeverity.HIGH.value == "high"
        assert AuditSeverity.CRITICAL.value == "critical"


class TestAuditLogEntry:
    """测试 AuditLogEntry 数据类"""
    
    def test_audit_log_entry_creation(self):
        """测试 AuditLogEntry 创建"""
        from neurova.security.audit_logger import AuditLogEntry, AuditEventType, AuditSeverity
        
        entry = AuditLogEntry(
            event_type=AuditEventType.AUTH_LOGIN,
            severity=AuditSeverity.MEDIUM,
            user_id="user123",
            action="Login successful",
            details={"ip": "192.168.1.1"}
        )
        
        assert entry.event_type == AuditEventType.AUTH_LOGIN
        assert entry.severity == AuditSeverity.MEDIUM
        assert entry.user_id == "user123"
        assert entry.action == "Login successful"
        assert entry.details["ip"] == "192.168.1.1"
    
    def test_audit_log_entry_to_dict(self):
        """测试 AuditLogEntry 转字典"""
        from neurova.security.audit_logger import AuditLogEntry, AuditEventType, AuditSeverity
        
        entry = AuditLogEntry(
            event_type=AuditEventType.AUTH_LOGIN,
            severity=AuditSeverity.MEDIUM,
            user_id="user123",
            action="Login successful"
        )
        
        data = entry.to_dict()
        assert isinstance(data, dict)
        assert data["event_type"] == "auth_login"
        assert data["severity"] == "medium"
        assert data["user_id"] == "user123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
