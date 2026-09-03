"""
Browser Supervisor 测试

测试 CDP WebSocket 监控功能
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到 Python 路径
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.computer_use.browser_manager import BrowserSupervisor


class TestBrowserSupervisorInit:
    """测试 BrowserSupervisor 初始化"""
    
    def test_supervisor_initialization(self):
        """测试 BrowserSupervisor 初始化"""
        supervisor = BrowserSupervisor()
        
        # 应该有基本的属性
        assert supervisor is not None
        assert hasattr(supervisor, 'dialog_handler')
        assert hasattr(supervisor, 'event_queue')
        assert hasattr(supervisor, 'page_snapshots')
    
    def test_supervisor_dialog_handler(self):
        """测试 BrowserSupervisor 对话框处理器"""
        supervisor = BrowserSupervisor()
        
        # 应该有对话框处理器
        assert supervisor.dialog_handler is not None
        assert hasattr(supervisor.dialog_handler, 'handle_dialog')


class TestBrowserSupervisorDialogHandling:
    """测试 BrowserSupervisor 对话框处理"""
    
    def test_handle_alert_dialog(self):
        """测试处理 alert 对话框"""
        supervisor = BrowserSupervisor()
        
        # 模拟对话框处理
        action = supervisor.dialog_handler.handle_dialog("alert", "Test message")
        
        # 应该返回 accept
        assert action == "accept"
    
    def test_handle_confirm_dialog(self):
        """测试处理 confirm 对话框"""
        supervisor = BrowserSupervisor()
        
        # 模拟对话框处理
        action = supervisor.dialog_handler.handle_dialog("confirm", "Are you sure?")
        
        # 应该返回 accept
        assert action == "accept"
    
    def test_handle_prompt_dialog(self):
        """测试处理 prompt 对话框"""
        supervisor = BrowserSupervisor()
        
        # 模拟对话框处理
        action = supervisor.dialog_handler.handle_dialog("prompt", "Enter your name")
        
        # 应该返回空字符串
        assert action == ""


class TestBrowserSupervisorSnapshotCompression:
    """测试 BrowserSupervisor 快照压缩"""
    
    def test_compress_snapshot_with_interactive_roles(self):
        """测试压缩包含交互角色的快照"""
        supervisor = BrowserSupervisor()
        
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
        
        compressed = supervisor._compress_snapshot(raw_snapshot)
        
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