"""成长分析器持久化测试（P2-A）

恢复原设计意图: agent_core.init_cognition 原本传 storage_path 期望落盘，
但 GrowthAnalyzer 从未实现持久化（签名也无此参数）→ 双重断链。
本测试验证 storage_path 参数真实生效：记录跨实例恢复。
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from neurova.agent_core import SubSystemContainer
from neurova.cognitive_layers.growth_layer.analyzer import GrowthAnalyzer, GrowthDimension


class GrowthPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_records_persist_across_instances(self):
        workspace = os.path.join(self.tmpdir, "growth")

        first = GrowthAnalyzer(agent_id="g1", workspace_path=workspace)
        first.record_learning(
            dimension=GrowthDimension.LEARNING,
            score=60.0,
            task_type="conversation",
            description="对话学习",
            metadata={"concepts": ["测试概念"]},
        )
        self.assertTrue(
            os.path.exists(os.path.join(workspace, "growth.json")),
            "record_learning 后应在允许目录内写盘",
        )

        second = GrowthAnalyzer(agent_id="g1", workspace_path=workspace)
        self.assertEqual(len(second._records[GrowthDimension.LEARNING]), 1, "记录应跨实例恢复")
        self.assertAlmostEqual(
            second._capability_scores[GrowthDimension.LEARNING],
            first._capability_scores[GrowthDimension.LEARNING],
        )

    def test_capability_scores_continue_from_loaded_state(self):
        """恢复后的 EMA 应基于已恢复的能力分数继续演化，而非从 0 重来"""
        workspace = os.path.join(self.tmpdir, "growth2")

        first = GrowthAnalyzer(agent_id="g1", workspace_path=workspace)
        for _ in range(5):
            first.record_learning(dimension=GrowthDimension.COGNITIVE, score=80.0)
        score_after_first = first._capability_scores[GrowthDimension.COGNITIVE]
        self.assertGreater(score_after_first, 8.0, "多次记录后 EMA 应显著高于首条")

        second = GrowthAnalyzer(agent_id="g1", workspace_path=workspace)
        second.record_learning(dimension=GrowthDimension.COGNITIVE, score=80.0)

        # 行为断言: 恢复后继续演化（高于恢复值），而非从 0 重来（重来首条 EMA=8）
        self.assertGreater(
            second._capability_scores[GrowthDimension.COGNITIVE],
            score_after_first,
            msg="重启后新记录应基于恢复后的能力分数继续演化",
        )
        self.assertEqual(
            len(second._records[GrowthDimension.COGNITIVE]),
            6,
            "恢复的 5 条 + 新 1 条",
        )

    def test_workspace_path_must_be_absolute(self):
        """相对路径（含穿越写法）必须被拒绝"""
        with self.assertRaises(ValueError):
            GrowthAnalyzer(agent_id="g1", workspace_path="relative/dir")

    def test_init_cognition_passes_workspace_path(self):
        """agent_core.init_cognition 应传入 workspace_path 恢复原持久化设计"""
        tmpdir = tempfile.mkdtemp()
        try:

            class _Cfg:
                enable_cognitive_capabilities = True
                enable_memory = False
                workspace_path = Path(tmpdir)
                agent_id = "persist_agent"

            class _Container:
                def __init__(self):
                    self.agent = SimpleNamespace(config=_Cfg(), memory_manager=object())
                    self.config = self.agent.config

            container = _Container()
            SubSystemContainer.init_cognition(container)

            self.assertIsNotNone(container.agent.growth_analyzer)
            expected = (Path(tmpdir) / "memory" / "growth" / "growth.json").resolve()
            self.assertEqual(
                container.agent.growth_analyzer._storage_file,
                expected,
                "init_cognition 应把 workspace/memory/growth 作为持久化目录",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
