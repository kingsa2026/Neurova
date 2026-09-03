"""工具权重持久化测试（断点 A 收尾：multiplier 跨重启保留）。

现状：AdaptiveToolWeights 是全局单例内存态——重启清零，学习只在会话内
有效。本测试锁定：
- save/load 往返（multiplier/计数一致）
- 损坏/缺失文件：安全回退（warning + 空表），不抛异常、不阻断
- 节流落盘：非零间隔内不重复写；零间隔每次写
- 未挂载持久化时行为零变化（不产生文件、不抛错）
- 单例启动恢复：get_evolution_orchestrator 加载默认路径（environment 可覆盖）
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from neurova.evolution.closed_loop import AdaptiveToolWeights, get_evolution_orchestrator


class TestAdaptiveWeightsPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "weights.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _weights_with_history(self):
        w = AdaptiveToolWeights()
        w.register_tool("tool_a", base_weight=1.0)
        w.update_weight("tool_a", True, 0.5)
        w.update_weight("tool_a", True, 0.6)
        w.update_weight("tool_a", False, 0.9)
        return w

    def test_save_load_roundtrip_preserves_multiplier(self):
        w = self._weights_with_history()
        w.save(self.path)

        restored = AdaptiveToolWeights()
        restored.load(self.path)
        entry = restored.get_weight("tool_a")
        self.assertAlmostEqual(entry.adaptive_multiplier, w.get_weight("tool_a").adaptive_multiplier, places=6)
        self.assertEqual(entry.success_count, 2)
        self.assertEqual(entry.failure_count, 1)

    def test_load_missing_file_is_noop(self):
        w = AdaptiveToolWeights()
        w.load(Path(self.tmp.name) / "nope.json")  # 不抛异常
        self.assertEqual(len(w._weights), 0)

    def test_load_corrupted_file_falls_back_empty(self):
        self.path.write_text("{not json!!", encoding="utf-8")
        w = AdaptiveToolWeights()
        with patch("neurova.evolution.closed_loop.logger") as mock_logger:
            w.load(self.path)
        self.assertEqual(len(w._weights), 0)
        mock_logger.warning.assert_called()

    def test_no_persistence_attached_never_writes(self):
        w = self._weights_with_history()
        w.update_weight("tool_a", True)
        self.assertFalse(self.path.exists())  # 未挂载 → 不落盘

    def test_attached_zero_interval_persists_every_update(self):
        w = AdaptiveToolWeights()
        w.register_tool("tool_a")
        w.attach_persistence(self.path, save_interval=0.0)
        w.update_weight("tool_a", True)
        w.update_weight("tool_a", True)
        self.assertTrue(self.path.exists())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        entry = data["weights"]["tool_a"]
        self.assertEqual(entry["success_count"], 2)
        w.update_weight("tool_a", False)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["weights"]["tool_a"]["failure_count"], 1)

    def test_attached_default_interval_throttles_writes(self):
        """非零间隔（默认 10s）：第二次 update 不落盘（mtime 不变）。"""
        w = AdaptiveToolWeights()
        w.register_tool("tool_a")
        w.attach_persistence(self.path)  # 默认 interval
        w.update_weight("tool_a", True)
        mtime1 = self.path.stat().st_mtime_ns
        w.update_weight("tool_a", True)  # 间隔内：不写
        mtime2 = self.path.stat().st_mtime_ns
        self.assertEqual(mtime1, mtime2)


class TestSingletonRestore(unittest.TestCase):
    """显式装配：bootstrap_evolution_persistence（启动时调用，单例本身零副作用）。"""

    def test_singleton_restores_from_env_path(self):
        from neurova.evolution.closed_loop import (
            bootstrap_evolution_persistence,
            reset_evolution_orchestrator,
        )

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ov.json"
            with patch.dict(os.environ, {"NEUROVA_EVOLUTION_WEIGHTS": str(path)}):
                w = AdaptiveToolWeights()
                w.register_tool("tool_env", base_weight=1.0)
                w.update_weight("tool_env", True)
                w.save(path)

                reset_evolution_orchestrator()
                try:
                    self.assertTrue(bootstrap_evolution_persistence())
                    orchestrator = get_evolution_orchestrator()
                    entry = orchestrator.tool_weights.get_weight("tool_env")
                    self.assertIsNotNone(entry)
                    self.assertGreater(entry.adaptive_multiplier, 1.0)
                finally:
                    reset_evolution_orchestrator()

    def test_bootstrap_without_file_starts_empty_and_is_idempotent(self):
        from neurova.evolution.closed_loop import (
            bootstrap_evolution_persistence,
            reset_evolution_orchestrator,
        )

        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"NEUROVA_EVOLUTION_WEIGHTS": str(Path(d) / "none.json")}):
                reset_evolution_orchestrator()
                try:
                    self.assertFalse(bootstrap_evolution_persistence())
                    self.assertFalse(bootstrap_evolution_persistence())  # 幂等
                    orchestrator = get_evolution_orchestrator()
                    self.assertEqual(len(orchestrator.tool_weights._weights), 0)
                finally:
                    reset_evolution_orchestrator()

    def test_get_singleton_is_zero_side_effect(self):
        """未 bootstrap 时单例不产生任何持久化 IO（测试环境零污染）。"""
        from neurova.evolution.closed_loop import reset_evolution_orchestrator

        reset_evolution_orchestrator()
        try:
            orchestrator = get_evolution_orchestrator()
            self.assertIsNone(orchestrator.tool_weights._persist_path)
            self.assertFalse((Path("data") / "evolution").exists())
        finally:
            reset_evolution_orchestrator()


if __name__ == "__main__":
    unittest.main()
