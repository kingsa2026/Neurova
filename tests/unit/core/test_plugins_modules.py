"""
测试 plugins 模块的实现
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


class TestPluginRecord:
    """测试 PluginRecord 数据类"""
    
    def test_plugin_record_creation(self):
        """测试 PluginRecord 创建"""
        from neurova.plugins.plugin_manager import PluginRecord
        
        record = PluginRecord(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            author="test",
            enabled=True
        )
        
        assert record.name == "test-plugin"
        assert record.version == "1.0.0"
        assert record.description == "A test plugin"
        assert record.author == "test"
        assert record.enabled is True
    
    def test_plugin_record_to_dict(self):
        """测试 PluginRecord 转字典"""
        from neurova.plugins.plugin_manager import PluginRecord
        
        record = PluginRecord(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin"
        )
        
        data = record.to_dict()
        assert isinstance(data, dict)
        assert data["name"] == "test-plugin"
        assert data["version"] == "1.0.0"
    
    def test_plugin_record_from_dict(self):
        """测试从字典创建 PluginRecord"""
        from neurova.plugins.plugin_manager import PluginRecord
        
        data = {
            "name": "test-plugin",
            "version": "1.0.0",
            "description": "A test plugin"
        }
        
        record = PluginRecord.from_dict(data)
        assert record.name == "test-plugin"
        assert record.version == "1.0.0"


class TestPluginManager:
    """测试 PluginManager 类"""
    
    def test_manager_initialization(self):
        """测试 PluginManager 初始化"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        assert manager is not None
        assert hasattr(manager, 'discover_plugins')
        assert hasattr(manager, 'install_plugin')
        assert hasattr(manager, 'load_plugin')
    
    def test_set_plugin_dir(self):
        """测试设置插件目录"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        test_dir = "/path/to/plugins"
        
        manager.set_plugin_dir(test_dir)
        assert manager.plugin_dir == test_dir
    
    def test_discover_plugins(self):
        """测试发现插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件目录
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.iterdir', return_value=[]):
                plugins = manager.discover_plugins()
                
                assert isinstance(plugins, list)
    
    def test_install_plugin(self):
        """测试安装插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件源
        mock_plugin_path = MagicMock()
        mock_plugin_path.exists.return_value = True
        mock_plugin_path.is_dir.return_value = True
        
        with patch.object(manager, '_load_manifest', return_value={"name": "test-plugin"}):
            result = manager.install_plugin(mock_plugin_path)
            
            assert result is True
    
    def test_uninstall_plugin(self):
        """测试卸载插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # 先安装一个插件
        mock_plugin_path = MagicMock()
        mock_plugin_path.exists.return_value = True
        mock_plugin_path.is_dir.return_value = True
        
        with patch.object(manager, '_load_manifest', return_value={"name": "test-plugin"}):
            manager.install_plugin(mock_plugin_path)
        
        # 卸载插件
        result = manager.uninstall_plugin("test-plugin")
        assert result is True
    
    def test_load_plugin(self):
        """测试加载插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        mock_record.path = "/path/to/plugin"
        mock_record.enabled = True
        
        with patch.object(manager, 'get_plugin', return_value=mock_record):
            with patch.object(manager, '_load_plugin_module', return_value=MagicMock()):
                result = manager.load_plugin("test-plugin")
                
                assert result is True
    
    def test_unload_plugin(self):
        """测试卸载插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        mock_record.loaded = True
        
        with patch.object(manager, 'get_plugin', return_value=mock_record):
            result = manager.unload_plugin("test-plugin")
            
            assert result is True
    
    def test_enable_plugin(self):
        """测试启用插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        mock_record.enabled = False
        
        with patch.object(manager, 'get_plugin', return_value=mock_record):
            result = manager.enable_plugin("test-plugin")
            
            assert result is True
            assert mock_record.enabled is True
    
    def test_disable_plugin(self):
        """测试禁用插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        mock_record.enabled = True
        
        with patch.object(manager, 'get_plugin', return_value=mock_record):
            result = manager.disable_plugin("test-plugin")
            
            assert result is True
            assert mock_record.enabled is False
    
    def test_check_dependencies(self):
        """测试检查依赖"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        mock_record.dependencies = ["dep1", "dep2"]
        
        # Mock 依赖插件
        mock_dep1 = MagicMock()
        mock_dep1.name = "dep1"
        mock_dep1.enabled = True
        
        mock_dep2 = MagicMock()
        mock_dep2.name = "dep2"
        mock_dep2.enabled = True
        
        with patch.object(manager, 'get_plugin', side_effect=[mock_dep1, mock_dep2]):
            result = manager._check_dependencies(mock_record)
            
            assert result is True
    
    def test_resolve_load_order(self):
        """测试解析加载顺序"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件记录
        mock_plugin1 = MagicMock()
        mock_plugin1.name = "plugin1"
        mock_plugin1.dependencies = []
        
        mock_plugin2 = MagicMock()
        mock_plugin2.name = "plugin2"
        mock_plugin2.dependencies = ["plugin1"]
        
        with patch.object(manager, 'list_plugins', return_value=[mock_plugin1, mock_plugin2]):
            order = manager.resolve_load_order()
            
            assert isinstance(order, list)
            assert len(order) == 2
            assert order[0] == "plugin1"
            assert order[1] == "plugin2"
    
    def test_load_all(self):
        """测试加载所有插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # Mock 插件列表
        mock_plugins = [
            MagicMock(name="plugin1", enabled=True),
            MagicMock(name="plugin2", enabled=True)
        ]
        
        with patch.object(manager, 'list_plugins', return_value=mock_plugins):
            with patch.object(manager, 'load_plugin', return_value=True):
                result = manager.load_all()
                
                assert result == 2
    
    def test_get_plugin(self):
        """测试获取插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # 添加插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        manager._plugins = {"test-plugin": mock_record}
        
        result = manager.get_plugin("test-plugin")
        assert result is mock_record
    
    def test_list_plugins(self):
        """测试列出插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # 添加插件记录
        mock_record1 = MagicMock()
        mock_record1.name = "plugin1"
        mock_record2 = MagicMock()
        mock_record2.name = "plugin2"
        
        manager._plugins = {
            "plugin1": mock_record1,
            "plugin2": mock_record2
        }
        
        plugins = manager.list_plugins()
        assert isinstance(plugins, list)
        assert len(plugins) == 2
    
    def test_has_plugin(self):
        """测试检查插件是否存在"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # 添加插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        manager._plugins = {"test-plugin": mock_record}
        
        assert manager.has_plugin("test-plugin") is True
        assert manager.has_plugin("nonexistent") is False
    
    def test_get_enabled_plugins(self):
        """测试获取已启用的插件"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # 添加插件记录
        mock_record1 = MagicMock()
        mock_record1.name = "plugin1"
        mock_record1.enabled = True
        
        mock_record2 = MagicMock()
        mock_record2.name = "plugin2"
        mock_record2.enabled = False
        
        manager._plugins = {
            "plugin1": mock_record1,
            "plugin2": mock_record2
        }
        
        enabled = manager.get_enabled_plugins()
        assert isinstance(enabled, list)
        assert len(enabled) == 1
        assert enabled[0].name == "plugin1"
    
    def test_get_status(self):
        """测试获取插件状态"""
        from neurova.plugins.plugin_manager import PluginManager
        
        manager = PluginManager()
        
        # 添加插件记录
        mock_record = MagicMock()
        mock_record.name = "test-plugin"
        mock_record.enabled = True
        mock_record.loaded = True
        mock_record.version = "1.0.0"
        
        manager._plugins = {"test-plugin": mock_record}
        
        status = manager.get_status()
        assert isinstance(status, dict)
        assert "test-plugin" in status


class TestLifecycleEvent:
    """测试 LifecycleEvent 枚举"""
    
    def test_lifecycle_events(self):
        """测试生命周期事件枚举"""
        from neurova.plugins.plugin_lifecycle import LifecycleEvent
        
        assert LifecycleEvent.BEFORE_INSTALL.value == "before_install"
        assert LifecycleEvent.AFTER_INSTALL.value == "after_install"
        assert LifecycleEvent.BEFORE_ENABLE.value == "before_enable"
        assert LifecycleEvent.AFTER_ENABLE.value == "after_enable"
        assert LifecycleEvent.BEFORE_DISABLE.value == "before_disable"
        assert LifecycleEvent.AFTER_DISABLE.value == "after_disable"
        assert LifecycleEvent.BEFORE_UNINSTALL.value == "before_uninstall"
        assert LifecycleEvent.AFTER_UNINSTALL.value == "after_uninstall"


class TestLifecycleHook:
    """测试 LifecycleHook 数据类"""
    
    def test_lifecycle_hook_creation(self):
        """测试 LifecycleHook 创建"""
        from neurova.plugins.plugin_lifecycle import LifecycleHook, LifecycleEvent
        
        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin"
        )
        
        assert hook.event == LifecycleEvent.BEFORE_INSTALL
        assert hook.priority == 10
        assert hook.plugin_name == "test-plugin"
    
    def test_lifecycle_hook_to_dict(self):
        """测试 LifecycleHook 转字典"""
        from neurova.plugins.plugin_lifecycle import LifecycleHook, LifecycleEvent
        
        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin"
        )
        
        data = hook.to_dict()
        assert isinstance(data, dict)
        assert data["event"] == "before_install"
        assert data["priority"] == 10


class TestPluginLifecycleManager:
    """测试 PluginLifecycleManager 类"""
    
    def test_manager_initialization(self):
        """测试 PluginLifecycleManager 初始化"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager
        
        manager = PluginLifecycleManager()
        assert manager is not None
        assert hasattr(manager, 'register_hook')
        assert hasattr(manager, 'execute_lifecycle')
    
    def test_register_hook(self):
        """测试注册钩子"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager, LifecycleEvent, LifecycleHook
        
        manager = PluginLifecycleManager()
        
        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin"
        )
        
        manager.register_hook(hook)
        
        # 检查钩子是否注册
        hooks = manager._collect_hooks(LifecycleEvent.BEFORE_INSTALL, "test-plugin")
        assert len(hooks) == 1
    
    def test_unregister_hooks(self):
        """测试注销钩子"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager, LifecycleEvent, LifecycleHook
        
        manager = PluginLifecycleManager()
        
        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin"
        )
        
        manager.register_hook(hook)
        manager.unregister_hooks("test-plugin")
        
        # 检查钩子是否注销
        hooks = manager._collect_hooks(LifecycleEvent.BEFORE_INSTALL, "test-plugin")
        assert len(hooks) == 0
    
    def test_execute_lifecycle(self):
        """测试执行生命周期"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager, LifecycleEvent, LifecycleHook
        
        manager = PluginLifecycleManager()
        
        # 创建回调函数
        callback_called = False
        
        def test_callback():
            nonlocal callback_called
            callback_called = True
        
        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=test_callback,
            priority=10,
            plugin_name="test-plugin"
        )
        
        manager.register_hook(hook)
        
        # 执行生命周期
        manager.execute_lifecycle(LifecycleEvent.BEFORE_INSTALL, "test-plugin")
        
        assert callback_called is True
    
    def test_set_plugin_state(self):
        """测试设置插件状态"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager
        
        manager = PluginLifecycleManager()
        
        manager.set_plugin_state("test-plugin", "installed")
        
        state = manager.get_plugin_state("test-plugin")
        assert state == "installed"
    
    def test_get_all_states(self):
        """测试获取所有状态"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager
        
        manager = PluginLifecycleManager()
        
        manager.set_plugin_state("plugin1", "installed")
        manager.set_plugin_state("plugin2", "enabled")
        
        states = manager.get_all_states()
        assert isinstance(states, dict)
        assert len(states) == 2
        assert states["plugin1"] == "installed"
        assert states["plugin2"] == "enabled"


class TestGetPluginManager:
    """测试 get_plugin_manager 函数"""
    
    def test_get_plugin_manager(self):
        """测试获取全局插件管理器"""
        from neurova.plugins.plugin_manager import get_plugin_manager, reset_plugin_manager
        
        # 重置管理器
        reset_plugin_manager()
        
        # 获取管理器
        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()
        
        # 应该返回同一个实例
        assert manager1 is manager2
        assert isinstance(manager1, PluginManager)
    
    def test_reset_plugin_manager(self):
        """测试重置全局插件管理器"""
        from neurova.plugins.plugin_manager import get_plugin_manager, reset_plugin_manager
        
        # 获取管理器
        manager1 = get_plugin_manager()
        
        # 重置管理器
        reset_plugin_manager()
        
        # 再次获取管理器
        manager2 = get_plugin_manager()
        
        # 应该是不同的实例
        assert manager1 is not manager2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
