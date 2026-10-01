"""P1-6 增益维度剪枝提案 — 三证合取产退役计划的红灯测试。

RRSI 对齐：近 N 轮改进候选全被评测拒绝（增益耗尽）× 使用归因零正贡献
× 技能未受保护 → 往既有 ConsolidationPlanStore 产一条待审计划。
只产计划、绝不执行；任一证缺失不产出；闸拒绝不算"无增益"证据。
"""

import pytest

from neurova.evolution.eval.history_ledger import EvolutionLedger


@pytest.fixture
def ledger(tmp_path):
    return EvolutionLedger(tmp_path / "history")


def _reject(ledger, key, reason="no_improvement", n=5):
    for i in range(n):
        ledger.append(key, {"ts": f"T{i}", "hypothesis": f"假设{i}",
                            "accepted": False, "reject_reason": reason})


class TestLedgerSupport:
    def test_keys_and_tail(self, tmp_path):
        ledger = EvolutionLedger(tmp_path / "h")
        ledger.append("a", {"hypothesis": "x", "accepted": True})
        ledger.append("a", {"hypothesis": "y", "accepted": False})
        ledger.append("b", {"hypothesis": "z", "accepted": False})
        assert ledger.keys() == ["a", "b"]
        assert [r["hypothesis"] for r in ledger.tail("a", 1)] == ["y"]
        # tail 不做墙压缩（判读面拿原始记录）
        for i in range(6):
            ledger.append("c", {"hypothesis": f"w{i}", "accepted": False,
                                "reject_reason": "leak:task_specialization"})
        assert len(ledger.tail("c", 6)) == 6
        assert any("gate_wall" in r for r in ledger.recent("c", 6))


class TestConjunction:
    def test_all_three_evidence_emits_plan(self, ledger, tmp_path):
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a")
        store = ConsolidationPlanStore(tmp_path / "skills")
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 4, "positive": 0, "negative": 3},
            is_protected_fn=lambda sid: False,
            plan_store=store,
        )
        assert len(plans) == 1 and plans[0]["umbrella"] == "sk-a"
        assert plans[0]["reason"] == "evolution_yield_exhausted"
        assert plans[0]["basis"] == "evolution_yield"
        assert plans[0]["quality"]["reject_streak"] == 5
        assert plans[0]["quality"]["usage"]["positive"] == 0
        # 落进了既有待审仓，状态 pending
        stored = store.load()
        assert stored and stored[0]["umbrella"] == "sk-a"
        assert stored[0]["status"] == "pending"

    def test_usage_with_positive_blocks_prune(self, ledger, tmp_path):
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a")
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 9, "positive": 2, "negative": 1},
            plan_store=ConsolidationPlanStore(tmp_path / "skills"),
        )
        assert plans == []

    def test_usage_below_floor_blocks_prune(self, ledger, tmp_path):
        """从未被用过（times_used=0）：没有使用证据不剪。"""
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a")
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 0, "positive": 0, "negative": 0},
            plan_store=ConsolidationPlanStore(tmp_path / "skills"),
        )
        assert plans == []

    def test_accepted_record_breaks_streak(self, ledger, tmp_path):
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a", n=4)
        ledger.append("sk-a", {"hypothesis": "有效改进", "accepted": True,
                               "reject_reason": ""})
        ledger.append("sk-a", {"hypothesis": "又一个", "accepted": False,
                               "reject_reason": "no_improvement"})
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 4, "positive": 0, "negative": 3},
            plan_store=ConsolidationPlanStore(tmp_path / "skills"),
        )
        assert plans == []

    def test_gate_rejections_do_not_count(self, ledger, tmp_path):
        """闸拒绝（背题/越界）是提案质量问题，不是无增益证据。"""
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a", reason="leak:task_specialization")
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 4, "positive": 0, "negative": 3},
            plan_store=ConsolidationPlanStore(tmp_path / "skills"),
        )
        assert plans == []

    def test_protected_skill_skipped(self, ledger, tmp_path):
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a")
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 4, "positive": 0, "negative": 3},
            is_protected_fn=lambda sid: sid == "sk-a",  # pinned
            plan_store=ConsolidationPlanStore(tmp_path / "skills"),
        )
        assert plans == []

    def test_protected_probe_failure_skips_skill(self, ledger, tmp_path):
        """保护判据抛异常 → 宁勿误杀，跳过该技能。"""
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a")

        def _boom(sid):
            raise RuntimeError("probe boom")

        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 4, "positive": 0, "negative": 3},
            is_protected_fn=_boom,
            plan_store=ConsolidationPlanStore(tmp_path / "skills"),
        )
        assert plans == []

    def test_no_auto_apply(self, ledger, tmp_path):
        """函数签名无 registry/skill 写入口——产出后计划仍待审批。"""
        from neurova.evolution.evolution_yield_prune import (
            propose_evolution_prune_candidates,
        )
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore

        _reject(ledger, "sk-a")
        store = ConsolidationPlanStore(tmp_path / "skills")
        plans = propose_evolution_prune_candidates(
            ledger=ledger,
            usage_fn=lambda sid: {"times_used": 4, "positive": 0, "negative": 3},
            plan_store=store,
        )
        assert plans
        assert all(p["status"] == "pending" for p in store.load())
