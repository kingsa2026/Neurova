"""
记忆代理单元测试

测试MemCore的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.mem_core import MemCore


class TestMemCore:
    """MemCore测试"""
    
    def test_import(self):
        """测试模块导入"""
        from neurova.mem_core import MemCore
        assert MemCore is not None
