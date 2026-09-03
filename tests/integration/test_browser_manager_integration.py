"""
Browser Manager 集成测试

测试 browser-skill 整合到 computer_use 能力后的新功能
"""
import pytest
import asyncio
import os
import tempfile
import yaml
from pathlib import Path

# 添加项目根目录到 Python 路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.computer_use.browser_manager import BrowserManager, get_browser_manager


class TestBrowserManagerConfig:
    """测试 BrowserManager 配置加载"""
    
    def test_load_config_from_yaml(self, tmp_path):
        """测试从 YAML 文件加载配置"""
        # 准备配置文件
        config_content = {
            "routing": {
                "timeout": 30,
                "rules": [
                    {
                        "pattern": "localhost|127\\.0\\.0\\.1",
                        "backend": "agent-browser",
                        "reason": "loopback address"
                    }
                ]
            },
            "backends": {
                "playwright": {
                    "type": "local",
                    "headless": True
                },
                "scrapling-stealthy": {
                    "type": "local",
                    "mode": "stealth",
                    "adaptive": True
                }
            }
        }
        
        config_file = tmp_path / "backends.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)
        
        # 测试加载配置
        manager = BrowserManager(config_path=str(config_file))
        
        # 验证配置加载成功
        assert manager._config is not None
        assert "routing" in manager._config
        assert "backends" in manager._config
        assert len(manager._config["routing"]["rules"]) == 1
    
    def test_default_config_if_no_file(self):
        """测试如果没有配置文件，使用默认配置"""
        manager = BrowserManager()
        
        # 应该有默认配置
        assert manager._config is not None
        assert "backends" in manager._config
        assert "playwright" in manager._config["backends"]


class TestBrowserManagerRouting:
    """测试 BrowserManager 路由功能"""
    
    def test_resolve_backend_with_config_rules(self, tmp_path):
        """测试根据配置规则解析后端"""
        config_content = {
            "routing": {
                "rules": [
                    {
                        "pattern": "localhost|127\\.0\\.0\\.1",
                        "backend": "agent-browser",
                        "reason": "loopback"
                    },
                    {
                        "pattern": ".*\\.cloudflare\\.com",
                        "backend": "scrapling-stealthy",
                        "reason": "Cloudflare"
                    }
                ]
            },
            "backends": {
                "agent-browser": {"type": "local"},
                "scrapling-stealthy": {"type": "local"}
            }
        }
        
        config_file = tmp_path / "backends.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)
        
        manager = BrowserManager(config_path=str(config_file))
        
        # 测试路由规则
        assert manager._resolve_backend("http://localhost:3000") == "agent-browser"
        assert manager._resolve_backend("https://example.cloudflare.com") == "scrapling-stealthy"
        assert manager._resolve_backend("https://example.com") == "playwright"  # 默认


class TestBrowserManagerBackends:
    """测试 BrowserManager 后端支持"""
    
    def test_available_backends_from_config(self, tmp_path):
        """测试从配置中获取可用后端"""
        config_content = {
            "backends": {
                "playwright": {"type": "local"},
                "scrapling-stealthy": {"type": "local"},
                "browserbase": {"type": "cloud"}
            }
        }
        
        config_file = tmp_path / "backends.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)
        
        manager = BrowserManager(config_path=str(config_file))
        
        # 验证后端配置
        assert "playwright" in manager._backend_configs
        assert "scrapling-stealthy" in manager._backend_configs
        assert "browserbase" in manager._backend_configs


class TestBrowserManagerDialogHandling:
    """测试对话框自动处理"""
    
    def test_dialog_handler_initialization(self):
        """测试对话框处理器初始化"""
        manager = BrowserManager()
        
        # 应该有对话框处理器
        assert hasattr(manager, '_dialog_handler')
        assert manager._dialog_handler is not None


class TestBrowserManagerSnapshotCompression:
    """测试快照压缩功能"""
    
    def test_compress_snapshot_with_interactive_roles(self):
        """测试压缩包含交互角色的快照"""
        manager = BrowserManager()
        
        # 模拟原始快照
        raw_snapshot = {
            "role": "WebArea",
            "name": "Test Page",
            "children": [
                {"role": "heading", "name": "Welcome", "children": []},
                {"role": "button", "name": "Click Me", "children": []},
                {"role": "link", "name": "Learn More", "children": []},
                {"role": "textbox", "name": "Search", "children": []},
                {"role": "generic", "name": "Some div", "children": []},  # 应该被过滤
            ]
        }
        
        compressed = manager._compress_snapshot(raw_snapshot)
        
        # 应该只保留交互和语义角色
        roles = [node["role"] for node in compressed]
        assert "button" in roles
        assert "link" in roles
        assert "textbox" in roles
        assert "heading" in roles
        assert "generic" not in roles


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])