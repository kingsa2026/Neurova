"""
上下文模块单元测试

测试ContextOrchestrator的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.context import ContextOrchestrator


class TestContextOrchestrator:
    """ContextOrchestrator测试"""
    
    def test_import(self):
        """测试模块导入"""
        from neurova.context import ContextOrchestrator
        assert ContextOrchestrator is not None
