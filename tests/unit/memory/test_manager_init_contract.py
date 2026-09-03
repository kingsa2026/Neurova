"""
MemoryManager.__init__ 契约测试 (TDD RED 阶段)

验证 L-1 修复后的构造契约：
- __init__ 接受 neuser_id 与 enable_buffer 关键字参数
- 暴露 neuser_id / agent_id / user_id 三个只读 property
- enable_buffer=False 时跳过 ConversationBuffer 初始化
- enable_buffer=True (默认) 时初始化 ConversationBuffer
- 向后兼容：不传 neuser_id / enable_buffer 时使用合理默认值
"""
import os
import shutil
import tempfile
import unittest


class TestMemoryManagerInitContract(unittest.TestCase):
    """验证 MemoryManager.__init__ 的契约签名与默认行为。"""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmpdir, "test_init_contract.db")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make(self, **kwargs):
        """构造 MemoryManager 实例的辅助方法。"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        kwargs.setdefault("db_path", self.db_path)
        return MemoryManager(**kwargs)

    # ── 契约 1: 接受 neuser_id 与 enable_buffer 关键字参数 ──

    def test_init_accepts_neuser_id_keyword(self):
        """__init__ 接受 neuser_id 关键字参数,不再抛出 TypeError。"""
        mgr = self._make(agent_id="a1", neuser_id="nu1", user_id="u1", enable_buffer=False)
        self.assertIsNotNone(mgr)
        mgr.close()

    def test_init_accepts_enable_buffer_keyword(self):
        """__init__ 接受 enable_buffer 关键字参数,不再抛出 TypeError。"""
        mgr = self._make(agent_id="a2", neuser_id="nu2", user_id="u2", enable_buffer=True)
        self.assertIsNotNone(mgr)
        mgr.close()

    # ── 契约 2: 暴露 neuser_id / agent_id / user_id 属性 ──

    def test_neuser_id_property_returns_value(self):
        """neuser_id property 返回构造时传入的值。"""
        mgr = self._make(agent_id="a", neuser_id="test_neuser", user_id="u", enable_buffer=False)
        self.assertEqual(mgr.neuser_id, "test_neuser")
        mgr.close()

    def test_agent_id_property_returns_value(self):
        """agent_id property 返回构造时传入的值。"""
        mgr = self._make(agent_id="my_agent", neuser_id="nu", user_id="u", enable_buffer=False)
        self.assertEqual(mgr.agent_id, "my_agent")
        mgr.close()

    def test_user_id_property_returns_value(self):
        """user_id property 返回构造时传入的值。"""
        mgr = self._make(agent_id="a", neuser_id="nu", user_id="my_user", enable_buffer=False)
        self.assertEqual(mgr.user_id, "my_user")
        mgr.close()

    # ── 契约 3: enable_buffer=False 时不初始化 ConversationBuffer ──

    def test_enable_buffer_false_keeps_buffer_none(self):
        """enable_buffer=False 时 _conversation_buffer 保持为 None。"""
        mgr = self._make(agent_id="a", neuser_id="nu", user_id="u", enable_buffer=False)
        self.assertIsNone(mgr._conversation_buffer)
        mgr.close()

    # ── 契约 4: enable_buffer=True (默认) 时初始化 ConversationBuffer ──

    def test_enable_buffer_true_initializes_buffer(self):
        """enable_buffer=True 时 _conversation_buffer 应为 ConversationBuffer 实例。"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer

        mgr = self._make(agent_id="a", neuser_id="nu", user_id="u", enable_buffer=True)
        self.assertIsInstance(mgr._conversation_buffer, ConversationBuffer)
        mgr.close()

    # ── 契约 5: 向后兼容,不传新参数时使用合理默认值 ──

    def test_default_neuser_id_is_default_string(self):
        """不传 neuser_id 时默认值为 "default"。"""
        mgr = self._make(agent_id="a", user_id="u", enable_buffer=False)
        self.assertEqual(mgr.neuser_id, "default")
        mgr.close()

    def test_default_enable_buffer_is_true(self):
        """不传 enable_buffer 时默认值为 True (向后兼容生产环境行为)。"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer

        mgr = self._make(agent_id="a", neuser_id="nu", user_id="u")
        self.assertIsInstance(mgr._conversation_buffer, ConversationBuffer)
        mgr.close()

    def test_minimal_args_only_db_path(self):
        """仅传 db_path 时也应能正常构造 (向后兼容)。"""
        mgr = self._make()
        self.assertEqual(mgr.agent_id, "default")
        self.assertEqual(mgr.neuser_id, "default")
        self.assertEqual(mgr.user_id, "default")
        mgr.close()


if __name__ == "__main__":
    unittest.main()
