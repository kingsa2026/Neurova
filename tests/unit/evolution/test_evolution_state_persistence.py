"""进化状态落盘测试（P-2 收尾：三个纯内存进化状态跨重启保留）。

现状：PatternMiner 序列缓冲 / ToolLifecycleManager 四态 / ExperienceFeedback
成败计数均为纯内存——重启清零，长期进化依赖单进程不存活。本测试锁定：
- 各组件 save/load 往返（序列+上下文 / 四态+计数 / 任务-工具计数）
- 损坏/缺失文件：安全回退（warning + 空态），不抛异常、不阻断
- 未挂载持久化时行为零变化（不产生文件、不抛错）
- 节流落盘：非零间隔内不重复写；零间隔每次写
- bootstrap_evolution_persistence 同批装配四件（幂等；单例本身零副作用）
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.pattern_miner import PatternMiner
from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState


class _PersistenceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()


class TestPatternMinerPersistence(_PersistenceTestBase):
    def _miner_with_sequences(self):
        miner = PatternMiner()
        miner.add_sequence(["a", "b"], context="t1")
        miner.add_sequence(["a", "b"], context="t2")
        miner.add_sequence(["a", "c"], context="t3")
        return miner

    def test_save_load_roundtrip_preserves_sequences(self):
        miner = self._miner_with_sequences()
        miner.save(self.path)

        restored = PatternMiner()
        restored.load(self.path)
        self.assertEqual(restored.sequence_count, 3)
        self.assertEqual(restored._contexts, ["t1", "t2", "t3"])
        self.assertEqual(restored.unique_tools_count, 3)
        # 派生态可重挖：a→b 支持度 2
        patterns = {tuple(p.tools): p.support for p in restored.mine()}
        self.assertEqual(patterns.get(("a", "b")), 2)

    def test_load_missing_file_is_noop(self):
        miner = PatternMiner()
        miner.load(Path(self.tmp.name) / "nope.json")  # 不抛异常
        self.assertEqual(miner.sequence_count, 0)

    def test_load_corrupted_file_falls_back_empty(self):
        self.path.write_text("{not json!!", encoding="utf-8")
        miner = PatternMiner()
        miner.load(self.path)
        self.assertEqual(miner.sequence_count, 0)

    def test_load_short_contexts_pads_empty(self):
        self.path.write_text(
            json.dumps({"version": 1, "sequences": [["a", "b"], ["a", "c"]], "contexts": ["t1"]}),
            encoding="utf-8",
        )
        miner = PatternMiner()
        miner.load(self.path)
        self.assertEqual(miner._contexts, ["t1", ""])

    def test_no_persistence_attached_never_writes(self):
        miner = self._miner_with_sequences()
        self.assertFalse(self.path.exists())  # 未挂载 → 不落盘

    def test_attached_zero_interval_persists_every_add(self):
        miner = PatternMiner()
        miner.attach_persistence(self.path, save_interval=0.0)
        miner.add_sequence(["a", "b"])
        self.assertTrue(self.path.exists())
        miner.add_sequence(["b", "c"])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["sequences"]), 2)

    def test_attached_default_interval_throttles_writes(self):
        miner = PatternMiner()
        miner.attach_persistence(self.path)  # 默认间隔
        miner.add_sequence(["a", "b"])
        mtime1 = self.path.stat().st_mtime_ns
        miner.add_sequence(["b", "c"])  # 间隔内：不写
        self.assertEqual(mtime1, self.path.stat().st_mtime_ns)

    def test_reset_persists_cleared_state(self):
        miner = PatternMiner()
        miner.attach_persistence(self.path, save_interval=0.0)
        miner.add_sequence(["a", "b"])
        miner.reset()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["sequences"], [])


class TestToolLifecyclePersistence(_PersistenceTestBase):
    def test_save_load_roundtrip_preserves_states_and_counters(self):
        lcm = ToolLifecycleManager()
        lcm.register_tool("tool_x")
        lcm.touch("tool_x", success=True)
        lcm.touch("tool_x", success=False)
        lcm._advance_time(8 * 24 * 3600)  # 超过 7 天不活跃
        lcm.evaluate()  # → DEGRADED
        lcm.save(self.path)

        restored = ToolLifecycleManager()
        restored.load(self.path)
        self.assertEqual(restored.get_state("tool_x"), ToolLifecycleState.DEGRADED)
        self.assertEqual(restored.get_usage_count("tool_x"), 2)
        entry = restored.evaluate("tool_x")
        self.assertEqual(entry["success_calls"], 1)
        self.assertEqual(entry["failure_calls"], 1)

    def test_load_missing_file_is_noop(self):
        lcm = ToolLifecycleManager()
        lcm.load(Path(self.tmp.name) / "nope.json")  # 不抛异常
        self.assertEqual(lcm.get_lifecycle_report()["total"], 0)

    def test_load_corrupted_file_falls_back_empty(self):
        self.path.write_text("[[[", encoding="utf-8")
        lcm = ToolLifecycleManager()
        lcm.load(self.path)
        self.assertEqual(lcm.get_lifecycle_report()["total"], 0)

    def test_load_unknown_state_falls_back_active(self):
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tools": {
                        "tool_bad": {"state": "bogus", "total_calls": 5},
                    },
                }
            ),
            encoding="utf-8",
        )
        lcm = ToolLifecycleManager()
        lcm.load(self.path)
        self.assertEqual(lcm.get_state("tool_bad"), ToolLifecycleState.ACTIVE)
        self.assertEqual(lcm.get_usage_count("tool_bad"), 5)

    def test_no_persistence_attached_never_writes(self):
        lcm = ToolLifecycleManager()
        lcm.register_tool("tool_x")
        lcm.touch("tool_x", success=True)
        self.assertFalse(self.path.exists())

    def test_touch_persists_with_zero_interval(self):
        lcm = ToolLifecycleManager()
        lcm.attach_persistence(self.path, save_interval=0.0)
        lcm.touch("tool_x", success=True)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["tools"]["tool_x"]["total_calls"], 1)

    def test_touch_throttled_with_default_interval(self):
        lcm = ToolLifecycleManager()
        lcm.attach_persistence(self.path)
        lcm.touch("tool_x", success=True)
        mtime1 = self.path.stat().st_mtime_ns
        lcm.touch("tool_x", success=True)  # 间隔内：不写
        self.assertEqual(mtime1, self.path.stat().st_mtime_ns)


class TestExperienceFeedbackPersistence(_PersistenceTestBase):
    def _feedback_with_history(self):
        fb = ExperienceFeedback()
        fb.process_experience("使用 web_search 搜索成功完成", task_type="research")
        fb.process_experience("web_search 再次成功", task_type="research")
        fb.process_experience("web_search 完成了", task_type="research")
        return fb

    def test_save_load_roundtrip_preserves_counters(self):
        fb = self._feedback_with_history()
        fb.save(self.path)

        restored = ExperienceFeedback()
        restored.load(self.path)
        patterns = restored.get_task_tool_patterns("research")
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["tool_name"], "web_search")
        self.assertEqual(patterns[0]["success_count"], 3)
        self.assertEqual(patterns[0]["total_count"], 3)
        # RSI 反馈信号跨重启一致：观察≥3 且成功率>0.6 → 已结晶
        self.assertEqual(restored.get_feedback()["crystallized_patterns"], 1)

    def test_load_missing_file_is_noop(self):
        fb = ExperienceFeedback()
        fb.load(Path(self.tmp.name) / "nope.json")  # 不抛异常
        self.assertEqual(fb.get_feedback()["total_experiences"], 0)

    def test_load_corrupted_file_falls_back_empty(self):
        self.path.write_text("nope{", encoding="utf-8")
        fb = ExperienceFeedback()
        fb.load(self.path)
        self.assertEqual(fb._associations, {})

    def test_no_persistence_attached_never_writes(self):
        fb = self._feedback_with_history()
        self.assertFalse(self.path.exists())

    def test_process_persists_with_zero_interval(self):
        fb = ExperienceFeedback()
        fb.attach_persistence(self.path, save_interval=0.0)
        fb.process_experience("web_search 成功", task_type="research")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            data["associations"]["research"]["web_search"]["total_count"], 1
        )

    def test_process_throttled_with_default_interval(self):
        fb = ExperienceFeedback()
        fb.attach_persistence(self.path)
        fb.process_experience("web_search 成功", task_type="research")
        mtime1 = self.path.stat().st_mtime_ns
        fb.process_experience("web_search 再次成功", task_type="research")
        self.assertEqual(mtime1, self.path.stat().st_mtime_ns)


class TestBootstrapWiring(_PersistenceTestBase):
    """bootstrap_evolution_persistence 同批装配四件持久化。"""

    def setUp(self):
        super().setUp()
        self.weights_path = Path(self.tmp.name) / "weights.json"
        self.patterns_path = Path(self.tmp.name) / "patterns.json"
        self.lifecycle_path = Path(self.tmp.name) / "lifecycle.json"
        self.experience_path = Path(self.tmp.name) / "experience.json"
        self.env = {
            "NEUROVA_EVOLUTION_WEIGHTS": str(self.weights_path),
            "NEUROVA_EVOLUTION_PATTERNS": str(self.patterns_path),
            "NEUROVA_EVOLUTION_LIFECYCLE": str(self.lifecycle_path),
            "NEUROVA_EVOLUTION_EXPERIENCE": str(self.experience_path),
        }

    def _seed_state_files(self):
        self.patterns_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sequences": [["a", "b"], ["a", "b"], ["a", "c"]],
                    "contexts": ["t1", "t2", "t3"],
                }
            ),
            encoding="utf-8",
        )
        self.lifecycle_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tools": {
                        "tool_boot": {
                            "state": "degraded",
                            "total_calls": 4,
                            "success_calls": 3,
                            "failure_calls": 1,
                            "last_used": 1000.0,
                            "created_at": 900.0,
                            "state_changed_at": 1000.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.experience_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "associations": {
                        "research": {
                            "web_search": {
                                "success_count": 3,
                                "failure_count": 0,
                                "total_count": 3,
                                "avg_confidence": 0.8,
                                "last_used": 1000.0,
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_bootstrap_restores_all_four_components(self):
        from neurova.evolution.closed_loop import (
            bootstrap_evolution_persistence,
            reset_evolution_orchestrator,
        )

        self._seed_state_files()
        with patch.dict(os.environ, self.env):
            from neurova.evolution import closed_loop

            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                orchestrator = closed_loop.get_evolution_orchestrator()
                self.assertEqual(orchestrator.pattern_miner.sequence_count, 3)
                self.assertEqual(
                    orchestrator.tool_lifecycle.get_state("tool_boot"),
                    ToolLifecycleState.DEGRADED,
                )
                self.assertEqual(
                    orchestrator.experience_feedback.get_task_tool_patterns("research")[0][
                        "success_count"
                    ],
                    3,
                )
            finally:
                closed_loop.reset_evolution_orchestrator()

    def test_bootstrap_is_idempotent(self):
        from neurova.evolution import closed_loop

        with patch.dict(os.environ, self.env):
            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                closed_loop.bootstrap_evolution_persistence()  # 二次挂载 no-op
                orchestrator = closed_loop.get_evolution_orchestrator()
                self.assertEqual(
                    orchestrator.pattern_miner._persist_path, self.patterns_path
                )
                self.assertEqual(
                    orchestrator.tool_lifecycle._persist_path, self.lifecycle_path
                )
                self.assertEqual(
                    orchestrator.experience_feedback._persist_path, self.experience_path
                )
            finally:
                closed_loop.reset_evolution_orchestrator()

    def test_get_singleton_is_zero_side_effect(self):
        """未 bootstrap 时单例不挂载任何持久化（测试环境零污染）。"""
        from neurova.evolution import closed_loop

        closed_loop.reset_evolution_orchestrator()
        try:
            orchestrator = closed_loop.get_evolution_orchestrator()
            self.assertIsNone(orchestrator.pattern_miner._persist_path)
            self.assertIsNone(orchestrator.tool_lifecycle._persist_path)
            self.assertIsNone(orchestrator.experience_feedback._persist_path)
        finally:
            closed_loop.reset_evolution_orchestrator()

    def test_flush_bypasses_throttle_on_shutdown(self):
        """关停 flush 绕过节流：节流窗口内未落盘的最后变更不丢失。"""
        from neurova.evolution import closed_loop

        with patch.dict(os.environ, self.env):
            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                orchestrator = closed_loop.get_evolution_orchestrator()
                orchestrator.pattern_miner.add_sequence(["a", "b"])
                # 默认节流间隔内的第二次变更不落盘
                orchestrator.pattern_miner.add_sequence(["c", "d"])
                data = json.loads(self.patterns_path.read_text(encoding="utf-8"))
                self.assertEqual(len(data["sequences"]), 1)
                # 关停 flush：强制全量落盘
                result = closed_loop.flush_evolution_persistence()
                self.assertTrue(result["pattern_miner"])
                data = json.loads(self.patterns_path.read_text(encoding="utf-8"))
                self.assertEqual(len(data["sequences"]), 2)
            finally:
                closed_loop.reset_evolution_orchestrator()


if __name__ == "__main__":
    unittest.main()
