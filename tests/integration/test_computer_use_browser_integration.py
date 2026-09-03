"""
Computer Use 浏览器集成测试

测试 ComputerUseManager 与 BrowserManager 的端到端集成，
验证 browser-skill 组件的正确整合。
"""
import pytest
import asyncio
import os
import tempfile
import yaml
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# 添加项目根目录到 Python 路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.computer_use import ComputerUseManager, get_computer_use_manager
from neurova.computer_use.browser_manager import BrowserManager, get_browser_manager


class TestComputerUseManagerBrowserIntegration:
    """测试 ComputerUseManager 与 BrowserManager 的集成"""
    
    def test_computer_use_manager_initialization_with_config_path(self):
        """测试 ComputerUseManager 使用配置路径初始化"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "backends": {
                    "playwright": {"headless": True}
                }
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            manager = ComputerUseManager(config_path=config_path)
            assert manager._config_path == config_path
        finally:
            os.unlink(config_path)
    
    def test_computer_use_manager_initialization_without_config_path(self):
        """测试 ComputerUseManager 不使用配置路径初始化"""
        manager = ComputerUseManager()
        assert manager._config_path is None
    
    def test_get_computer_use_manager_with_config_path(self):
        """测试获取全局 ComputerUseManager 实例（带配置路径）"""
        # 重置全局实例
        import neurova.computer_use
        neurova.computer_use._global_computer_use_manager = None
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {"backends": {"playwright": {"headless": True}}}
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            manager = get_computer_use_manager(config_path=config_path)
            assert isinstance(manager, ComputerUseManager)
            assert manager._config_path == config_path
            
            # 再次获取应该返回同一个实例
            manager2 = get_computer_use_manager()
            assert manager is manager2
        finally:
            os.unlink(config_path)
            neurova.computer_use._global_computer_use_manager = None
    
    def test_computer_use_manager_browser_manager_integration(self):
        """测试 ComputerUseManager 与 BrowserManager 的集成"""
        manager = ComputerUseManager()
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.get_status.return_value = {
            "initialized": True,
            "backends_loaded": ["playwright"],
            "components": {
                "dialog_handler": True,
                "supervisor": True,
                "camofox_adapter": False,
                "spider_tool": False,
            }
        }
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            browser = manager._get_browser_manager()
            assert browser is mock_browser_manager
            
            status = manager.get_status()
            assert status["has_browser"] is True
            assert "browser_status" in status
            assert status["browser_status"]["initialized"] is True
    
    def test_computer_use_manager_browser_operations_integration(self):
        """测试 ComputerUseManager 浏览器操作集成"""
        manager = ComputerUseManager()
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.navigate = AsyncMock(return_value={"status": "success", "url": "https://example.com"})
        mock_browser_manager.screenshot = AsyncMock(return_value={"status": "success", "image_base64": "test"})
        mock_browser_manager.snapshot = AsyncMock(return_value={"status": "success", "snapshot": []})
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            # 测试导航
            result = asyncio.run(manager.browser_navigate("test_agent", "https://example.com"))
            assert result["status"] == "success"
            mock_browser_manager.navigate.assert_called_once_with("https://example.com", None)
            
            # 测试截图
            result = asyncio.run(manager.browser_screenshot("test_agent", "https://example.com"))
            assert result["status"] == "success"
            mock_browser_manager.screenshot.assert_called_once_with("https://example.com", None, None)
            
            # 测试快照
            result = asyncio.run(manager.browser_snapshot("test_agent", "https://example.com"))
            assert result["status"] == "success"
            mock_browser_manager.snapshot.assert_called_once_with("https://example.com", None)


class TestBrowserManagerComponentIntegration:
    """测试 BrowserManager 组件集成"""
    
    def test_browser_manager_initializes_all_components(self):
        """测试 BrowserManager 初始化所有组件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "camofox": {"binary_path": "/nonexistent"},
                "spider": {"default_concurrency": 10}
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            manager = BrowserManager(config_path=config_path)
            
            # 检查组件是否初始化
            assert hasattr(manager, '_dialog_handler')
            assert hasattr(manager, '_supervisor')
            assert hasattr(manager, '_camofox_adapter')
            assert hasattr(manager, '_spider_tool')
            
            # 检查组件类型
            from neurova.computer_use.browser_manager import DialogHandler, BrowserSupervisor, CamofoxAdapter, ScraplingSpiderTool
            assert isinstance(manager._dialog_handler, DialogHandler)
            assert isinstance(manager._supervisor, BrowserSupervisor)
            assert isinstance(manager._camofox_adapter, CamofoxAdapter)
            assert isinstance(manager._spider_tool, ScraplingSpiderTool)
            
            # 检查状态
            status = manager.get_status()
            assert "components" in status
            assert status["components"]["dialog_handler"] is True
            assert status["components"]["supervisor"] is True
        finally:
            os.unlink(config_path)
    
    def test_browser_manager_config_loading_integration(self):
        """测试 BrowserManager 配置加载集成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "routing": {
                    "timeout": 60,
                    "rules": [
                        {"pattern": "test\\.com", "backend": "playwright", "reason": "test"}
                    ]
                },
                "backends": {
                    "playwright": {"headless": False},
                    "scrapling-stealthy": {"mode": "stealth", "headless": True}
                }
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            manager = BrowserManager(config_path=config_path)
            
            # 检查配置是否正确加载
            assert manager._config["routing"]["timeout"] == 60
            assert len(manager._config["routing"]["rules"]) == 1
            assert manager._config["routing"]["rules"][0]["pattern"] == "test\\.com"
            
            # 检查后端配置
            assert "playwright" in manager._backend_configs
            assert "scrapling-stealthy" in manager._backend_configs
            assert manager._backend_configs["playwright"]["headless"] is False
            
            # 检查路由解析
            backend = manager._resolve_backend("https://test.com")
            assert backend == "playwright"
        finally:
            os.unlink(config_path)
    
    def test_browser_manager_component_status_integration(self):
        """测试 BrowserManager 组件状态集成"""
        manager = BrowserManager()
        
        # 获取状态
        status = manager.get_status()
        
        # 检查组件状态
        assert "components" in status
        components = status["components"]
        
        assert "dialog_handler" in components
        assert "supervisor" in components
        assert "camofox_adapter" in components
        assert "spider_tool" in components
        
        # 检查依赖状态
        assert "dependencies" in status
        dependencies = status["dependencies"]
        
        assert "playwright" in dependencies
        assert "websockets" in dependencies
        assert "scrapling" in dependencies


class TestComputerUseManagerStatusIntegration:
    """测试 ComputerUseManager 状态集成"""
    
    def test_computer_use_manager_status_includes_browser_components(self):
        """测试 ComputerUseManager 状态包含浏览器组件"""
        manager = ComputerUseManager()
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.get_status.return_value = {
            "initialized": True,
            "components": {
                "dialog_handler": True,
                "supervisor": True,
                "camofox_adapter": False,
                "spider_tool": False,
            }
        }
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            status = manager.get_status()
            
            # 检查浏览器状态
            assert "browser_status" in status
            browser_status = status["browser_status"]
            assert browser_status["initialized"] is True
            assert browser_status["components"]["dialog_handler"] is True
            
            # 检查能力
            capabilities = status["capabilities"]
            assert capabilities["browser_navigate"] is True
            assert capabilities["browser_screenshot"] is True
            assert capabilities["browser_snapshot"] is True
            assert capabilities["browser_scrape"] is True
            assert capabilities["browser_supervisor"] is True
            assert capabilities["browser_dialog_handler"] is True
            assert capabilities["browser_anti_detection"] is True
            assert capabilities["browser_spider"] is True
    
    def test_computer_use_manager_status_without_browser(self):
        """测试 ComputerUseManager 状态（无浏览器）"""
        manager = ComputerUseManager()
        
        with patch('neurova.computer_use.HAS_BROWSER', False):
            status = manager.get_status()
            
            assert status["has_browser"] is False
            assert status["capabilities"]["browser_navigate"] is False
            assert status["capabilities"]["browser_supervisor"] is False


@pytest.mark.asyncio
class TestComputerUseManagerBrowserOperations:
    """测试 ComputerUseManager 浏览器操作"""
    
    async def test_browser_navigate_with_config(self):
        """测试带配置的浏览器导航"""
        manager = ComputerUseManager()
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.navigate = AsyncMock(return_value={
            "status": "success",
            "url": "https://example.com",
            "backend": "playwright"
        })
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            result = await manager.browser_navigate("test_agent", "https://example.com", backend="playwright")
            
            assert result["status"] == "success"
            assert result["url"] == "https://example.com"
            mock_browser_manager.navigate.assert_called_once_with("https://example.com", "playwright")
    
    async def test_browser_screenshot_with_selector(self):
        """测试带选择器的浏览器截图"""
        manager = ComputerUseManager()
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.screenshot = AsyncMock(return_value={
            "status": "success",
            "image_base64": "test_base64",
            "url": "https://example.com"
        })
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            result = await manager.browser_screenshot(
                "test_agent",
                "https://example.com",
                selector="#main",
                backend="playwright"
            )
            
            assert result["status"] == "success"
            assert result["image_base64"] == "test_base64"
            mock_browser_manager.screenshot.assert_called_once_with(
                "https://example.com", "#main", "playwright"
            )
    
    async def test_browser_snapshot_returns_compressed_tree(self):
        """测试浏览器快照返回压缩的 accessibility tree"""
        manager = ComputerUseManager()
        
        # 模拟压缩的快照
        compressed_snapshot = [
            {"role": "button", "name": "Submit", "depth": 0},
            {"role": "textbox", "name": "Username", "depth": 1},
            {"role": "heading", "name": "Login", "depth": 0}
        ]
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.snapshot = AsyncMock(return_value={
            "status": "success",
            "snapshot": compressed_snapshot,
            "backend": "playwright"
        })
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            result = await manager.browser_snapshot("test_agent", "https://example.com")
            
            assert result["status"] == "success"
            assert len(result["snapshot"]) == 3
            assert result["snapshot"][0]["role"] == "button"
            assert result["snapshot"][0]["name"] == "Submit"
    
    async def test_browser_scrape_with_mode(self):
        """测试带模式的浏览器抓取"""
        manager = ComputerUseManager()
        
        # 模拟 BrowserManager
        mock_browser_manager = MagicMock()
        mock_browser_manager.scrape = AsyncMock(return_value={
            "status": "success",
            "url": "https://example.com",
            "backend": "scrapling-stealthy"
        })
        
        with patch('neurova.computer_use.get_browser_manager', return_value=mock_browser_manager):
            result = await manager.browser_scrape("test_agent", "https://example.com", mode="stealth")
            
            assert result["status"] == "success"
            assert result["backend"] == "scrapling-stealthy"
            mock_browser_manager.scrape.assert_called_once_with("https://example.com", "stealth")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])