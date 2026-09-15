"""MotivationLedger 契约测试（2026-09-15 动机/主动行为真实化）

设计约束：
- 包装 core/intrinsic_motivation.IntrinsicMotivationSystem（775 行已实现但零接线）
- drive 内部状态无序列化接口 → 跨重启持久化用**事件流回放**（observe 事件 JSON
  落盘 <dir>/motivation.json，重建实例时重放恢复），不发明第二套状态模型
- snapshot() 直接产出 /growth/motivation 端点所需形状：
  {agent_id, level, factors:[{name, impact}], updated_at, drives:{...}}
"""

import os
import tempfile
import unittest

from neurova.core.motivation_ledger import MotivationLedger


class MotivationLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "motivation", "motivation.json")
        self.ledger = MotivationLedger(agent_id="t1", persistence_path=self.path)

    def test_snapshot_shape_matches_endpoint_contract(self):
        snap = self.ledger.snapshot()
        self.assertEqual(snap["agent_id"], "t1")
        self.assertIsInstance(snap["level"], float)
        self.assertGreaterEqual(snap["level"], 0.0)
        self.assertLessEqual(snap["level"], 1.0)
        self.assertIsInstance(snap["factors"], list)
        names = {f["name"] for f in snap["factors"]}
        self.assertEqual(names, {"competence", "autonomy", "growth", "purpose"})
        self.assertIn("updated_at", snap)
        self.assertIn("drives", snap)

    def test_observe_events_move_snapshot_values(self):
        """真实信号必须改变快照——恒等于默认值即是假接口"""
        before = self.ledger.snapshot()["drives"]["competence"]["intensity"]
        for _ in range(5):
            self.ledger.observe_competence(success=True, difficulty=0.5)
        after = self.ledger.snapshot()["drives"]["competence"]["intensity"]
        self.assertNotEqual(before, after, "competence 事件后强度必须变化")

        g_before = self.ledger.snapshot()["drives"]["growth"]["intensity"]
        self.ledger.observe_growth(concept="量子计算", understanding=0.9)
        g_after = self.ledger.snapshot()["drives"]["growth"]["intensity"]
        self.assertGreater(g_after, g_before)

        a_before = self.ledger.snapshot()["drives"]["autonomy"]["intensity"]
        self.ledger.observe_autonomy(choice="主动提问澄清需求", satisfaction=0.8)
        a_after = self.ledger.snapshot()["drives"]["autonomy"]["intensity"]
        self.assertNotEqual(a_before, a_after)

    def test_purpose_observed(self):
        p_before = self.ledger.snapshot()["drives"]["purpose"]["intensity"]
        self.ledger.observe_purpose(contribution="澄清问题获用户回答", impact=0.8)
        self.assertGreater(
            self.ledger.snapshot()["drives"]["purpose"]["intensity"],
            p_before,
        )

    def test_persistence_replay_restores_drive_state(self):
        """事件流落盘，新实例（同路径）回放 → 状态跨重启恢复"""
        for _ in range(4):
            self.ledger.observe_growth(concept="测试概念", understanding=0.85)
        expected = self.ledger.snapshot()["drives"]["growth"]["intensity"]
        self.assertTrue(os.path.exists(self.path), "observe 后必须落盘")

        ledger2 = MotivationLedger(agent_id="t1", persistence_path=self.path)
        restored = ledger2.snapshot()["drives"]["growth"]["intensity"]
        self.assertAlmostEqual(expected, restored, places=6)

    def test_snapshot_level_is_weighted_intensity(self):
        """level 必须等于四驱动加权强度（与 drives 自洽，非独立常量）"""
        self.ledger.observe_competence(success=True, difficulty=0.4)
        snap = self.ledger.snapshot()
        weights = snap["drive_weights"]
        manual = sum(snap["drives"][k]["intensity"] * weights[k] for k in weights)
        self.assertAlmostEqual(snap["level"], round(manual, 4), places=3)

    def test_update_drive_weights(self):
        self.ledger.update_drive_weights({"competence": 0.7, "growth": 0.3})
        weights = self.ledger.snapshot()["drive_weights"]
        self.assertAlmostEqual(weights["competence"], 0.7, places=2)
        self.assertAlmostEqual(weights["autonomy"], 0.0, places=2)

    def test_events_capped(self):
        for i in range(1200):
            self.ledger.observe_competence(success=bool(i % 2), difficulty=0.5)
        # 事件流有界（防无界增长）
        with open(self.path, encoding="utf-8") as f:
            import json

            data = json.load(f)
        self.assertLessEqual(len(data["events"]), 1000)


if __name__ == "__main__":
    unittest.main()
