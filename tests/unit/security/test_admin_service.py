"""
测试管理员服务
"""

import sys
import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

import pytest

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.auth.user_group_model import (
    UserGroupManager,
    UserGroupType,
    ResourceQuota,
    Permission,
)
from neurova.admin.resource_quota_manager import ResourceQuotaManager
from neurova.admin.admin_service import AdminService
from neurova.auth.enhanced_user_model import EnhancedUserModel


class TestAdminService:
    """测试管理员服务"""

    @pytest.fixture
    def setup(self, tmp_path):
        """设置测试环境"""
        # 创建用户组管理器
        group_manager = UserGroupManager(tmp_path)
        
        # 创建资源配额管理器
        quota_manager = ResourceQuotaManager(
            data_dir=tmp_path,
            group_manager=group_manager,
        )
        
        # 创建增强用户模型
        db_path = str(tmp_path / "enhanced_users.db")
        user_model = EnhancedUserModel(
            data_dir=tmp_path,
            db_path=db_path,
            group_manager=group_manager,
            quota_manager=quota_manager,
        )
        
        # 创建技能池管理器
        from neurova.skill_system.skill_pool_manager import SkillPoolManager
        skill_manager = SkillPoolManager(tmp_path)
        
        # 创建协作管理器
        from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager
        collab_manager = CollaborationIsolationManager(tmp_path)
        
        # 创建管理员服务
        admin_service = AdminService(
            data_dir=tmp_path,
            user_model=user_model,
            group_manager=group_manager,
            skill_manager=skill_manager,
            collab_manager=collab_manager,
        )
        
        return {
            "group_manager": group_manager,
            "quota_manager": quota_manager,
            "user_model": user_model,
            "skill_manager": skill_manager,
            "collab_manager": collab_manager,
            "admin_service": admin_service,
            "tmp_path": tmp_path,
        }

    def test_create_user(self, setup):
        """测试创建用户"""
        admin_service = setup["admin_service"]
        
        # 创建用户
        user = admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        assert user is not None
        assert user["username"] == "testuser"
        assert user["group_type"] == "user"
        
        # 验证用户是否创建成功
        retrieved = setup["user_model"].get_user_by_username("testuser")
        assert retrieved is not None
        assert retrieved["username"] == "testuser"

    def test_create_user_duplicate_username(self, setup):
        """测试创建重复用户名的用户"""
        admin_service = setup["admin_service"]
        
        # 创建第一个用户
        admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        # 尝试创建同名用户
        with pytest.raises(ValueError):
            admin_service.create_user(
                username="testuser",  # 重复用户名
                email="test2@example.com",
                password="password123",
                group_type=UserGroupType.USER,
            )

    def test_create_user_duplicate_email(self, setup):
        """测试创建重复邮箱的用户"""
        admin_service = setup["admin_service"]
        
        # 创建第一个用户
        admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        # 尝试创建同邮箱用户
        with pytest.raises(ValueError):
            admin_service.create_user(
                username="testuser2",
                email="test@example.com",  # 重复邮箱
                password="password123",
                group_type=UserGroupType.USER,
            )

    def test_delete_user(self, setup):
        """测试删除用户"""
        admin_service = setup["admin_service"]
        
        # 创建用户
        user = admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 删除用户
        result = admin_service.delete_user(user_id, backup_before_delete=False)
        
        assert result["user_id"] == user_id
        assert result["username"] == "testuser"
        
        # 验证用户是否删除成功
        retrieved = setup["user_model"].get_user_by_id(user_id)
        assert retrieved is None

    def test_delete_user_not_found(self, setup):
        """测试删除不存在的用户"""
        admin_service = setup["admin_service"]
        
        with pytest.raises(ValueError):
            admin_service.delete_user(999, backup_before_delete=False)

    def test_backup_user(self, setup):
        """测试备份用户资料"""
        admin_service = setup["admin_service"]
        
        # 创建用户
        user = admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 备份用户
        backup = admin_service.backup_user(user_id)
        
        assert backup.backup_id is not None
        assert backup.user_id == user_id
        assert backup.username == "testuser"
        assert backup.backup_file.exists()
        assert backup.backup_size > 0

    def test_backup_user_not_found(self, setup):
        """测试备份不存在的用户"""
        admin_service = setup["admin_service"]
        
        with pytest.raises(ValueError):
            admin_service.backup_user(999)

    def test_restore_user(self, setup):
        """测试从备份恢复用户"""
        admin_service = setup["admin_service"]
        
        # 创建用户
        user = admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 备份用户
        backup = admin_service.backup_user(user_id)
        backup_id = backup.backup_id
        
        # 删除用户
        admin_service.delete_user(user_id, backup_before_delete=False)
        
        # 恢复用户
        result = admin_service.restore_user(backup_id)
        
        assert result["user_id"] == user_id
        assert result["username"] == "testuser"
        
        # 验证用户是否恢复成功
        retrieved = setup["user_model"].get_user_by_id(user_id)
        assert retrieved is not None
        assert retrieved["username"] == "testuser"

    def test_restore_user_backup_not_found(self, setup):
        """测试从不存在的备份恢复用户"""
        admin_service = setup["admin_service"]
        
        with pytest.raises(ValueError):
            admin_service.restore_user("non-existent-backup")

    def test_list_backups(self, setup):
        """测试列出备份"""
        admin_service = setup["admin_service"]
        
        # 创建用户
        user = admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        # 创建两个备份
        admin_service.backup_user(user["id"])
        admin_service.backup_user(user["id"])
        
        # 列出备份
        backups = admin_service.list_backups()
        
        assert len(backups) == 2

    def test_delete_backup(self, setup):
        """测试删除备份"""
        admin_service = setup["admin_service"]
        
        # 创建用户
        user = admin_service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        # 创建备份
        backup = admin_service.backup_user(user["id"])
        backup_id = backup.backup_id
        
        # 验证备份文件存在
        assert backup.backup_file.exists()
        
        # 删除备份
        result = admin_service.delete_backup(backup_id)
        
        assert result == True
        
        # 验证备份文件已删除
        assert not backup.backup_file.exists()

    def test_delete_backup_not_found(self, setup):
        """测试删除不存在的备份"""
        admin_service = setup["admin_service"]
        
        result = admin_service.delete_backup("non-existent-backup")
        
        assert result == False

    def test_get_system_stats(self, setup):
        """测试获取系统统计信息"""
        admin_service = setup["admin_service"]
        
        # 创建两个用户
        admin_service.create_user(
            username="testuser1",
            email="test1@example.com",
            password="password123",
            group_type=UserGroupType.USER,
        )
        
        admin_service.create_user(
            username="testuser2",
            email="test2@example.com",
            password="password123",
            group_type=UserGroupType.DEVELOPER,
        )
        
        # 获取系统统计
        stats = admin_service.get_system_stats()
        
        assert stats["total_users"] == 2
        assert "group_stats" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
