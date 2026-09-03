"""
测试资源配额管理器
"""

import sys
from pathlib import Path
from datetime import datetime, date, timezone
from typing import Set

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
from neurova.admin.resource_quota_manager import ResourceQuotaManager, ResourceUsage


class TestResourceUsage:
    """测试资源使用量记录"""

    def test_init(self):
        """测试初始化"""
        usage = ResourceUsage("user-1")
        
        assert usage.user_id == "user-1"
        assert usage.agent_count == 0
        assert usage.project_count == 0
        assert usage.daily_llm_calls == 0
        assert usage.storage_used_mb == 0.0

    def test_reset_daily_usage(self):
        """测试重置每日使用量"""
        usage = ResourceUsage("user-1")
        usage.daily_llm_calls = 100
        usage.daily_llm_tokens = 5000
        usage.daily_api_calls = 200
        
        # 重置
        usage.reset_daily_usage()
        
        assert usage.daily_llm_calls == 0
        assert usage.daily_llm_tokens == 0
        assert usage.daily_api_calls == 0

    def test_check_daily_reset(self):
        """测试检查是否需要重置每日使用量"""
        usage = ResourceUsage("user-1")
        usage.daily_llm_calls = 100
        
        # 模拟昨天
        usage.last_daily_reset = date.today().replace(day=1)
        
        # 检查并重置
        usage.check_daily_reset()
        
        # 应该已重置
        assert usage.daily_llm_calls == 0
        assert usage.last_daily_reset == date.today()

    def test_to_dict(self):
        """测试转换为字典"""
        usage = ResourceUsage("user-1")
        usage.agent_count = 5
        usage.project_count = 10
        
        data = usage.to_dict()
        
        assert data["user_id"] == "user-1"
        assert data["agent_count"] == 5
        assert data["project_count"] == 10

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "user_id": "user-1",
            "agent_count": 5,
            "project_count": 10,
            "private_skill_count": 20,
            "storage_used_mb": 500.0,
            "daily_llm_calls": 100,
            "daily_llm_tokens": 5000,
            "daily_api_calls": 200,
            "concurrent_sessions": 2,
            "team_member_count": 5,
            "collab_project_count": 3,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "last_daily_reset": date.today().isoformat(),
        }
        
        usage = ResourceUsage.from_dict(data)
        
        assert usage.user_id == "user-1"
        assert usage.agent_count == 5
        assert usage.project_count == 10
        assert usage.daily_llm_calls == 100


class TestResourceQuotaManager:
    """测试资源配额管理器"""

    @pytest.fixture
    def manager(self, tmp_path):
        """创建测试用的资源配额管理器"""
        # 创建用户组管理器
        group_manager = UserGroupManager({"data_dir": str(tmp_path)})
        group_manager._on_init()
        
        # 创建资源配额管理器
        quota_manager = ResourceQuotaManager({"data_dir": str(tmp_path)})
        quota_manager.group_manager = group_manager
        quota_manager._load_usage()
        
        return quota_manager

    def test_init(self, manager):
        """测试初始化"""
        assert manager.data_dir is not None
        assert manager.group_manager is not None
        assert len(manager._usage) == 0

    def test_get_or_create_usage(self, manager):
        """测试获取或创建资源使用量记录"""
        # 获取不存在的使用量记录
        usage = manager._get_or_create_usage("user-1")
        
        assert usage is not None
        assert usage.user_id == "user-1"
        assert "user-1" in manager._usage
        
        # 再次获取同一个用户的记录
        usage2 = manager._get_or_create_usage("user-1")
        
        assert usage is usage2  # 应该是同一个对象

    def test_get_user_quota(self, manager):
        """测试获取用户资源配额"""
        quota = manager.get_user_quota("user-1", UserGroupType.USER)
        
        assert quota is not None
        assert quota.max_agents == 5
        assert quota.max_projects == 10
        assert quota.max_llm_calls_per_day == 1000

    def test_get_usage(self, manager):
        """测试获取用户资源使用量"""
        usage = manager.get_usage("user-1")
        
        assert usage is not None
        assert usage.user_id == "user-1"
        assert usage.agent_count == 0

    def test_check_agent_quota(self, manager):
        """测试检查Agent配额"""
        # 检查配额
        allowed, error = manager.check_agent_quota("user-1", UserGroupType.USER)
        
        assert allowed == True
        assert error == ""
        
        # 增加Agent数量到上限
        manager.increment_agent_count("user-1", 5)
        
        # 再次检查配额
        allowed, error = manager.check_agent_quota("user-1", UserGroupType.USER)
        
        assert allowed == False
        assert "已达上限" in error

    def test_check_project_quota(self, manager):
        """测试检查项目配额"""
        # 检查配额
        allowed, error = manager.check_project_quota("user-1", UserGroupType.USER)
        
        assert allowed == True
        assert error == ""
        
        # 增加项目数量到上限
        manager.increment_project_count("user-1", 10)
        
        # 再次检查配额
        allowed, error = manager.check_project_quota("user-1", UserGroupType.USER)
        
        assert allowed == False
        assert "已达上限" in error

    def test_check_llm_call_quota(self, manager):
        """测试检查LLM调用次数配额"""
        # 检查配额
        allowed, error = manager.check_llm_call_quota("user-1", UserGroupType.USER)
        
        assert allowed == True
        assert error == ""
        
        # 增加LLM调用次数到上限
        for _ in range(1000):
            manager.increment_llm_call("user-1")
        
        # 再次检查配额
        allowed, error = manager.check_llm_call_quota("user-1", UserGroupType.USER)
        
        assert allowed == False
        assert "已达上限" in error

    def test_check_storage_quota(self, manager):
        """测试检查存储配额"""
        # 检查配额
        allowed, error = manager.check_storage_quota("user-1", UserGroupType.USER, 100.0)
        
        assert allowed == True
        assert error == ""
        
        # 增加存储空间使用量到上限
        manager.increment_storage("user-1", 1024.0)
        
        # 再次检查配额
        allowed, error = manager.check_storage_quota("user-1", UserGroupType.USER, 1.0)
        
        assert allowed == False
        assert "已达上限" in error

    def test_increment_agent_count(self, manager):
        """测试增加Agent数量"""
        manager.increment_agent_count("user-1", 3)
        
        usage = manager.get_usage("user-1")
        assert usage.agent_count == 3

    def test_decrement_agent_count(self, manager):
        """测试减少Agent数量"""
        manager.increment_agent_count("user-1", 5)
        manager.decrement_agent_count("user-1", 2)
        
        usage = manager.get_usage("user-1")
        assert usage.agent_count == 3

    def test_increment_project_count(self, manager):
        """测试增加项目数量"""
        manager.increment_project_count("user-1", 5)
        
        usage = manager.get_usage("user-1")
        assert usage.project_count == 5

    def test_decrement_project_count(self, manager):
        """测试减少项目数量"""
        manager.increment_project_count("user-1", 10)
        manager.decrement_project_count("user-1", 3)
        
        usage = manager.get_usage("user-1")
        assert usage.project_count == 7

    def test_increment_llm_call(self, manager):
        """测试增加LLM调用次数"""
        manager.increment_llm_call("user-1", 5000)
        
        usage = manager.get_usage("user-1")
        assert usage.daily_llm_calls == 1
        assert usage.daily_llm_tokens == 5000

    def test_increment_storage(self, manager):
        """测试增加存储空间使用量"""
        manager.increment_storage("user-1", 500.0)
        
        usage = manager.get_usage("user-1")
        assert usage.storage_used_mb == 500.0

    def test_decrement_storage(self, manager):
        """测试减少存储空间使用量"""
        manager.increment_storage("user-1", 1000.0)
        manager.decrement_storage("user-1", 300.0)
        
        usage = manager.get_usage("user-1")
        assert usage.storage_used_mb == 700.0

    def test_get_quota_status(self, manager):
        """测试获取用户配额状态"""
        # 增加一些使用量
        manager.increment_agent_count("user-1", 2)
        manager.increment_project_count("user-1", 3)
        manager.increment_llm_call("user-1", 500)
        manager.increment_storage("user-1", 500.0)
        
        # 获取配额状态
        status = manager.get_quota_status("user-1", UserGroupType.USER)
        
        assert status is not None
        assert "quota" in status
        assert "usage" in status
        assert "remaining" in status
        
        # 检查配额
        assert status["quota"]["max_agents"] == 5
        assert status["usage"]["agent_count"] == 2
        assert status["remaining"]["agents"] == 3
        
        assert status["quota"]["max_projects"] == 10
        assert status["usage"]["project_count"] == 3
        assert status["remaining"]["projects"] == 7
        
        assert status["quota"]["max_llm_calls_per_day"] == 1000
        assert status["usage"]["daily_llm_calls"] == 1
        assert status["remaining"]["llm_calls_today"] == 999
        
        assert status["quota"]["max_storage_mb"] == 1024
        assert status["usage"]["storage_used_mb"] == 500.0
        assert status["remaining"]["storage_mb"] == 524.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
