# -*- coding: utf-8 -*-
"""P3-2：MetaEvaluator 元层调参 + 两个空转件转正（计划书 §3.7 / §6 P3-2）。

判据结构（红→绿）：
- 红灯：``neurova/evolution/rsi/meta_evaluator.py`` 缺席时本文件收集即红（import 失败）；
- 数据不足（<3 代 / 无带判据样本）→ unevidenced 不调整；
- 某来源存活率显著高 → 权重上调且仍在区间内；近上界时钳制不越界；
- 回滚多的来源不被上调、被下调；
- 两个空转件转正：compareStrategies / deploymentAmortization 输出进 evidence；
- applyIfApproved：无 approver 拒 / 有 approver 入账 / 同号异摘要拒 / 幂等；
- 调参事件对账：baseVersion/newVersion/指标快照与策略台账、世代账本对得上。
"""

from __future__ import annotations

import pytest

from neurova.evolution.rsi.eval_harness import RSIEvalHarness
from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.evolution.rsi.generation_ledger import (
    ChangeRef,
    DecisionRef,
    DeploymentRef,
    EvolutionGeneration,
    GenerationLedger,
)
from neurova.evolution.rsi.meta_evaluator import (
    MIN_GENERATIONS_FOR_ADJUSTMENT,
    MetaEvaluator,
    PolicyAdjustment,
)
from neurova.evolution.rsi.policy import EvolutionPolicy, EvolutionPolicyLedger


# ---------------------------------------------------------------------------
# 世代构造助手：直接构造 EvolutionGeneration（与世代账本落盘 schema 同形）。
# kind 归源约定与生产一致：parameter→rsi / text→eval / patch→external。
# ---------------------------------------------------------------------------

def _verdict(state: str) -> GateVerdict:
    if state == "passed":
        return GateVerdict.passed("测试判据通过")
    if state == "failed":
        return GateVerdict.failed("测试判据失败")
    return GateVerdict.unevidenced("测试判据无证据")


def _gen(no: int, *, kinds=("parameter",), status="deployed",
         survival="passed", overall="passed", parentNo=None) -> EvolutionGeneration:
    return EvolutionGeneration(
        generationNo=no,
        parentNo=parentNo,
        basisCommit="abc1234",
        createdAt=f"2026-11-22T00:00:{no:02d}+00:00",
        changes=[
            ChangeRef(targetId=f"t{no}.{i}", kind=k, ref=f"c{no}-{i}",
                      rationale="测试候选")
            for i, k in enumerate(kinds)
        ],
        verdicts=(
            {"g0": _verdict(survival), "overall": _verdict(overall)}
            if survival is not None else {}
        ),
        status=status,
    )


def _rsiPassGen(no: int, **kw) -> EvolutionGeneration:
    return _gen(no, kinds=("parameter",), status="deployed", **kw)


def _evalFailGen(no: int, **kw) -> EvolutionGeneration:
    return _gen(no, kinds=("text",), status="rejected", survival="failed",
                overall="failed", **kw)


def _sufficientGens() -> list:
    """3 代 rsi 全存活 + 1 代 eval 失败：rsi 存活率 1.0 显著高于 eval 0.0。"""
    return [_rsiPassGen(1), _rsiPassGen(2), _rsiPassGen(3), _evalFailGen(4)]


class TestInsufficientDataNoAdjustment:
    """数据不足 → 如实 unevidenced，不调整、不产候选。"""

    def test_below_minimum_generations_reports_unevidenced(self):
        evaluator = MetaEvaluator()
        for gens in ([], [_gen(1)], [_gen(1), _gen(2)]):
            assert len(gens) < MIN_GENERATIONS_FOR_ADJUSTMENT
            adj = evaluator.evaluateAndPropose(
                policy=EvolutionPolicy.default(), generations=gens)
            assert adj.unevidenced is True
            assert adj.applied is False
            assert adj.proposedPolicy is None
            assert adj.newVersion == ""  # 无候选可入账
            assert "世代" in adj.reason

    def test_enough_generations_but_no_judged_samples_unevidenced(self):
        """世代数够但全部无判据 → 存活率不可估，照实 unevidenced。"""
        gens = [_gen(1, survival=None), _gen(2, survival=None), _gen(3, survival=None)]
        adj = MetaEvaluator().evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=gens)
        assert adj.unevidenced is True
        assert adj.applied is False
        assert adj.proposedPolicy is None


class TestEvidenceBasedAdjustment:
    """按世代证据在允许区间内调来源权重。"""

    def test_high_survival_source_weight_raised_within_bounds(self):
        base = EvolutionPolicy.default()
        adj = MetaEvaluator().evaluateAndPropose(
            policy=base, generations=_sufficientGens())
        assert adj.unevidenced is False
        assert adj.applied is True
        proposed = adj.proposedPolicy
        assert proposed is not None
        new_w = proposed.sourceWeights
        assert new_w["rsi"] > base.sourceWeights["rsi"]
        assert new_w["eval"] < base.sourceWeights["eval"]
        assert new_w["external"] == base.sourceWeights["external"]
        assert abs(sum(new_w.values()) - 1.0) < 1e-9
        assert all(0.0 <= v <= 1.0 for v in new_w.values())
        # 只动来源权重，其余元层字段保持基线
        assert proposed.maxTokensPerGeneration == base.maxTokensPerGeneration
        assert proposed.maxWallMs == base.maxWallMs
        assert proposed.shadowConcurrency == base.shadowConcurrency
        assert proposed.canaryWindow == base.canaryWindow
        assert proposed.gateThresholds == base.gateThresholds
        # 对账字段：版本链与指标快照
        assert adj.baseVersion == "P_0"
        assert adj.newVersion == "P_1"
        assert adj.sourceMetrics["rsi"]["survivalRate"] == 1.0
        assert adj.sourceMetrics["rsi"]["samples"] == 3
        assert adj.sourceMetrics["eval"]["survivalRate"] == 0.0
        assert adj.sourceMetrics["eval"]["samples"] == 1
        assert adj.evidence["generationCount"] == 4

    def test_near_upper_bound_clamped_not_exceeded(self):
        """已近上界：钳制到区间内（不越界），且构造校验通过。"""
        base = EvolutionPolicy(
            sourceWeights={"rsi": 0.985, "eval": 0.015, "external": 0.0})
        adj = MetaEvaluator().evaluateAndPropose(
            policy=base, generations=_sufficientGens())
        assert adj.applied is True
        new_w = adj.proposedPolicy.sourceWeights
        assert 0.0 <= new_w["rsi"] <= 1.0
        assert new_w["rsi"] > base.sourceWeights["rsi"]  # 仍在上调
        assert new_w["rsi"] == pytest.approx(1.0)  # 钳到上界而非 1.085
        assert new_w["eval"] == pytest.approx(0.0)
        assert abs(sum(new_w.values()) - 1.0) < 1e-9

    def test_rollback_heavy_source_not_rewarded_and_lowered(self):
        gens = [
            _gen(1, kinds=("text",), status="deployed"),
            _gen(2, kinds=("text",), status="deployed"),
            _gen(3, kinds=("parameter",), status="rolledBack"),
            _gen(4, kinds=("parameter",), status="rejected",
                 survival="failed", overall="failed"),
        ]
        base = EvolutionPolicy.default()
        adj = MetaEvaluator().evaluateAndPropose(policy=base, generations=gens)
        assert adj.applied is True
        new_w = adj.proposedPolicy.sourceWeights
        assert new_w["eval"] > base.sourceWeights["eval"]
        assert new_w["rsi"] < base.sourceWeights["rsi"]
        assert adj.sourceMetrics["rsi"]["rolledBack"] == 1
        assert adj.sourceMetrics["rsi"]["survivalRate"] == pytest.approx(0.5)

    def test_winner_with_rollbacks_vetoed_no_adjustment(self):
        """有回滚记录的来源不参评上调（安全第一）→ 本轮不调整。"""
        gens = [
            _gen(1, kinds=("parameter",), status="rolledBack"),
            _gen(2, kinds=("parameter",), status="rolledBack"),
            _evalFailGen(3),
            _evalFailGen(4),
            _evalFailGen(5),
        ]
        adj = MetaEvaluator().evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=gens)
        assert adj.applied is False
        assert adj.unevidenced is False  # 数据够，只是无可上调来源
        assert adj.proposedPolicy is None
        assert "回滚" in adj.reason

    def test_no_significant_margin_no_adjustment(self):
        """各来源存活率无显著差 → 不调整（数据足但不显著）。"""
        gens = [
            _rsiPassGen(1), _rsiPassGen(2),
            _gen(3, kinds=("text",), status="deployed"),
            _gen(4, kinds=("text",), status="deployed"),
        ]
        adj = MetaEvaluator().evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=gens)
        assert adj.applied is False
        assert adj.unevidenced is False
        assert adj.proposedPolicy is None

    def test_external_patch_source_attributed_and_adjustable(self):
        """patch 类变更归 external 来源，并可依证据上调。"""
        gens = [
            _gen(1, kinds=("patch",), status="deployed"),
            _gen(2, kinds=("patch",), status="deployed"),
            _gen(3, kinds=("patch",), status="deployed"),
            _evalFailGen(4),
        ]
        base = EvolutionPolicy.default()
        adj = MetaEvaluator().evaluateAndPropose(policy=base, generations=gens)
        assert adj.applied is True
        assert adj.sourceMetrics["external"]["survivalRate"] == 1.0
        assert adj.sourceMetrics["eval"]["survivalRate"] == 0.0
        assert adj.proposedPolicy.sourceWeights["external"] > base.sourceWeights["external"]


class TestIdleModulesPromoted:
    """两个空转件转正：MetaEvaluator 成为真实生产消费方，读数进 evidence。"""

    @staticmethod
    def _params(**overrides):
        base = {
            "tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                            "decay_rate": 0.01, "muscle_memory_threshold": 0.8},
            "sleep": {"base_decay_rate": 0.1, "similarity_threshold": 0.7},
            "emotion": {"emotional_protection_threshold": 0.5,
                        "emotional_protection_factor": 0.3},
            "experience": {"crystallize_min_observations": 3,
                           "crystallize_min_success_rate": 0.6,
                           "pattern_min_support": 2},
        }
        for system, params in overrides.items():
            base[system].update(params)
        return base

    def test_compare_strategies_output_lands_in_evidence(self):
        evaluator = MetaEvaluator(
            harness=RSIEvalHarness(),
            strategyParamsProvider=lambda: {
                "replay": self._params(),
                "selective_retain": self._params(tool_memory={"success_bonus": 0.15}),
                "refresh": self._params(tool_memory={"decay_rate": 0.02}),
            },
        )
        adj = evaluator.evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=_sufficientGens())
        readout = adj.evidence["strategyComparison"]
        assert readout["state"] == "measured"
        assert set(readout["scores"]) == {"replay", "selective_retain", "refresh"}
        assert readout["best"] in readout["scores"]

    def test_deployment_amortization_output_lands_in_evidence(self):
        evaluator = MetaEvaluator(
            usageSnapshotProvider=lambda: {"total": {"calls": 2, "total_tokens": 700}},
            devTokensProvider=lambda: 500,
            amortizationHorizon=100,
        )
        adj = evaluator.evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=_sufficientGens())
        readout = adj.evidence["deploymentAmortization"]
        assert readout["state"] == "measured"
        assert readout["serving_samples"] == 2
        assert readout["c_bar_task"] == pytest.approx(350.0)
        assert readout["c_total_n"] == pytest.approx(500 + 350.0 * 100)
        assert readout["dev_tokens"] == 500

    def test_default_wiring_reaches_real_usage_accounting(self):
        """默认装配（零注入）也真实消费 usage 记账 → deploymentAmortization。"""
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        try:
            adj = MetaEvaluator().evaluateAndPropose(
                policy=EvolutionPolicy.default(), generations=_sufficientGens())
        finally:
            reset_usage_accounting()
        readout = adj.evidence["deploymentAmortization"]
        # 无 serving 样本 → 如实 insufficient_data，不拿 0 冒充
        assert readout["state"] == "insufficient_data"
        assert "c_bar_task" in readout["missing"]
        assert readout["c_total_n"] is None

    def test_strategy_comparison_without_provider_reports_unevidenced(self):
        adj = MetaEvaluator().evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=_sufficientGens())
        readout = adj.evidence["strategyComparison"]
        assert readout["state"] == "unevidenced"
        assert readout.get("reason")


class TestApplyIfApproved:
    """applyIfApproved：本卡阶段一律人工批准；入账守台账既有纪律。"""

    @staticmethod
    def _adjustment() -> PolicyAdjustment:
        adj = MetaEvaluator().evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=_sufficientGens())
        assert adj.applied is True
        return adj

    def test_without_approver_rejected(self):
        ledger = EvolutionPolicyLedger()
        adj = self._adjustment()
        assert MetaEvaluator.applyIfApproved(adj, approver="", ledger=ledger) is False
        assert MetaEvaluator.applyIfApproved(adj, approver="   ", ledger=ledger) is False
        assert ledger.readAll() == []

    def test_unevidenced_adjustment_rejected_even_with_approver(self):
        ledger = EvolutionPolicyLedger()
        adj = MetaEvaluator().evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=[])
        assert adj.unevidenced is True
        assert MetaEvaluator.applyIfApproved(adj, approver="alice", ledger=ledger) is False
        assert ledger.readAll() == []

    def test_with_approver_registered_into_ledger(self):
        ledger = EvolutionPolicyLedger()
        adj = self._adjustment()
        assert MetaEvaluator.applyIfApproved(adj, approver="alice", ledger=ledger) is True
        entry = ledger.latest()
        assert entry["version"] == adj.newVersion == "P_1"
        assert entry["policy"] == adj.proposedPolicy.toDict()
        assert "alice" in entry["summary"]
        ledger.requireKnown("P_1")  # 已注册 → 不抛

    def test_same_version_different_summary_rejected(self):
        ledger = EvolutionPolicyLedger()
        adj = self._adjustment()
        assert MetaEvaluator.applyIfApproved(adj, approver="alice", ledger=ledger) is True
        forged = PolicyAdjustment(
            baseVersion=adj.baseVersion,
            newVersion=adj.newVersion,  # 同版本号
            applied=True,
            unevidenced=False,
            reason="另一份摘要的伪造调参",
            proposedPolicy=EvolutionPolicy(
                sourceWeights={"rsi": 0.2, "eval": 0.5, "external": 0.3}),
            sourceMetrics={},
            evidence={},
        )
        with pytest.raises(ValueError):
            MetaEvaluator.applyIfApproved(forged, approver="bob", ledger=ledger)

    def test_idempotent_reapply_same_adjustment(self):
        ledger = EvolutionPolicyLedger()
        adj = self._adjustment()
        assert MetaEvaluator.applyIfApproved(adj, approver="alice", ledger=ledger) is True
        assert MetaEvaluator.applyIfApproved(adj, approver="alice", ledger=ledger) is True
        assert len(ledger.readAll()) == 1


class TestReconciliationWithLedgers:
    """调参事件可对账：与世代账本（NEUROVA_EVOLUTION_GENERATIONS 的数据面）
    和策略版本台账（NEUROVA_EVOLUTION_POLICY 的数据面）都对得上。"""

    def test_adjustment_reconciles_with_generation_and_policy_ledgers(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_EVOLUTION_GENERATIONS", raising=False)
        gen_ledger = GenerationLedger()  # env 未配置 → 纯内存零 IO
        # 3 代 rsi 全存活：开代 → 落判据 → 裁决 → 晋升（走真实状态机）
        for no in (1, 2, 3):
            g = gen_ledger.openGeneration(
                None, [],
                [ChangeRef(targetId="rsi.parameterFamily", kind="parameter",
                           ref=f"c{no}", rationale="RSI 参数候选")],
                "abc1234")
            gen_ledger.recordVerdicts(g.generationNo, {"g0": GateVerdict.passed("存活")})
            gen_ledger.recordVerdicts(g.generationNo, {"overall": GateVerdict.passed("全绿")})
            gen_ledger.recordDecision(g.generationNo, DecisionRef(kind="auto"))
            gen_ledger.markDeployed(g.generationNo, DeploymentRef())
        # 1 代 eval 文本候选影子失败被拒
        g4 = gen_ledger.openGeneration(
            3, [],
            [ChangeRef(targetId="text.soul", kind="text",
                       ref="c4", rationale="文本候选")],
            "abc1234")
        gen_ledger.recordVerdicts(g4.generationNo, {"g0": GateVerdict.failed("影子失败")})
        gen_ledger.recordVerdicts(g4.generationNo, {"overall": GateVerdict.failed("门禁不过")})
        gen_ledger.markRejected(g4.generationNo, "G0 影子失败")

        generations = gen_ledger.listAll()
        assert len(generations) == 4

        adj = MetaEvaluator(baseVersion="P_0").evaluateAndPropose(
            policy=EvolutionPolicy.default(), generations=generations)
        assert adj.applied is True

        # 与世代账本对账：样本数与存活率可由世代记录复核
        rsi_gens = [g for g in generations
                    if any(c.kind == "parameter" for c in g.changes)]
        assert adj.sourceMetrics["rsi"]["samples"] == len(rsi_gens) == 3
        assert adj.sourceMetrics["rsi"]["survivalRate"] == 1.0
        assert adj.sourceMetrics["eval"]["samples"] == 1
        assert adj.sourceMetrics["eval"]["survivalRate"] == 0.0
        assert adj.evidence["generationCount"] == len(generations)

        # 与策略版本台账对账：新版本入账、载荷与候选策略一致
        policy_ledger = EvolutionPolicyLedger()
        assert MetaEvaluator.applyIfApproved(
            adj, approver="alice", ledger=policy_ledger) is True
        entry = policy_ledger.latest()
        assert entry["version"] == adj.newVersion
        assert EvolutionPolicy.fromDict(entry["policy"]) == adj.proposedPolicy
