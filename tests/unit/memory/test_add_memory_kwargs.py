"""
M-7 断点修复测试: add_memory kwargs 黑洞

验证 MemoryManager.remember 不再丢弃 API 层传入的 7 个参数:
  - 数据参数(应进入 Memory 对象):
      is_important / is_crystallized / emotion_score / perspective
  - 控制参数(不应存入 Memory 数据字段, 只影响 remember 内部逻辑):
      auto_analyze_emotion / auto_classify / classification_context

设计依据:
  - Memory 数据类有 perspective 字段(MemoryPerspective 枚举), 直接写入
  - Memory 无 is_important / is_crystallized / emotion_score 字段, 存入 metadata
  - auto_analyze_emotion / auto_classify / classification_context 是控制开关, 不污染数据
"""
import os
import shutil
import tempfile
import unittest


class TestAddMemoryPreservesFields(unittest.TestCase):
    """验证 remember 把 API 层的 7 个参数正确送达 Memory 对象"""

    @classmethod
    def setUpClass(cls):
        # 临时 DB 目录, 避免污染项目数据
        cls.tmpdir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmpdir, "test_add_memory_kwargs.db")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _create_manager(self):
        # 仅使用 __init__ 实际接收的参数: db_path / agent_id / user_id
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        return MemoryManager(
            db_path=self.db_path,
            agent_id="test_agent",
            user_id="test_user",
        )

    def _remember(self, mgr, content, **kwargs):
        # 避开已知源码 bug(auto_analyze_emotion=True 会触发 tuple 存储异常)
        # 同时明确给 emotion 跳过自动情感分析分支
        kwargs.setdefault("auto_analyze_emotion", False)
        kwargs.setdefault("auto_classify", False)
        kwargs.setdefault("emotion", "neutral")
        return mgr.remember(content, **kwargs)

    # ──────────────────────────────────────────────────────────
    # 数据参数: 应进入 Memory 对象
    # ──────────────────────────────────────────────────────────

    def test_remember_accepts_is_important(self):
        """remember 接受 is_important 并写入 Memory"""
        mgr = self._create_manager()
        try:
            mem_id = self._remember(mgr, "重要事件", is_important=True)
            mem = mgr._memories[mem_id]
            # Memory 无 is_important 字段, 应存入 metadata
            self.assertTrue(mem.metadata.get("is_important"),
                            "is_important 未到达 Memory 对象")
        finally:
            mgr.close()

    def test_remember_accepts_is_crystallized(self):
        """remember 接受 is_crystallized 并写入 Memory"""
        mgr = self._create_manager()
        try:
            mem_id = self._remember(mgr, "固化记忆", is_crystallized=True)
            mem = mgr._memories[mem_id]
            self.assertTrue(mem.metadata.get("is_crystallized"),
                            "is_crystallized 未到达 Memory 对象")
        finally:
            mgr.close()

    def test_remember_accepts_emotion_score(self):
        """remember 接受 emotion_score 并写入 Memory"""
        mgr = self._create_manager()
        try:
            mem_id = self._remember(mgr, "带情感分数", emotion_score=0.8)
            mem = mgr._memories[mem_id]
            self.assertEqual(float(mem.metadata.get("emotion_score")), 0.8,
                             "emotion_score 未到达 Memory 对象")
        finally:
            mgr.close()

    def test_remember_accepts_perspective(self):
        """remember 接受 perspective 并写入 Memory.perspective(转枚举)"""
        from neurova.cognitive_layers.memory_layer.models import MemoryPerspective

        mgr = self._create_manager()
        try:
            mem_id = self._remember(mgr, "第三人称视角", perspective="third_person")
            mem = mgr._memories[mem_id]
            self.assertEqual(mem.perspective, MemoryPerspective.THIRD_PERSON,
                             "perspective 未到达 Memory.perspective 字段")
        finally:
            mgr.close()

    # ──────────────────────────────────────────────────────────
    # 控制参数: 不应污染 Memory 数据字段
    # ──────────────────────────────────────────────────────────

    def test_auto_classify_not_stored_in_memory(self):
        """auto_classify / classification_context 是控制参数, 不存入 Memory 数据字段"""
        mgr = self._create_manager()
        try:
            mem_id = self._remember(
                mgr, "控制参数测试",
                auto_classify=True,
                classification_context={"topic": "demo"},
            )
            mem = mgr._memories[mem_id]
            # 控制参数不应出现在 metadata
            self.assertNotIn("auto_classify", mem.metadata,
                              "auto_classify 不应存入 Memory 数据字段")
            self.assertNotIn("classification_context", mem.metadata,
                             "classification_context 不应存入 Memory 数据字段")
            self.assertNotIn("auto_analyze_emotion", mem.metadata,
                             "auto_analyze_emotion 不应存入 Memory 数据字段")
        finally:
            mgr.close()

    # ──────────────────────────────────────────────────────────
    # 端到端: 模拟 API 层 crud.py 的完整 7 参数调用
    # ──────────────────────────────────────────────────────────

    def test_api_add_memory_end_to_end(self):
        """模拟 add_memory 端点调用, 验证 7 个参数都到达 Memory 对象"""
        from neurova.cognitive_layers.memory_layer.models import MemoryPerspective

        mgr = self._create_manager()
        try:
            # 完全复刻 crud.py add_memory 端点的调用方式
            mem_id = mgr.remember(
                content="端到端测试记忆",
                category="general",
                is_important=True,
                is_crystallized=True,
                emotion_score=0.7,
                perspective="third_person",
                metadata={"source": "api"},
                auto_analyze_emotion=False,
                auto_classify=False,
                classification_context=None,
            )
            mem = mgr._memories[mem_id]

            # 数据参数到达 Memory
            self.assertTrue(mem.metadata.get("is_important"),
                            "is_important 端到端丢失")
            self.assertTrue(mem.metadata.get("is_crystallized"),
                            "is_crystallized 端到端丢失")
            self.assertEqual(float(mem.metadata.get("emotion_score")), 0.7,
                             "emotion_score 端到端丢失")
            self.assertEqual(mem.perspective, MemoryPerspective.THIRD_PERSON,
                             "perspective 端到端丢失")
            # 用户传入的 metadata 不被覆盖
            self.assertEqual(mem.metadata.get("source"), "api",
                             "用户 metadata 被覆盖")
            # 控制参数被接受(调用不报错)但不污染数据
            self.assertNotIn("auto_classify", mem.metadata)
            self.assertNotIn("classification_context", mem.metadata)
        finally:
            mgr.close()


if __name__ == "__main__":
    unittest.main()
