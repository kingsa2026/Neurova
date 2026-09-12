"""结晶混合信号层测试（QP 对齐启发 #1，2026-09-12）。

规则预筛（≥3 次 & 成功率≥60%）保持零成本不变；LLM 闸开启且 judge 在位时，
候选不再直写存储引擎，进入待裁决队列，由复盘通道低频批量裁决——
被否决者不写库（过滤词面匹配伪模式），超龄自动放行（零 LLM 环境不丢数据）。
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer


class _FakeEngine:
    def __init__(self):
        self.stored = []

    def store(self, node):
        self.stored.append(node)

    def retrieve(self, query, limit=5, filters=None):
        return []


def _make_crystallizer(tmp_dir, llm_gate="1"):
    with patch.dict(os.environ, {"NEUROVA_CRYSTALLIZATION_LLM_GATE": llm_gate}):
        engine = _FakeEngine()
        state = os.path.join(tmp_dir, "cryst_state.json")
        c = PatternCrystallizer(engine=engine, state_path=state)
    return c, engine


def _observe_three(c, key_ctx="搜索 资料 天气", tool="web_search"):
    for _ in range(3):
        c.observe(tool, key_ctx, True)


class CrystallizationLLMGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    import tempfile

    def test_no_judge_direct_write_zero_llm_semantics(self):
        """judge 未注入 = 零 LLM 语义：规则通过即直写（现有行为不变）。"""
        c, engine = _make_crystallizer(self.tmp)
        _observe_three(c)
        self.assertEqual(len(engine.stored), 1, "无 judge 时应直写")
        self.assertEqual(c.list_pending(), [])

    def test_judge_injected_routes_to_pending(self):
        c, engine = _make_crystallizer(self.tmp)
        c.set_llm_judge(MagicMock())
        _observe_three(c)
        self.assertEqual(len(engine.stored), 0, "judge 在位时不得直写")
        self.assertEqual(len(c.list_pending()), 1)

    def test_confirm_pending_approve_writes_store(self):
        c, engine = _make_crystallizer(self.tmp)
        c.set_llm_judge(MagicMock())
        _observe_three(c)
        pending = c.list_pending()
        result = c.confirm_pending(
            [{"key": pending[0]["key"], "approved": True, "reason": "可复用"}]
        )
        self.assertEqual(result["approved"], 1)
        self.assertEqual(len(engine.stored), 1)
        self.assertIn("web_search", engine.stored[0].content)
        self.assertEqual(c.list_pending(), [])

    def test_confirm_pending_reject_drops(self):
        c, engine = _make_crystallizer(self.tmp)
        c.set_llm_judge(MagicMock())
        _observe_three(c)
        pending = c.list_pending()
        result = c.confirm_pending(
            [{"key": pending[0]["key"], "approved": False, "reason": "一次性事实"}]
        )
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(len(engine.stored), 0, "被否决的伪模式不得写库")
        self.assertEqual(c.list_pending(), [])

    def test_unreviewed_candidates_kept(self):
        """LLM 漏判的候选留队等下轮（不丢数据）。"""
        c, _ = _make_crystallizer(self.tmp)
        c.set_llm_judge(MagicMock())
        _observe_three(c)
        result = c.confirm_pending([])  # LLM 返回空裁决
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(c.list_pending()), 1)

    def test_review_pending_with_llm_end_to_end(self):
        import asyncio

        c, engine = _make_crystallizer(self.tmp)
        c.set_llm_judge(MagicMock())
        _observe_three(c)

        class _FakeLLM:
            async def generate(self, prompt):
                self.prompt = prompt
                return '{"verdicts": [{"key": "' + c.list_pending()[0]["key"] + '", "reusable": false, "reason": "临时环境故障"}]}'

        llm = _FakeLLM()
        result = asyncio.run(c.review_pending_with_llm(llm))
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(len(engine.stored), 0)
        self.assertIn("可复用", llm.prompt)

    def test_gate_off_direct_write_even_with_judge(self):
        c, engine = _make_crystallizer(self.tmp, llm_gate="0")
        c.set_llm_judge(MagicMock())
        _observe_three(c)
        self.assertEqual(len(engine.stored), 1, "闸显式关闭=回退直写")

    def test_pending_survives_reinit(self):
        """待裁决队列持久化：重启不丢候选。"""
        state = os.path.join(self.tmp, "cryst.json")
        with patch.dict(os.environ, {"NEUROVA_CRYSTALLIZATION_LLM_GATE": "1"}):
            engine = _FakeEngine()
            c1 = PatternCrystallizer(engine=engine, state_path=state)
            c1.set_llm_judge(MagicMock())
            for _ in range(3):
                c1.observe("web_search", "搜索 资料", True)
            self.assertEqual(len(c1.list_pending()), 1)

            c2 = PatternCrystallizer(engine=_FakeEngine(), state_path=state)
            self.assertEqual(len(c2.list_pending()), 1, "重启后待审候选应恢复")


if __name__ == "__main__":
    unittest.main()
