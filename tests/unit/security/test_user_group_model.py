"""
测试用户组模型
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
from typing import Set

import pytest

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.auth.user_group_model import (
    Permission,
    UserGroupType,
    ResourceQuota,
    UserGroup,
    UserGroupManager,
)


class TestResourceQuota:
    """测试资源配额"""

    def test_default_quota(self):
        """测试默认配额"""
        quota = ResourceQuota()
        
        assert quota.max_agents == 5
        assert quota.max_projects == 10
        assert quota.max_llm_calls_per_day == 1000
        assert quota.max_storage_mb == 1024

    def test_custom_quota(self):
        """测试自定义配额"""
        quota = ResourceQuota(
            max_agents=20,
            max_projects=50,
            max_llm_calls_per_day=5000,
        )
        
        assert quota.max_agents == 20
        assert quota.max_projects == 50
        assert quota.max_llm_calls_per_day == 5000


class TestUserGroup:
    """测试用户组"""

    def test_create_user_group(self):
        """测试创建用户组"""
        quota = ResourceQuota(max_agents=10)
        permissions = {Permission.AGENT_CREATE, Permission.PROJECT_CREATE}
        
        group = UserGroup(
            group_id="test_group",
            name="测试用户组",
            description="测试描述",
            group_type=UserGroupType.CUSTOM,
            quota=quota,
            permissions=permissions,
        )
        
        assert group.group_id == "test_group"
        assert group.name == "测试用户组"
        assert group.group_type == UserGroupType.CUSTOM
        assert group.quota.max_agents == 10
        assert Permission.AGENT_CREATE in group.permissions
        assert group.is_system == False

    def test_has_permission(self):
        """测试权限检查"""
        permissions = {Permission.AGENT_CREATE, Permission.PROJECT_CREATE}
        group = UserGroup(
            group_id="test_group",
            name="测试用户组",
            description="测试描述",
            group_type=UserGroupType.CUSTOM,
            quota=ResourceQuota(),
            permissions=permissions,
        )
        
        assert group.has_permission(Permission.AGENT_CREATE) == True
        assert group.has_permission(Permission.USER_CREATE) == False

    def test_add_permission(self):
        """测试添加权限"""
        group = UserGroup(
            group_id="test_group",
            name="测试用户组",
            description="测试描述",
            group_type=UserGroupType.CUSTOM,
            quota=ResourceQuota(),
            permissions=set(),
        )
        
        assert group.has_permission(Permission.AGENT_CREATE) == False
        
        group.add_permission(Permission.AGENT_CREATE)
        assert group.has_permission(Permission.AGENT_CREATE) == True

    def test_remove_permission(self):
        """测试移除权限"""
        permissions = {Permission.AGENT_CREATE, Permission.PROJECT_CREATE}
        group = UserGroup(
            group_id="test_group",
            name="测试用户组",
            description="测试描述",
            group_type=UserGroupType.CUSTOM,
            quota=ResourceQuota(),
            permissions=permissions,
        )
        
        assert group.has_permission(Permission.AGENT_CREATE) == True
        
        group.remove_permission(Permission.AGENT_CREATE)
        assert group.has_permission(Permission.AGENT_CREATE) == False

    def test_to_dict(self):
        """测试转换为字典"""
        quota = ResourceQuota(max_agents=10)
        permissions = {Permission.AGENT_CREATE}
        group = UserGroup(
            group_id="test_group",
            name="测试用户组",
            description="测试描述",
            group_type=UserGroupType.CUSTOM,
            quota=quota,
            permissions=permissions,
        )
        
        data = group.to_dict()
        
        assert data["group_id"] == "test_group"
        assert data["name"] == "测试用户组"
        assert data["quota"]["max_agents"] == 10
        assert Permission.AGENT_CREATE.value in data["permissions"]

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "group_id": "test_group",
            "name": "测试用户组",
            "description": "测试描述",
            "group_type": "custom",
            "quota": {
                "max_agents": 10,
                "max_projects": 20,
            },
            "permissions": [Permission.AGENT_CREATE.value],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "is_active": True,
            "is_system": False,
        }
        
        group = UserGroup.from_dict(data)
        
        assert group.group_id == "test_group"
        assert group.name == "测试用户组"
        assert group.group_type == UserGroupType.CUSTOM
        assert group.quota.max_agents == 10
        assert Permission.AGENT_CREATE in group.permissions


class TestUserGroupManager:
    """测试用户组管理器"""

    @pytest.fixture
    def manager(self, tmp_path):
        """创建测试用的用户组管理器"""
        mgr = UserGroupManager({"data_dir": str(tmp_path)})
        mgr._on_init()
        return mgr

    def test_init_system_groups(self, manager):
        """测试初始化系统内置用户组"""
        groups = manager.list_groups()
        
        # 应该有5个系统内置用户组
        assert len(groups) == 5
        
        # 检查是否有超级管理员用户组
        super_admin = manager.get_group_by_type(UserGroupType.SUPER_ADMIN)
        assert super_admin is not None
        assert super_admin.name == "超级管理员"
        assert super_admin.is_system == True

    def test_create_custom_group(self, manager):
        """测试创建自定义用户组"""
        quota = ResourceQuota(max_agents=15)
        permissions = {Permission.AGENT_CREATE}
        
        group = manager.create_group(
            name="自定义用户组",
            description="测试自定义用户组",
            quota=quota,
            permissions=permissions,
        )
        
        assert group.group_id != ""
        assert group.name == "自定义用户组"
        assert group.group_type == UserGroupType.CUSTOM
        assert group.is_system == False
        assert group.quota.max_agents == 15
        
        # 验证是否保存成功
        loaded_group = manager.get_group(group.group_id)
        assert loaded_group is not None
        assert loaded_group.name == "自定义用户组"

    def test_update_group(self, manager):
        """测试更新用户组"""
        # 创建自定义用户组
        quota = ResourceQuota(max_agents=15)
        permissions = {Permission.AGENT_CREATE}
        
        group = manager.create_group(
            name="自定义用户组",
            description="测试",
            quota=quota,
            permissions=permissions,
        )
        
        # 更新用户组
        new_quota = ResourceQuota(max_agents=20)
        new_permissions = {Permission.AGENT_CREATE, Permission.PROJECT_CREATE}
        
        result = manager.update_group(
            group.group_id,
            name="更新后的用户组",
            quota=new_quota,
            permissions=new_permissions,
        )
        
        assert result == True
        
        # 验证更新
        updated_group = manager.get_group(group.group_id)
        assert updated_group.name == "更新后的用户组"
        assert updated_group.quota.max_agents == 20
        assert Permission.PROJECT_CREATE in updated_group.permissions

    def test_delete_group(self, manager):
        """测试删除用户组"""
        # 创建自定义用户组
        group = manager.create_group(
            name="要删除的用户组",
            description="测试",
            quota=ResourceQuota(),
            permissions=set(),
        )
        
        group_id = group.group_id
        
        # 删除用户组
        result = manager.delete_group(group_id)
        
        assert result == True
        
        # 验证删除
        deleted_group = manager.get_group(group_id)
        assert deleted_group is None

    def test_cannot_delete_system_group(self, manager):
        """测试不能删除系统内置用户组"""
        # 尝试删除超级管理员用户组
        result = manager.delete_group("group_super_admin")
        
        assert result == False
        
        # 验证仍然存在
        group = manager.get_group("group_super_admin")
        assert group is not None

    def test_check_permission(self, manager):
        """测试检查权限"""
        # 检查超级管理员权限
        result = manager.check_permission(
            "group_super_admin",
            Permission.USER_CREATE,
        )
        assert result == True
        
        # 检查普通用户权限
        result = manager.check_permission(
            "group_user",
            Permission.USER_CREATE,
        )
        assert result == False

    def test_get_user_quota(self, manager):
        """测试获取用户配额"""
        quota = manager.get_user_quota("group_user")
        
        assert quota is not None
        assert quota.max_agents == 5
        assert quota.max_projects == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
