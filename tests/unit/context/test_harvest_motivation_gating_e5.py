"""E5 件 2：动机调制补接收割点（E3 移交清偿，修复教义第 5 条）。

根因：E3 已把 purpose/autonomy 强度接进 post_chat_pipeline 的 QuestionQueue
出队点，但真链路里问题队列的真消费方是
`ContextOrchestrator._collect_pending_questions`（构建上下文时收割 pending 并
mark_asked，每轮先于管线出队点得手，管线出队点常扑空）——调制在线上不约束
实际提问频率。

判据（与 E3 出队点同口径）：
- 低强度（新鲜账本 purpose/autonomy 均值落低档）→ 间隔窗口内收割被 gating
  （返回空、问题不 mark_asked、留在队列）；
- 高强度 → 收割照常（连续两轮均可收割，不受额外限流）；
- 无账本 → 不调制（保持原行为）；
- 间隔窗口过后 → 恢复收割；
- 复用同一个 `resolveMotivationQuestionInterval` 纯函数（不复制第二套逻辑）。
"""

import os
import shutil
import tempfile
import time
import types
import unittest

from neurova.context.orchestrator import ContextOrchestrator
from neurova.core.motivation_ledger import MotivationLedger
from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionQueueManager


class HarvestMotivationGatingTest(unittest.TestCase):
    """收割点（_collect_pending_questions）的动机调制两态。"""

    def _make(self, agent_id: str):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        ledger = MotivationLedger(agent_id=agent_id, persistence_path=os.path.join(tmpdir, "m.json"))
        qqm = QuestionQueueManager(memory_manager=None, default_cooldown=0.0)
        agent = types.SimpleNamespace(intrinsic_motivation=ledger, question_queue_manager=qqm)
        orchestrator = ContextOrchestrator(agent, use_pool=False)
        return orchestrator, ledger, qqm

    def _primeHigh(self, ledger: MotivationLedger) -> None:
        """经既有 observe 口把 purpose/autonomy 均值推到高档（≥0.45）。"""
        for i in range(5):
            ledger.observe_purpose(contribution=f"贡献{i}", impact=0.8)
        for i in range(3):
            ledger.observe_autonomy(choice=f"选择{i}", satisfaction=1.0)

    def test_lowIntensityGatesHarvestWithinInterval(self):
        """低强度：刚收割过（间隔窗口内）→ 本轮收割被挡，问题不 mark_asked 留队列。"""
        orchestrator, ledger, qqm = self._make("e5-harvest-lo")
        qqm.generate_question(content="待探索问题一")
        orchestrator._lastProactiveAskAt = time.time()  # 上一轮刚收割提问

        items = orchestrator._collect_pending_questions()

        self.assertEqual(items, [], "低强度间隔窗口内收割必须被 gating")
        self.assertEqual(len(qqm.get_pending_questions()), 1, "被挡下的问题不得 mark_asked")

    def test_highIntensityHarvestsImmediately(self):
        """高强度：不受额外限流，照常收割并 mark_asked、刷新记账。"""
        orchestrator, ledger, qqm = self._make("e5-harvest-hi")
        self._primeHigh(ledger)
        qqm.generate_question(content="待探索问题一")
        orchestrator._lastProactiveAskAt = time.time()

        items = orchestrator._collect_pending_questions()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content"], "待探索问题一")
        self.assertGreaterEqual(orchestrator._lastProactiveAskAt, time.time() - 5)

    def test_missingLedgerKeepsLegacyHarvest(self):
        """无动机账本 → 不调制（与 E3 出队点同口径：不凭空造 0.5 强度）。"""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        qqm = QuestionQueueManager(memory_manager=None, default_cooldown=0.0)
        qqm.generate_question(content="待探索问题一")
        agent = types.SimpleNamespace(question_queue_manager=qqm)  # 无 intrinsic_motivation
        orchestrator = ContextOrchestrator(agent, use_pool=False)
        orchestrator._lastProactiveAskAt = time.time()  # 刚收割过，若无调制必被挡

        items = orchestrator._collect_pending_questions()

        self.assertEqual(len(items), 1, "无账本不得调制，收割行为保持原样")

    def test_intervalExpiryRestoresHarvest(self):
        """间隔窗口过后恢复收割（低强度只是拉长间隔，不是永久禁止）。"""
        from neurova.post_chat_pipeline import MOTIVATION_QUESTION_MIN_INTERVAL_LOW_S

        orchestrator, ledger, qqm = self._make("e5-harvest-expiry")
        qqm.generate_question(content="待探索问题一")
        orchestrator._lastProactiveAskAt = time.time() - (MOTIVATION_QUESTION_MIN_INTERVAL_LOW_S + 1.0)

        items = orchestrator._collect_pending_questions()

        self.assertEqual(len(items), 1, "间隔窗口过后应恢复收割")

    def test_sharesSameIntervalFunctionAsDequeuePoint(self):
        """与出队点共用同一个纯函数与常量表（严禁第二套逻辑/常量）。"""
        import inspect

        from neurova.post_chat_pipeline import (
            MOTIVATION_QUESTION_INTERVAL_TABLE,
            resolveMotivationQuestionInterval,
        )

        src = inspect.getsource(ContextOrchestrator._collect_pending_questions)
        self.assertIn("resolveMotivationQuestionInterval", src, "收割点必须复用出队点纯函数")
        # 强度→间隔映射与 E3 常量表同源（低强度间隔最长）
        low = resolveMotivationQuestionInterval(0.1)
        high = resolveMotivationQuestionInterval(0.9)
        self.assertGreaterEqual(low, high)
        self.assertIn((0.0, low), MOTIVATION_QUESTION_INTERVAL_TABLE)


if __name__ == "__main__":
    unittest.main()
