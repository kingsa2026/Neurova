"""
AgentMemoryLayer 单元测试
"""

import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

try:
    from neurova.cognitive_layers.memory_layer.memory_layer import AgentMemoryLayer
    HAS_MEMORY_LAYER = True
except ImportError:
    HAS_MEMORY_LAYER = False


@unittest.skipIf(not HAS_MEMORY_LAYER, "AgentMemoryLayer not available")
class TestAgentMemoryLayer(unittest.TestCase):
    """AgentMemoryLayer 测试类"""

    def setUp(self) -> None:
        """测试前初始化"""

    def tearDown(self) -> None:
        """测试后清理"""

    def test_init(self) -> None:
        """测试初始化"""
        memory = AgentMemoryLayer(
            agent_id="test_agent",
            db_path="/tmp/test_memory.db",
        )
        self.assertEqual(memory.agent_id, "test_agent")
        self.assertEqual(memory.db_path, "/tmp/test_memory.db")

    def test_init_requires_agent_id(self) -> None:
        """测试初始化需要agent_id"""
        with self.assertRaises(TypeError):
            AgentMemoryLayer()

    def test_properties(self) -> None:
        """测试属性访问"""
        memory = AgentMemoryLayer(
            agent_id="test_agent",
            db_path="/tmp/test_memory.db",
            neuser_id="user1",
            user_id="user2",
        )
        self.assertEqual(memory.agent_id, "test_agent")
        self.assertEqual(memory.db_path, "/tmp/test_memory.db")
        self.assertEqual(memory.neuser_id, "user1")
        self.assertEqual(memory.user_id, "user2")

    def test_repr(self) -> None:
        """测试字符串表示"""
        memory = AgentMemoryLayer(
            agent_id="test_agent",
            db_path="/tmp/test_memory.db",
        )
        repr_str = repr(memory)
        self.assertIn("test_agent", repr_str)

    def test_import(self) -> None:
        """测试模块导入"""
        from neurova.cognitive_layers.memory_layer.memory_layer import AgentMemoryLayer
        self.assertIsNotNone(AgentMemoryLayer)
