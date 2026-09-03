"""
集成测试配置
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock


@pytest.fixture
def temp_storage():
    """提供临时存储目录"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_event_bus():
    """模拟事件总线"""
    bus = Mock()
    bus.subscribe = Mock()
    bus.publish = Mock()
    bus.unsubscribe = Mock()
    return bus


@pytest.fixture
def sample_project_data():
    """示例项目数据"""
    return {
        "name": "Test Project",
        "description": "A test project for integration",
        "owner_id": "user_123",
        "config": {"setting": "test"}
    }
