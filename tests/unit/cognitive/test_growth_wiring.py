"""成长链路接线测试（P1）

覆盖两处签名错配的根因修复:
- P1-3: agent_core.SubSystemContainer.init_cognition 用 GrowthAnalyzer 不接受的
  storage_path 参数构造 → TypeError 被 except 吞掉 → growth_analyzer 恒为 None。
- P1-4: post_chat_pipeline._step_cognitive_analysis 用不存在的
  concepts/context 关键字调用 record_learning（真实签名为 dimension/score/...）。
"""

import asyncio
import shutil
import tempfile
import types
import unittest
from pathlib import Path

from neurova.agent_core import SubSystemContainer
from neurova.cognitive_layers.growth_layer.analyzer import GrowthAnalyzer, GrowthDimension
from neurova.post_chat_pipeline import PostChatPipeline


class _ContainerStub:
    """绕开 SubSystemContainer.__init__ 的重依赖，仅提供 init_cognition 所需属性"""

    def __init__(self, agent):
        self.agent = agent
        self.config = agent.config


class _FakeConfig:
    def __init__(self, workspace_path):
        self.enable_cognitive_capabilities = True
        self.enable_memory = False
        self.workspace_path = Path(workspace_path)
        self.agent_id = "agent_growth_test"


class _FakeAgent:
    def __init__(self, workspace_path):
        self.config = _FakeConfig(workspace_path)
        self.memory_manager = object()  # 仅需真值


class GrowthWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_cognition_builds_growth_analyzer(self):
        agent = _FakeAgent(self.tmpdir)
        SubSystemContainer.init_cognition(_ContainerStub(agent))
        self.assertIsInstance(
            agent.growth_analyzer,
            GrowthAnalyzer,
            "init_cognition 必须用真实签名构造 GrowthAnalyzer（此前 TypeError 被吞，恒为 None）",
        )
        self.assertEqual(agent.growth_analyzer._agent_id, "agent_growth_test")

    def test_record_learning_signature_contract(self):
        analyzer = GrowthAnalyzer(agent_id="agent_growth_test")
        record = analyzer.record_learning(
            dimension=GrowthDimension.LEARNING,
            score=72.5,
            task_type="conversation",
            description="对话认知分析",
            metadata={"concepts": ["机器学习", "模型训练"]},
        )
        self.assertEqual(record.dimension, GrowthDimension.LEARNING)
        # _calculate_learning_score 用 EMA（首条 = raw × learning_rate=0.1），而非直存 raw
        self.assertAlmostEqual(record.score, 7.25)
        self.assertAlmostEqual(analyzer._capability_scores[GrowthDimension.LEARNING], 7.25)
        self.assertEqual(len(analyzer._records[GrowthDimension.LEARNING]), 1)

    def test_cognitive_analysis_records_learning(self):
        analyzer = GrowthAnalyzer(agent_id="agent_growth_test")
        agent = types.SimpleNamespace(growth_analyzer=analyzer)
        pipeline = PostChatPipeline(agent)

        score = asyncio.run(pipeline._step_cognitive_analysis("机器学习，模型训练！这是一个重要话题"))

        self.assertGreaterEqual(score, 0.3)
        self.assertLessEqual(score, 1.0)
        records = analyzer._records[GrowthDimension.LEARNING]
        self.assertEqual(
            len(records),
            1,
            "认知分析应真实写入成长记录（此前 record_learning(concepts=...) 签名错配抛 TypeError）",
        )
        # raw = pipeline score(0.3-1.0) × 100；首条 EMA = raw × 0.1
        self.assertAlmostEqual(records[0].score, score * 100.0 * 0.1, places=2)
        self.assertTrue(records[0].metadata.get("concepts"))


if __name__ == "__main__":
    unittest.main()
