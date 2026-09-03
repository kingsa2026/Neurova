"""
测试用户工作空间管理器
"""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from neurova.core.user_workspace import (
    UserWorkspace,
    UserWorkspaceManager,
    get_workspace_manager,
    init_workspace_manager,
)


class TestUserWorkspace:
    """测试UserWorkspace类"""
    
    def test_init(self, tmp_path):
        """测试初始化"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        assert workspace.user_id == "user1"
        assert workspace.workspace_root.exists()
    
    def test_workspace_directories(self, tmp_path):
        """测试工作空间目录结构"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        assert workspace.database_path.exists()
        assert workspace.memory_path.exists()
        assert workspace.projects_path.exists()
        assert workspace.skills_path.exists()
        assert workspace.channels_path.exists()
        assert workspace.workflows_path.exists()
        assert workspace.attachments_path.exists()
        assert workspace.logs_path.exists()
        assert workspace.cache_path.exists()
    
    def test_get_config(self, tmp_path):
        """测试获取配置"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        language = workspace.get_config("language")
        
        assert language == "zh_CN"
    
    def test_get_config_default(self, tmp_path):
        """测试获取默认配置"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        value = workspace.get_config("nonexistent_key", "default_value")
        
        assert value == "default_value"
    
    def test_set_config(self, tmp_path):
        """测试设置配置"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        workspace.set_config("test_key", "test_value")
        
        assert workspace.get_config("test_key") == "test_value"
    
    def test_get_size(self, tmp_path):
        """测试获取工作空间大小"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        size = workspace.get_size()
        
        assert size >= 0
    
    def test_delete(self, tmp_path):
        """测试删除工作空间"""
        workspace = UserWorkspace("user1", str(tmp_path))
        
        workspace.delete()
        
        assert not workspace.workspace_root.exists()


class TestUserWorkspaceManager:
    """测试UserWorkspaceManager类"""
    
    def test_init_default(self, tmp_path):
        """测试默认初始化"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        assert manager.workspace_root == tmp_path
        assert manager._workspaces == {}
    
    def test_init_custom_root(self, tmp_path):
        """测试自定义根目录"""
        custom_root = tmp_path / "custom_workspaces"
        manager = UserWorkspaceManager(str(custom_root))
        
        assert manager.workspace_root == custom_root
        assert custom_root.exists()
    
    def test_get_workspace(self, tmp_path):
        """测试获取工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        workspace = manager.get_workspace("user1")
        
        assert workspace is not None
        assert workspace.user_id == "user1"
    
    def test_get_workspace_caching(self, tmp_path):
        """测试工作空间缓存"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        workspace1 = manager.get_workspace("user1")
        workspace2 = manager.get_workspace("user1")
        
        assert workspace1 is workspace2
    
    def test_create_workspace(self, tmp_path):
        """测试创建工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        workspace = manager.create_workspace("user1")
        
        assert workspace is not None
        assert workspace.user_id == "user1"
        assert workspace.workspace_root.exists()
    
    def test_create_workspace_existing(self, tmp_path):
        """测试创建已存在的工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        workspace1 = manager.create_workspace("user1")
        workspace2 = manager.create_workspace("user1")
        
        assert workspace1 is workspace2
    
    def test_delete_workspace(self, tmp_path):
        """测试删除工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        manager.create_workspace("user1")
        success = manager.delete_workspace("user1")
        
        assert success is True
        assert "user1" not in manager._workspaces
    
    def test_delete_workspace_nonexistent(self, tmp_path):
        """测试删除不存在的工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        success = manager.delete_workspace("nonexistent_user")
        
        assert success is False
    
    def test_list_workspaces(self, tmp_path):
        """测试列出工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        manager.create_workspace("user1")
        manager.create_workspace("user2")
        
        workspaces = manager.list_workspaces()
        
        assert len(workspaces) == 2
        assert "user1" in workspaces
        assert "user2" in workspaces
    
    def test_get_all_workspaces(self, tmp_path):
        """测试获取所有工作空间"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        manager.create_workspace("user1")
        manager.create_workspace("user2")
        
        all_workspaces = manager.get_all_workspaces()
        
        assert len(all_workspaces) == 2
        assert "user1" in all_workspaces
        assert "user2" in all_workspaces
    
    def test_workspace_exists(self, tmp_path):
        """测试检查工作空间是否存在"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        assert manager.workspace_exists("user1") is False
        
        manager.create_workspace("user1")
        
        assert manager.workspace_exists("user1") is True
    
    def test_get_workspace_stats(self, tmp_path):
        """测试获取工作空间统计"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        manager.create_workspace("user1")
        stats = manager.get_workspace_stats("user1")
        
        assert stats is not None
        assert stats["user_id"] == "user1"
        assert "size_bytes" in stats
        assert "size_mb" in stats
        assert "config" in stats
    
    def test_get_workspace_stats_nonexistent(self, tmp_path):
        """测试获取不存在的工作空间统计"""
        manager = UserWorkspaceManager(str(tmp_path))
        
        stats = manager.get_workspace_stats("nonexistent_user")
        
        assert stats is None


class TestGlobalFunctions:
    """测试全局函数"""
    
    def test_init_workspace_manager(self, tmp_path):
        """测试初始化工作空间管理器"""
        manager = init_workspace_manager(str(tmp_path))
        
        assert manager is not None
        assert manager.workspace_root == tmp_path
    
    def test_get_workspace_manager(self, tmp_path):
        """测试获取全局工作空间管理器"""
        manager1 = get_workspace_manager()
        manager2 = get_workspace_manager()
        
        assert manager1 is manager2


class TestUserWorkspaceIntegration:
    """测试UserWorkspace集成功能"""
    
    def test_config_persistence(self, tmp_path):
        """测试配置持久化"""
        workspace1 = UserWorkspace("user1", str(tmp_path))
        workspace1.set_config("test_key", "test_value")
        
        workspace2 = UserWorkspace("user1", str(tmp_path))
        
        assert workspace2.get_config("test_key") == "test_value"
    
    def test_multi_user_isolation(self, tmp_path):
        """测试多用户隔离"""
        workspace1 = UserWorkspace("user1", str(tmp_path))
        workspace2 = UserWorkspace("user2", str(tmp_path))
        
        workspace1.set_config("shared_key", "value1")
        workspace2.set_config("shared_key", "value2")
        
        assert workspace1.get_config("shared_key") == "value1"
        assert workspace2.get_config("shared_key") == "value2"
        assert workspace1.workspace_root != workspace2.workspace_root
