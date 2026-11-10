# -*- coding: utf-8 -*-
"""E1/E2/E3 成本链（survey §10.2）：usage 单源差分 → 每轮资源向量 → 被拒候选成本。

- E1：token 计数从既有 usage 记账链（`usage_accounting.snapshot`）取差分，
  不新建第二套计数（教义第 6 条）；确定性件记轮次/墙钟，不冒领真 token。
- E2：`cost_history` 的常数 1.0 旁增**资源向量** {turns,tokens,wall_ms}——
  向量不相加、逐维呈报（论文 Eq10 口径）；ROI 标量分母＝turns（迭代单位，
  即真实轮数），tokens/wall_ms 是并列呈报的维度。
- E3：被拒候选带 realized cost 入账，治理面聚合；零成本被拒不许静默入账
  （漏计费守卫）。
"""

import pytest

from neurova.core import usage_accounting as ua_module
from neurova.core.usage_accounting import (
    get_usage_accounting,
    reset_usage_accounting,
)


@pytest.fixture
def clean_usage():
    reset_usage_accounting()
    yield get_usage_accounting()
    reset_usage_accounting()


class TestCostVector:
    def test_iteration_records_resource_vector(self, tmp_path, monkeypatch):
        """E2：应用轮次记 {turns,tokens,wall_ms}，逐维呈报（向量不相加）。"""
        from unittest.mock import MagicMock

        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
        orch = RSIOrchestrator(
            sleep_system=MagicMock(), emotion_system=MagicMock(),
            experience_system=MagicMock(), tool_memory_system=MagicMock(),
        )
        vector = orch._iterationCostVector(wall_ms=123, tokens_delta=0)
        assert vector["turns"] == 1
        assert vector["tokens"] == 0
        assert vector["wall_ms"] == 123

    def test_tokens_from_usage_single_source_delta(self, clean_usage):
        """E1：token 维取 usage 单源差分——记账链里种一笔，差分即现身。"""
        from neurova.evolution.rsi.orchestrator import usageTokensDelta

        before = get_usage_accounting().snapshot()["total"]["total_tokens"]
        get_usage_accounting().record(
            model="m", provider="p", prompt_tokens=100, completion_tokens=50,
            estimated=False)
        after = get_usage_accounting().snapshot()["total"]["total_tokens"]
        assert usageTokensDelta(before, after) == 150
        assert usageTokensDelta(before, before) == 0
        # 负差分（单例被清）不出负数——记账面异常按 0 处理，不产假成本
        assert usageTokensDelta(before, after - 1000) == 0

    def test_analyzer_keeps_vector_history_and_scalar_roi(self, tmp_path, monkeypatch):
        """E2：收敛分析器并行保留向量史；ROI 标量分母仍是轮数（旧行为回归）。"""
        from neurova.evolution.rsi.convergence_analyzer import create_convergence_analyzer

        analyzer = create_convergence_analyzer()
        analyzer.record_iteration(gain=0.1, cost=1.0, evidenced=True,
                                  cost_vector={"turns": 1, "tokens": 150, "wall_ms": 40})
        analyzer.record_iteration(gain=0.2, cost=1.0, evidenced=True,
                                  cost_vector={"turns": 1, "tokens": 0, "wall_ms": 30})
        readout = analyzer.costVectorReadout()
        assert readout["totals"] == {"turns": 2, "tokens": 150, "wall_ms": 70}
        assert len(readout["iterations"]) == 2
        # ROI 标量路径回归：Σgain/Σcost = 0.3/2
        assert analyzer.compute_roi() == pytest.approx(0.15)


class TestRejectedCandidateCost:
    def test_eliminated_candidates_carry_realized_cost(self, tmp_path, monkeypatch):
        """E3：被筛掉的候选带 realized cost（计分回调调用数）入账。"""
        from neurova.evolution.rsi.recursive_ratchet_pruner import (
            Candidate,
            RecursiveRatchetPruner,
        )

        pruner = RecursiveRatchetPruner(rounds=3, candidates_per_round=[50, 10, 3])
        candidates = [
            Candidate(id=f"c{i}", name=f"c{i}", heuristic_score=1.0 - i * 0.1,
                      quick_evaluation_score=0.5, complexity=1.0)
            for i in range(5)
        ]
        best = pruner.recursive_prune(
            candidates=candidates,
            validation_fn=lambda c: {"valid": True, "score": 1.0},
            quick_eval_fn=lambda c: 0.5,
            heuristic_fn=lambda c: c.heuristic_score,
        )
        assert best is not None
        failed = pruner.failed_candidates_history
        assert failed, "无被拒入账——E3 的账面是空的"
        for entry in failed:
            assert entry.metadata.get("realized_cost", 0) >= 1, (
                f"零成本被拒静默入账（漏计费）：{entry.id}")

    def test_failed_cost_readout_aggregates(self, tmp_path, monkeypatch):
        """治理面聚合：被拒总数与 realized cost 总额可读。"""
        from neurova.evolution.rsi.recursive_ratchet_pruner import (
            Candidate,
            RecursiveRatchetPruner,
        )

        pruner = RecursiveRatchetPruner(rounds=3, candidates_per_round=[50, 10, 3])
        candidates = [
            Candidate(id=f"c{i}", name=f"c{i}", heuristic_score=1.0 - i * 0.1,
                      quick_evaluation_score=0.5, complexity=1.0)
            for i in range(5)
        ]
        pruner.recursive_prune(
            candidates=candidates,
            validation_fn=lambda c: {"valid": True, "score": 1.0},
            quick_eval_fn=lambda c: 0.5,
            heuristic_fn=lambda c: c.heuristic_score,
        )
        readout = pruner.failedCostReadout()
        assert readout["eliminated"] >= 1
        assert readout["total_realized_cost"] >= readout["eliminated"], (
            "聚合读数的成本总额小于被拒数——漏计费守卫失守")


def test_orchestrator_status_surfaces_cost_chain(tmp_path, monkeypatch):
    """状态面：cost_vector 与被拒成本聚合出街（写了有人读）。"""
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    status = orch.get_status()
    assert "cost_vector" in status, "资源向量读数未挂状态面"
    assert "pruner_failed_cost" in status, "被拒成本聚合未挂状态面"
