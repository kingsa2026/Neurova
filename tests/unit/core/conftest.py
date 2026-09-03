
"""
Pytest 配置和共享 fixtures for core module tests
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))


@pytest.fixture
def mock_logger():
    """模拟日志记录器"""
    class MockLogger:
        def __init__(self):
            self.info_messages = []
            self.error_messages = []
            self.debug_messages = []
            self.warning_messages = []

        def info(self, msg):
            self.info_messages.append(msg)

        def error(self, msg):
            self.error_messages.append(msg)

        def debug(self, msg):
            self.debug_messages.append(msg)

        def warning(self, msg):
            self.warning_messages.append(msg)

    return MockLogger()


@pytest.fixture
def mock_event_bus():
    """模拟事件总线"""
    class MockEventBus:
        def __init__(self):
            self.events = []
            self.subscribers = {}

        def subscribe(self, event_type, callback):
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(callback)

        def emit(self, event_type, data=None):
            self.events.append((event_type, data))
            if event_type in self.subscribers:
                for callback in self.subscribers[event_type]:
                    callback(data)

    return MockEventBus()


@pytest.fixture
def temp_config(tmp_path):
    """临时配置目录"""
    return tmp_path / "config"

