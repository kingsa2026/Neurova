"""
测试增强用户模型
"""
import os

import sys
import sqlite3
import bcrypt
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set

import pytest

# 凭据统一从环境变量取默认值，避免源码中出现凭据字面量（安全扫描要求）
TEST_PASSWORD = os.environ.get("NEUROVA_TEST_PASSWORD", "pw-" + __import__("uuid").uuid4().hex[:12])
TEST_PASSWORD_ALT = TEST_PASSWORD + "-alt"
TEST_EMAIL = "tester-" + __import__("uuid").uuid4().hex[:8] + "@invalid.local"
TEST_EMAIL_ALT = "tester-" + __import__("uuid").uuid4().hex[:8] + "@invalid.local"


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
from neurova.auth.enhanced_user_model import EnhancedUserModel


class TestEnhancedUserModel:
    """测试增强用户模型"""

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
        
        return {
            "group_manager": group_manager,
            "quota_manager": quota_manager,
            "user_model": user_model,
            "tmp_path": tmp_path,
        }

    def test_init_db(self, setup):
        """测试初始化数据库"""
        user_model = setup["user_model"]
        
        # 验证表是否创建
        conn = user_model._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enhanced_users'")
        result = cursor.fetchone()
        
        conn.close()
        
        assert result is not None

    def test_create_user(self, setup):
        """测试创建用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        assert user is not None
        assert user["username"] == "testuser"
        assert user["email"] == TEST_EMAIL
        assert user["group_type"] == "user"
        
        # 验证密码是否加密
        assert user["password_hash"] != TEST_PASSWORD
        
        # 验证用户是否保存成功
        retrieved = user_model.get_user_by_id(user["id"])
        assert retrieved is not None
        assert retrieved["username"] == "testuser"

    def test_create_user_duplicate_username(self, setup):
        """测试创建重复用户名的用户"""
        user_model = setup["user_model"]
        
        # 创建第一个用户
        user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 尝试创建同名用户
        user = user_model.create_user(
            username="testuser",  # 重复用户名
            password=TEST_PASSWORD_ALT,
            email=TEST_EMAIL_ALT,
            group_type=UserGroupType.USER,
        )
        
        assert user is None  # 应该返回None

    def test_create_user_duplicate_email(self, setup):
        """测试创建重复邮箱的用户"""
        user_model = setup["user_model"]
        
        # 创建第一个用户
        user_model.create_user(
            username="testuser1",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 尝试创建同邮箱用户
        user = user_model.create_user(
            username="testuser2",
            password=TEST_PASSWORD_ALT,
            email=TEST_EMAIL,  # 重复邮箱
            group_type=UserGroupType.USER,
        )
        
        assert user is None  # 应该返回None

    def test_get_user_by_id(self, setup):
        """测试根据ID获取用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 获取用户
        retrieved = user_model.get_user_by_id(user_id)
        
        assert retrieved is not None
        assert retrieved["id"] == user_id
        assert retrieved["username"] == "testuser"

    def test_get_user_by_id_not_found(self, setup):
        """测试获取不存在的用户"""
        user_model = setup["user_model"]
        
        retrieved = user_model.get_user_by_id(999)
        
        assert retrieved is None

    def test_get_user_by_username(self, setup):
        """测试根据用户名获取用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 获取用户
        retrieved = user_model.get_user_by_username("testuser")
        
        assert retrieved is not None
        assert retrieved["username"] == "testuser"

    def test_get_user_by_username_not_found(self, setup):
        """测试获取不存在的用户"""
        user_model = setup["user_model"]
        
        retrieved = user_model.get_user_by_username("nonexistent")
        
        assert retrieved is None

    def test_get_user_by_email(self, setup):
        """测试根据邮箱获取用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 获取用户
        retrieved = user_model.get_user_by_email(TEST_EMAIL)
        
        assert retrieved is not None
        assert retrieved["email"] == TEST_EMAIL

    def test_get_user_by_email_not_found(self, setup):
        """测试获取不存在的用户"""
        user_model = setup["user_model"]
        
        retrieved = user_model.get_user_by_email("nonexistent@example.com")
        
        assert retrieved is None

    def test_list_users(self, setup):
        """测试列出用户"""
        user_model = setup["user_model"]
        
        # 创建两个用户
        user_model.create_user(
            username="testuser1",
            password=TEST_PASSWORD,
            email="test1@example.com",
            group_type=UserGroupType.USER,
        )
        
        user_model.create_user(
            username="testuser2",
            password=TEST_PASSWORD_ALT,
            email=TEST_EMAIL_ALT,
            group_type=UserGroupType.DEVELOPER,
        )
        
        # 列出用户
        users = user_model.list_users()
        
        assert len(users) == 2

    def test_list_users_with_group_type_filter(self, setup):
        """测试按用户组过滤列出用户"""
        user_model = setup["user_model"]
        
        # 创建两个用户（不同用户组）
        user_model.create_user(
            username="testuser1",
            password=TEST_PASSWORD,
            email="test1@example.com",
            group_type=UserGroupType.USER,
        )
        
        user_model.create_user(
            username="testuser2",
            password=TEST_PASSWORD_ALT,
            email=TEST_EMAIL_ALT,
            group_type=UserGroupType.DEVELOPER,
        )
        
        # 按用户组过滤
        users = user_model.list_users(group_type=UserGroupType.USER)
        
        assert len(users) == 1
        assert users[0]["group_type"] == "user"

    def test_list_users_with_status_filter(self, setup):
        """测试按状态过滤列出用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 更新用户状态
        user_model.update_user(user_id, status="inactive")
        
        # 按状态过滤
        users = user_model.list_users(status="inactive")
        
        assert len(users) == 1
        assert users[0]["status"] == "inactive"

    def test_count_users(self, setup):
        """测试获取用户总数"""
        user_model = setup["user_model"]
        
        # 创建两个用户
        user_model.create_user(
            username="testuser1",
            password=TEST_PASSWORD,
            email="test1@example.com",
            group_type=UserGroupType.USER,
        )
        
        user_model.create_user(
            username="testuser2",
            password=TEST_PASSWORD_ALT,
            email=TEST_EMAIL_ALT,
            group_type=UserGroupType.DEVELOPER,
        )
        
        # 获取用户总数
        count = user_model.count_users()
        
        assert count == 2

    def test_update_user(self, setup):
        """测试更新用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 更新用户
        result = user_model.update_user(
            user_id,
            username="updateduser",
            email="updated@example.com",
        )
        
        assert result is True
        
        # 验证更新
        updated = user_model.get_user_by_id(user_id)
        assert updated["username"] == "updateduser"
        assert updated["email"] == "updated@example.com"

    def test_update_user_not_found(self, setup):
        """测试更新不存在的用户"""
        user_model = setup["user_model"]
        
        result = user_model.update_user(999, username="updateduser")
        
        assert result is False

    def test_update_user_password(self, setup):
        """测试更新用户密码"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        old_password_hash = user["password_hash"]
        
        # 更新密码
        new_password_hash = bcrypt.hashpw("newpassword".encode(), bcrypt.gensalt()).decode()
        result = user_model.update_user(user_id, password_hash=new_password_hash)
        
        assert result is True
        
        # 验证密码已更新
        updated = user_model.get_user_by_id(user_id)
        assert updated["password_hash"] != old_password_hash

    def test_delete_user(self, setup):
        """测试删除用户"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 删除用户
        result = user_model.delete_user(user_id)
        
        assert result is True
        
        # 验证删除
        deleted = user_model.get_user_by_id(user_id)
        assert deleted is None

    def test_delete_user_not_found(self, setup):
        """测试删除不存在的用户"""
        user_model = setup["user_model"]
        
        result = user_model.delete_user(999)
        
        assert result is False

    def test_authenticate_user(self, setup):
        """测试验证用户登录"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 验证登录
        authenticated = user_model.authenticate_user("testuser", TEST_PASSWORD)
        
        assert authenticated is not None
        assert authenticated["username"] == "testuser"

    def test_authenticate_user_wrong_password(self, setup):
        """测试验证用户登录（错误密码）"""
        user_model = setup["user_model"]
        
        # 创建用户
        user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 验证登录（错误密码）
        authenticated = user_model.authenticate_user("testuser", "wrongpassword")
        
        assert authenticated is None

    def test_authenticate_user_not_found(self, setup):
        """测试验证用户登录（用户不存在）"""
        user_model = setup["user_model"]
        
        authenticated = user_model.authenticate_user("nonexistent", TEST_PASSWORD)
        
        assert authenticated is None

    def test_authenticate_user_locked(self, setup):
        """测试验证用户登录（账号锁定）"""
        user_model = setup["user_model"]
        
        # 创建用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        user_id = user["id"]
        
        # 锁定账号
        user_model.update_user(
            user_id,
            status="locked",
            locked_until=(datetime.now() + timedelta(minutes=30)).isoformat(),
        )
        
        # 验证登录（账号锁定）
        authenticated = user_model.authenticate_user("testuser", TEST_PASSWORD)
        
        assert authenticated is None

    def test_get_user_permissions(self, setup):
        """测试获取用户权限集合"""
        user_model = setup["user_model"]
        
        # 创建普通用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 获取权限
        permissions = user_model.get_user_permissions(user["id"])
        
        assert isinstance(permissions, set)
        # 普通用户应该有AGENT_CREATE权限
        assert Permission.AGENT_CREATE in permissions

    def test_get_user_permissions_not_found(self, setup):
        """测试获取不存在的用户权限"""
        user_model = setup["user_model"]
        
        permissions = user_model.get_user_permissions(999)
        
        assert len(permissions) == 0

    def test_check_user_permission(self, setup):
        """测试检查用户是否拥有某个权限"""
        user_model = setup["user_model"]
        
        # 创建普通用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 检查权限
        has_permission = user_model.check_user_permission(
            user["id"],
            Permission.AGENT_CREATE,
        )
        
        assert has_permission is True

    def test_check_user_permission_not_found(self, setup):
        """测试检查不存在的用户权限"""
        user_model = setup["user_model"]
        
        has_permission = user_model.check_user_permission(
            999,
            Permission.AGENT_CREATE,
        )
        
        assert has_permission is False

    def test_get_user_quota(self, setup):
        """测试获取用户的资源配额"""
        user_model = setup["user_model"]
        
        # 创建普通用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 获取配额
        quota = user_model.get_user_quota(user["id"])
        
        assert quota is not None
        assert quota.max_agents == 5
        assert quota.max_projects == 10

    def test_get_user_quota_not_found(self, setup):
        """测试获取不存在的用户配额"""
        user_model = setup["user_model"]
        
        quota = user_model.get_user_quota(999)
        
        assert quota is None

    def test_get_user_usage(self, setup):
        """测试获取用户的资源使用量"""
        user_model = setup["user_model"]
        
        # 创建普通用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 获取使用量
        usage = user_model.get_user_usage(user["id"])
        
        assert usage is not None
        assert usage.user_id == str(user["id"])
        assert usage.agent_count == 0

    def test_get_user_usage_not_found(self, setup):
        """测试获取不存在的用户使用量"""
        user_model = setup["user_model"]
        quota_manager = setup["quota_manager"]
        
        # 获取使用量
        usage = quota_manager.get_usage("999")
        
        assert usage is not None  # 应该创建新的使用量记录
        assert usage.user_id == "999"

    def test_get_user_quota_status(self, setup):
        """测试获取用户配额状态"""
        user_model = setup["user_model"]
        
        # 创建普通用户
        user = user_model.create_user(
            username="testuser",
            password=TEST_PASSWORD,
            email=TEST_EMAIL,
            group_type=UserGroupType.USER,
        )
        
        # 获取配额状态
        status = user_model.get_user_quota_status(user["id"])
        
        assert status is not None
        assert "quota" in status
        assert "usage" in status
        assert "remaining" in status
        
        # 检查配额
        assert status["quota"]["max_agents"] == 5
        assert status["usage"]["agent_count"] == 0
        assert status["remaining"]["agents"] == 5

    def test_get_user_quota_status_not_found(self, setup):
        """测试获取不存在的用户配额状态"""
        user_model = setup["user_model"]
        
        status = user_model.get_user_quota_status(999)
        
        assert status is None

    def test_migrate_db(self, setup, tmp_path):
        """测试数据库迁移"""
        user_model = setup["user_model"]
        
        # 创建旧表
        conn = user_model._get_conn()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_login TEXT,
                login_count INTEGER DEFAULT 0,
                failed_attempts INTEGER DEFAULT 0,
                locked_until TEXT,
                reset_token TEXT,
                reset_token_expires TEXT
            )
        ''')
        
        # 插入旧数据
        password_hash = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
        cursor.execute('''
            INSERT INTO users (username, email, password_hash, role)
            VALUES (?, ?, ?, ?)
        ''', ("olduser", "old@example.com", password_hash, "admin"))
        
        conn.commit()
        conn.close()
        
        # 重新初始化用户模型（触发迁移）
        db_path = str(tmp_path / "enhanced_users.db")
        new_user_model = EnhancedUserModel(
            data_dir=tmp_path,
            db_path=db_path,
            group_manager=setup["group_manager"],
            quota_manager=setup["quota_manager"],
        )
        
        # 验证迁移
        user = new_user_model.get_user_by_username("olduser")
        assert user is not None
        assert user["group_type"] == "admin"  # role应该映射到group_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
