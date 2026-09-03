"""时间感知闭环测试（P1-F）

覆盖 time_awareness.py 的 TimeAwareness 从零调用到真实闭环:
- 新增轻量 get_time_context_hint（纯日期计算，不读记忆，可每轮调用）
- injector 的 `## 当前时间` 块在提示非空时追加（不增加消息条数，保持上下文长度契约）
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from neurova.context.injector import UnifiedContextInjector


class TimeContextHintTest(unittest.TestCase):
    def setUp(self):
        from neurova.cognitive_layers.emotion_context_layer.time_awareness import (
            reset_time_awareness,
        )

        reset_time_awareness()

    def tearDown(self):
        from neurova.cognitive_layers.emotion_context_layer.time_awareness import (
            reset_time_awareness,
        )

        reset_time_awareness()

    def test_hint_contains_season_without_memory(self):
        """无记忆依赖的轻量提示：季节信息总是可用"""
        from neurova.cognitive_layers.emotion_context_layer.time_awareness import (
            get_time_awareness,
        )

        hint = get_time_awareness().get_time_context_hint()
        self.assertTrue(hint, "季节提示应始终可生成（纯日期计算）")
        self.assertIn("季节", hint)

    def test_injector_time_block_appends_hint(self):
        """时间块内容被追加提示（不新增消息条数，保持上下文长度契约）"""
        tmpdir = tempfile.mkdtemp()
        try:
            from neurova.cognitive_layers.memory_layer.manager import MemoryManager

            mm = MemoryManager(
                db_path=os.path.join(tmpdir, "time_hint.db"),
                agent_id="test_agent",
                user_id="test_user",
            )
            injector = UnifiedContextInjector(memory_manager=mm)

            prompt = injector._build_system_prompt(base_prompt="你是测试助手")
            self.assertIn("当前时间", prompt)
            self.assertIn("季节", prompt, "时间块应追加时间感知提示")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_injector_time_block_without_hint_keeps_shape(self):
        """提示为空时时间块保持原样（容错路径）"""
        tmpdir = tempfile.mkdtemp()
        try:
            from neurova.cognitive_layers.memory_layer.manager import MemoryManager

            mm = MemoryManager(
                db_path=os.path.join(tmpdir, "time_hint2.db"),
                agent_id="test_agent",
                user_id="test_user",
            )
            injector = UnifiedContextInjector(memory_manager=mm)

            from neurova.cognitive_layers.emotion_context_layer import time_awareness as ta_module

            class _FakeAwareness:
                def get_time_context_hint(self, prediction_days=3):
                    return ""

            with patch.object(ta_module, "get_time_awareness", return_value=_FakeAwareness()):
                prompt = injector._build_system_prompt(base_prompt="你是测试助手")
            self.assertIn("当前时间", prompt)
            self.assertNotIn("季节", prompt)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
