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


# 注：原 TestUserRole/TestUserStatus/TestApprovalMode/TestPasswordHasher 四类
# 针对 security/auth_system.py（S-07 死代码，2026-09-11 删除）；
# 认证归 neurova.auth.password_hasher（tests/unit/auth/ 覆盖）。


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
