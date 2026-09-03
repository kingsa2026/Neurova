"""
RBACManager 全面单元测试
测试 neurova.security.rbac 模块的所有功能
"""
import pytest
import sqlite3
import tempfile
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from neurova.security.rbac import (
    Permission,
    Role,
    PermissionChangeRequest,
    RBACManager,
    ROLE_PERMISSIONS,
    get_rbac_manager,
)


class TestPermission:
    """测试 Permission 枚举"""

    def test_system_permissions(self):
        """测试系统权限"""
        assert Permission.SYSTEM_READ.value == "system:read"
        assert Permission.SYSTEM_WRITE.value == "system:write"

    def test_user_permissions(self):
        """测试用户管理权限"""
        assert Permission.USER_READ.value == "user:read"
        assert Permission.USER_WRITE.value == "user:write"
        assert Permission.USER_DELETE.value == "user:delete"

    def test_role_permissions(self):
        """测试角色管理权限"""
        assert Permission.ROLE_READ.value == "role:read"
        assert Permission.ROLE_WRITE.value == "role:write"
        assert Permission.ROLE_DELETE.value == "role:delete"

    def test_api_key_permissions(self):
        """测试 API Key 管理权限"""
        assert Permission.API_KEY_READ.value == "api_key:read"
        assert Permission.API_KEY_WRITE.value == "api_key:write"
        assert Permission.API_KEY_DELETE.value == "api_key:delete"

    def test_audit_permissions(self):
        """测试审计权限"""
        assert Permission.AUDIT_READ.value == "audit:read"
        assert Permission.AUDIT_EXPORT.value == "audit:export"

    def test_config_permissions(self):
        """测试配置权限"""
        assert Permission.CONFIG_READ.value == "config:read"
        assert Permission.CONFIG_WRITE.value == "config:write"

    def test_skill_permissions(self):
        """测试 Skill 权限"""
        assert Permission.SKILL_READ.value == "skill:read"
        assert Permission.SKILL_WRITE.value == "skill:write"
        assert Permission.SKILL_DELETE.value == "skill:delete"

    def test_workflow_permissions(self):
        """测试工作流权限"""
        assert Permission.WORKFLOW_READ.value == "workflow:read"
        assert Permission.WORKFLOW_WRITE.value == "workflow:write"
        assert Permission.WORKFLOW_DELETE.value == "workflow:delete"

    def test_channel_permissions(self):
        """测试渠道权限"""
        assert Permission.CHANNEL_READ.value == "channel:read"
        assert Permission.CHANNEL_WRITE.value == "channel:write"
        assert Permission.CHANNEL_DELETE.value == "channel:delete"

    def test_compliance_permissions(self):
        """测试合规权限"""
        assert Permission.COMPLIANCE_READ.value == "compliance:read"
        assert Permission.COMPLIANCE_WRITE.value == "compliance:write"


class TestRoleDefinition:
    """测试角色定义"""

    def test_predefined_roles_exist(self):
        """测试预定义角色存在"""
        assert "admin" in ROLE_PERMISSIONS
        assert "operator" in ROLE_PERMISSIONS
        assert "developer" in ROLE_PERMISSIONS
        assert "viewer" in ROLE_PERMISSIONS
        assert "guest" in ROLE_PERMISSIONS

    def test_admin_permissions(self):
        """测试 admin 角色权限"""
        admin_perms = ROLE_PERMISSIONS["admin"]
        assert "system:read" in admin_perms
        assert "system:write" in admin_perms
        assert "user:delete" in admin_perms
        assert "role:delete" in admin_perms

    def test_viewer_permissions(self):
        """测试 viewer 角色权限"""
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        assert "system:read" in viewer_perms
        assert "user:read" in viewer_perms
        # viewer 不应该有写权限
        assert "user:write" not in viewer_perms
        assert "config:write" not in viewer_perms

    def test_guest_permissions(self):
        """测试 guest 角色权限（最小权限）"""
        guest_perms = ROLE_PERMISSIONS["guest"]
        assert "system:read" in guest_perms
        assert "skill:read" in guest_perms
        # guest 不应该有写权限
        assert "user:write" not in guest_perms
        assert "config:read" not in guest_perms


class TestRoleDataclass:
    """测试 Role 数据类"""

    def test_role_creation(self):
        """测试创建角色"""
        role = Role(
            id="test_role",
            name="Test Role",
            description="A test role",
            permissions={"user:read", "user:write"},
            is_system=False,
        )
        assert role.id == "test_role"
        assert role.name == "Test Role"
        assert role.description == "A test role"
        assert role.permissions == {"user:read", "user:write"}
        assert role.is_system is False
        assert isinstance(role.created_at, datetime)
        assert isinstance(role.updated_at, datetime)

    def test_role_to_dict(self):
        """测试转换为字典"""
        role = Role(
            id="dict_role",
            name="Dict Role",
            description="Test",
            permissions={"config:read"},
            is_system=True,
        )
        result = role.to_dict()
        assert result["id"] == "dict_role"
        assert result["name"] == "Dict Role"
        assert result["is_system"] is True
        assert "config:read" in result["permissions"]


class TestPermissionChangeRequest:
    """测试 PermissionChangeRequest 数据类"""

    def test_request_creation(self):
        """测试创建权限变更请求"""
        now = datetime.now()
        request = PermissionChangeRequest(
            id=1,
            requester_id="user1",
            target_user_id="user2",
            action="assign_role",
            role_id="admin",
            permissions=None,
            reason="Need admin access",
            status="pending",
            created_at=now,
        )
        assert request.id == 1
        assert request.requester_id == "user1"
        assert request.target_user_id == "user2"
        assert request.action == "assign_role"
        assert request.status == "pending"

    def test_request_to_dict(self):
        """测试转换为字典"""
        now = datetime.now()
        request = PermissionChangeRequest(
            id=42,
            requester_id="requester",
            target_user_id="target",
            action="update_permissions",
            role_id=None,
            permissions={"user:read", "user:write"},
            reason="Update perms",
            status="approved",
            approver_id="admin",
            approver_comment="Approved",
            created_at=now,
            processed_at=now,
        )
        result = request.to_dict()
        assert result["id"] == 42
        assert result["status"] == "approved"
        assert result["approver_id"] == "admin"
        assert "user:read" in result["permissions"]


class TestRBACManagerSingleton:
    """测试 RBACManager 单例模式"""

    def test_singleton(self):
        """测试单例"""
        manager1 = RBACManager()
        manager2 = RBACManager()
        assert manager1 is manager2

    def test_singleton_different_paths(self, tmp_path):
        """测试不同数据库路径也返回同一实例"""
        manager1 = RBACManager(db_path=str(tmp_path / "test1.db"))
        manager2 = RBACManager(db_path=str(tmp_path / "test2.db"))
        # 仍然是同一个实例（单例模式）
        assert manager1 is manager2


class TestRBACManagerRoleManagement:
    """测试 RBACManager 角色管理功能"""

    @pytest.fixture
    def rbac_manager(self, tmp_path):
        """创建 RBACManager 实例（使用临时数据库）"""
        db_path = str(tmp_path / "test_rbac.db")
        # 重置单例
        RBACManager._instance = None
        manager = RBACManager(db_path=db_path)
        yield manager
        RBACManager._instance = None

    def test_create_role(self, rbac_manager):
        """测试创建角色"""
        role = rbac_manager.create_role(
            name="Custom Role",
            description="A custom role",
            permissions={"user:read", "skill:read"},
        )
        assert role is not None
        assert role.name == "Custom Role"
        assert role.is_system is False
        assert "user:read" in role.permissions

    def test_create_duplicate_role(self, rbac_manager):
        """测试创建重复角色（名称唯一）"""
        rbac_manager.create_role(
            name="Duplicate",
            description="First",
            permissions={"user:read"},
        )
        result = rbac_manager.create_role(
            name="Duplicate",
            description="Second",
            permissions={"user:write"},
        )
        # 应该失败（名称唯一约束）
        assert result is None

    def test_get_role(self, rbac_manager):
        """测试获取角色"""
        # 先创建一个角色
        created = rbac_manager.create_role(
            name="Get Test",
            description="Test",
            permissions={"config:read"},
        )
        
        # 通过 ID 获取
        retrieved = rbac_manager.get_role("get_test")
        assert retrieved is not None
        assert retrieved.id == "get_test"
        assert retrieved.name == "Get Test"

    def test_get_role_by_name(self, rbac_manager):
        """测试通过名称获取角色"""
        rbac_manager.create_role(
            name="ByName Test",
            description="Test",
            permissions={"api_key:read"},
        )
        
        role = rbac_manager.get_role_by_name("ByName Test")
        assert role is not None
        assert role.name == "ByName Test"

    def test_get_nonexistent_role(self, rbac_manager):
        """测试获取不存在的角色"""
        result = rbac_manager.get_role("nonexistent")
        assert result is None

    def test_list_roles(self, rbac_manager):
        """测试列出所有角色"""
        # 应该有预定义角色
        roles = rbac_manager.list_roles()
        assert len(roles) >= 5  # 至少 5 个预定义角色
        
        role_names = [r.name for r in roles]
        assert "admin" in role_names
        assert "operator" in role_names
        assert "viewer" in role_names

    def test_update_role(self, rbac_manager):
        """测试更新角色"""
        # 创建自定义角色
        created = rbac_manager.create_role(
            name="Update Test",
            description="Before",
            permissions={"user:read"},
        )
        
        # 更新
        updated = rbac_manager.update_role(
            role_id="update_test",
            name="Update Test Updated",
            description="After",
            permissions={"user:read", "user:write"},
        )
        
        assert updated is not None
        assert updated.name == "Update Test Updated"
        assert updated.description == "After"
        assert "user:write" in updated.permissions

    def test_update_system_role(self, rbac_manager):
        """测试更新系统预定义角色（应该失败）"""
        result = rbac_manager.update_role(
            role_id="admin",
            name="Hacked Admin",
        )
        assert result is None

    def test_update_nonexistent_role(self, rbac_manager):
        """测试更新不存在的角色"""
        result = rbac_manager.update_role("nonexistent")
        assert result is None

    def test_delete_role(self, rbac_manager):
        """测试删除角色"""
        # 创建自定义角色
        rbac_manager.create_role(
            name="Delete Test",
            description="To be deleted",
            permissions={"user:read"},
        )
        
        # 删除
        result = rbac_manager.delete_role("delete_test")
        assert result is True
        
        # 确认已删除
        assert rbac_manager.get_role("delete_test") is None

    def test_delete_system_role(self, rbac_manager):
        """测试删除系统预定义角色（应该失败）"""
        result = rbac_manager.delete_role("admin")
        assert result is False

    def test_delete_nonexistent_role(self, rbac_manager):
        """测试删除不存在的角色"""
        result = rbac_manager.delete_role("nonexistent")
        assert result is False


class TestRBACManagerPermissionChecking:
    """测试 RBACManager 权限检查功能"""

    @pytest.fixture
    def rbac_manager(self, tmp_path):
        """创建 RBACManager 实例并分配角色"""
        db_path = str(tmp_path / "test_rbac.db")
        RBACManager._instance = None
        manager = RBACManager(db_path=db_path)
        
        # 分配角色给用户
        manager.assign_role("user1", "admin", assigned_by="system")
        manager.assign_role("user2", "viewer", assigned_by="system")
        
        yield manager
        RBACManager._instance = None

    def test_has_permission_admin(self, rbac_manager):
        """测试 admin 用户权限"""
        assert rbac_manager.has_permission("user1", "system:read") is True
        assert rbac_manager.has_permission("user1", "system:write") is True
        assert rbac_manager.has_permission("user1", "user:delete") is True

    def test_has_permission_viewer(self, rbac_manager):
        """测试 viewer 用户权限"""
        assert rbac_manager.has_permission("user2", "system:read") is True
        assert rbac_manager.has_permission("user2", "user:read") is True
        # viewer 不应该有写权限
        assert rbac_manager.has_permission("user2", "user:write") is False
        assert rbac_manager.has_permission("user2", "config:write") is False

    def test_has_permission_nonexistent_user(self, rbac_manager):
        """测试不存在的用户"""
        assert rbac_manager.has_permission("nonexistent", "user:read") is False

    def test_has_any_permission(self, rbac_manager):
        """测试检查任一权限"""
        assert rbac_manager.has_any_permission(
            "user1", ["user:read", "nonexistent:perm"]
        ) is True
        assert rbac_manager.has_any_permission(
            "user2", ["user:write", "config:write"]
        ) is False

    def test_has_all_permissions(self, rbac_manager):
        """测试检查所有权限"""
        assert rbac_manager.has_all_permissions(
            "user1", ["system:read", "user:read"]
        ) is True
        assert rbac_manager.has_all_permissions(
            "user2", ["system:read", "user:write"]
        ) is False

    def test_get_user_permissions(self, rbac_manager):
        """测试获取用户所有权限"""
        perms = rbac_manager.get_user_permissions("user1")
        assert "system:read" in perms
        assert "system:write" in perms
        assert "user:delete" in perms

        viewer_perms = rbac_manager.get_user_permissions("user2")
        assert "system:read" in viewer_perms
        assert "user:write" not in viewer_perms


class TestRBACManagerUserRoleAssignment:
    """测试 RBACManager 用户角色分配功能"""

    @pytest.fixture
    def rbac_manager(self, tmp_path):
        """创建 RBACManager 实例"""
        db_path = str(tmp_path / "test_rbac.db")
        RBACManager._instance = None
        manager = RBACManager(db_path=db_path)
        yield manager
        RBACManager._instance = None

    def test_assign_role(self, rbac_manager):
        """测试分配角色"""
        result = rbac_manager.assign_role(
            user_id="test_user",
            role_id="admin",
            assigned_by="system",
        )
        assert result is True

    def test_assign_nonexistent_role(self, rbac_manager):
        """测试分配不存在的角色"""
        result = rbac_manager.assign_role(
            user_id="test_user",
            role_id="nonexistent",
            assigned_by="system",
        )
        assert result is False

    def test_assign_role_duplicate(self, rbac_manager):
        """测试重复分配角色（应该成功，INSERT OR REPLACE）"""
        rbac_manager.assign_role("user1", "viewer", assigned_by="system")
        result = rbac_manager.assign_role("user1", "viewer", assigned_by="system")
        assert result is True

    def test_revoke_role(self, rbac_manager):
        """测试撤销角色"""
        # 先分配
        rbac_manager.assign_role("user1", "operator", assigned_by="system")
        assert rbac_manager.has_permission("user1", "user:write") is True
        
        # 撤销
        result = rbac_manager.revoke_role("user1", "operator")
        assert result is True
        assert rbac_manager.has_permission("user1", "user:write") is False

    def test_revoke_nonexistent_role(self, rbac_manager):
        """测试撤销未分配的角色"""
        result = rbac_manager.revoke_role("user1", "admin")
        assert result is False

    def test_get_user_roles(self, rbac_manager):
        """测试获取用户的所有角色"""
        rbac_manager.assign_role("user1", "admin", assigned_by="system")
        rbac_manager.assign_role("user1", "developer", assigned_by="system")
        
        roles = rbac_manager.get_user_roles("user1")
        role_names = [r.name for r in roles]
        assert "admin" in role_names
        assert "developer" in role_names

    def test_get_role_users(self, rbac_manager):
        """测试获取拥有指定角色的所有用户"""
        rbac_manager.assign_role("user1", "viewer", assigned_by="system")
        rbac_manager.assign_role("user2", "viewer", assigned_by="system")
        rbac_manager.assign_role("user3", "operator", assigned_by="system")
        
        viewer_users = rbac_manager.get_role_users("viewer")
        assert "user1" in viewer_users
        assert "user2" in viewer_users
        assert "user3" not in viewer_users


class TestRBACManagerPermissionRequests:
    """测试 RBACManager 权限变更请求功能"""

    @pytest.fixture
    def rbac_manager(self, tmp_path):
        """创建 RBACManager 实例"""
        db_path = str(tmp_path / "test_rbac.db")
        RBACManager._instance = None
        manager = RBACManager(db_path=db_path)
        yield manager
        RBACManager._instance = None

    def test_create_permission_request(self, rbac_manager):
        """测试创建权限变更请求"""
        request_id = rbac_manager.create_permission_request(
            requester_id="user1",
            target_user_id="user2",
            action="assign_role",
            reason="Need access",
            role_id="operator",
        )
        assert isinstance(request_id, int)
        assert request_id > 0

    def test_create_permission_request_with_permissions(self, rbac_manager):
        """测试创建带权限的变更请求"""
        request_id = rbac_manager.create_permission_request(
            requester_id="user1",
            target_user_id="user2",
            action="update_permissions",
            reason="Update perms",
            permissions={"user:read", "user:write"},
        )
        assert isinstance(request_id, int)

    def test_get_pending_requests(self, rbac_manager):
        """测试获取待处理的权限变更请求"""
        # 创建几个请求
        rbac_manager.create_permission_request(
            requester_id="user1",
            target_user_id="user2",
            action="assign_role",
            reason="Test 1",
            role_id="viewer",
        )
        rbac_manager.create_permission_request(
            requester_id="user3",
            target_user_id="user4",
            action="assign_role",
            reason="Test 2",
            role_id="operator",
        )
        
        pending = rbac_manager.get_pending_requests()
        assert len(pending) == 2

    def test_approve_request(self, rbac_manager):
        """测试批准权限变更请求"""
        # 创建请求
        request_id = rbac_manager.create_permission_request(
            requester_id="user1",
            target_user_id="user2",
            action="assign_role",
            reason="Need role",
            role_id="viewer",
        )
        
        # 批准
        result = rbac_manager.approve_request(
            request_id=request_id,
            approver_id="admin",
            comment="Approved",
        )
        assert result is True
        
        # 验证角色已分配
        assert rbac_manager.has_permission("user2", "system:read") is True

    def test_approve_request_invalid(self, rbac_manager):
        """测试批准不存在的请求"""
        result = rbac_manager.approve_request(
            request_id=9999,
            approver_id="admin",
        )
        assert result is False

    def test_reject_request(self, rbac_manager):
        """测试拒绝权限变更请求"""
        # 创建请求
        request_id = rbac_manager.create_permission_request(
            requester_id="user1",
            target_user_id="user2",
            action="assign_role",
            reason="Need role",
            role_id="admin",
        )
        
        # 拒绝
        result = rbac_manager.reject_request(
            request_id=request_id,
            approver_id="admin",
            comment="Not approved",
        )
        assert result is True
        
        # 验证角色未分配
        assert rbac_manager.has_permission("user2", "system:write") is False

    def test_reject_request_invalid(self, rbac_manager):
        """测试拒绝不存在的请求"""
        result = rbac_manager.reject_request(
            request_id=9999,
            approver_id="admin",
        )
        assert result is False


class TestRBACManagerPermissionList:
    """测试 RBACManager 权限列表功能"""

    @pytest.fixture
    def rbac_manager(self, tmp_path):
        """创建 RBACManager 实例"""
        db_path = str(tmp_path / "test_rbac.db")
        RBACManager._instance = None
        manager = RBACManager(db_path=db_path)
        yield manager
        RBACManager._instance = None

    def test_get_all_permissions(self, rbac_manager):
        """测试获取所有可用权限"""
        all_perms = rbac_manager.get_all_permissions()
        assert len(all_perms) == len(Permission)
        
        # 检查格式
        for perm in all_perms:
            assert "id" in perm
            assert "name" in perm
            assert "description" in perm

    def test_permission_descriptions(self, rbac_manager):
        """测试权限描述"""
        all_perms = rbac_manager.get_all_permissions()
        perm_dict = {p["id"]: p["description"] for p in all_perms}
        
        assert perm_dict["system:read"] == "读取系统信息"
        assert perm_dict["user:delete"] == "删除用户"
        assert perm_dict["audit:export"] == "导出审计日志"


class TestGlobalRBACManager:
    """测试全局 RBACManager 函数"""

    def teardown_method(self):
        """每个测试后重置全局管理器"""
        global _rbac_manager
        from neurova.security.rbac import _rbac_manager
        globals()["_rbac_manager"] = None

    def test_get_rbac_manager_singleton(self):
        """测试全局管理器单例"""
        manager1 = get_rbac_manager()
        manager2 = get_rbac_manager()
        assert manager1 is manager2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
