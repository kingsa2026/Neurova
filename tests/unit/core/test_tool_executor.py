"""
工具执行器单元测试

测试ToolExecutor的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.tool_executor import ToolExecutor


class TestToolExecutor:
    """ToolExecutor测试"""
    
    def test_init(self):
        """测试初始化"""
        executor = ToolExecutor(agent_ref=Mock())
        assert executor is not None
    
    def test_import(self):
        """测试模块导入"""
        from neurova.tool_executor import ToolExecutor
        assert ToolExecutor is not None
