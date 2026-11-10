# -*- coding: utf-8 -*-
"""A3 Eq8 配对探针 ImproverPairedProbe（survey §10.2）。

同一批留出起始参数态，I_t 与 I_0 各产候选、同预算跑下游，输出 Γ_t(B)（后继质量差
＋逐对明细）。与主轨迹完全隔离（不进 gain/回滚/收敛史，先观测后升判据）。
三态纪律复用 task_yardstick：measured / insufficient_data（MIN_ENTRIES 先例）/
unevidenced（版本缺失不空转）。
"""

import json

import pytest

from neurova.evolution.rsi.candidate_policy import CandidatePolicy
from neurova.evolution.rsi.improver_paired_probe import ImproverPairedProbe
from neurova.evolution.rsi.task_yardstick import MIN_ENTRIES

def _states(n=12):
    """确定性起始态（≥ MIN_ENTRIES）：合成可控，不依赖真实子系统。"""
    return [
        {"system": "tool_memory", "param": f"param_{i}",
         "current": round(0.85 + i * 0.001, 6), "setpoint": 0.8}
        for i in range(n)
    ]


def _policies(version_t="I_0"):
    """同源 I_0（+可换名的 I_t）：配对探针的固定双版本输入。"""
    mk = lambda version: CandidatePolicy(
        version=version,
        summary="synthetic",
        setpoint_lookup=lambda s, n: 0.8,
        performance_extractor=lambda signals: 0.5,
        sealed_validator=None,
    )
    return mk(version_t), mk("I_0")


def _probe(policy_t, policy_0, *, outcome=None, states=None):
    states = _states() if states is None else states
    return ImproverPairedProbe(
        policy_t=policy_t, policy_0=policy_0,
        starting_states=lambda: list(states),
        outcome_evaluator=outcome or (lambda state, candidate: 0.5),
    )


class TestThreeStateDiscipline:
    def test_missing_versions_report_unevidenced_not_silent(self):
        """接口格：I_t/I_0 版本缺失报 unevidenced 而非空转（GateVerdict 纪律）。"""
        probe = ImproverPairedProbe(
            policy_t=None, policy_0=None,
            starting_states=lambda: list(STATES),
            outcome_evaluator=lambda state, candidate: 0.5,
        )
        readout = probe.run()
        assert readout["state"] == "unevidenced"
        assert readout.get("reason"), "缺席必须说原因，不得静默"

    def test_insufficient_states_report_insufficient_data(self):
        """三态格：起始态 < MIN_ENTRIES（yardstick 先例）→ insufficient_data。"""
        policy_t, policy_0 = _policies()
        probe = _probe(policy_t, policy_0, states=_states(2))
        readout = probe.run()
        assert readout["state"] == "insufficient_data"
        assert readout["score"] is None
        assert readout["states"] < MIN_ENTRIES

    def test_enough_states_report_measured_with_gamma_and_pairs(self):
        policy_t, policy_0 = _policies()
        probe = _probe(policy_t, policy_0)
        readout = probe.run()
        assert readout["state"] == "measured"
        assert readout["score"] is not None
        assert len(readout["pairs"]) == len(_states())
        assert readout["realized_evaluations"] == 3 * len(_states()), (
            "A4 起无更新臂每态 1 评——预算记账 3×起始态")


class TestDirectionAndDeterminism:
    def test_gamma_measures_downstream_difference_with_sign(self):
        """判向格：I_t 产出的候选下游更差 → Γ<0；更好 → Γ>0（符号即事实）。

        I_t 必须是真变体（不同步进档位）——同语义复刻配对 Γ 恒 0 是当前生产
        现实（I_t 尚未升级），判向格量的就是变体间的方向差。
        """
        policy_0 = _policies()[1]

        class _AggressiveT(CandidatePolicy):
            """步进更大的 I_t 变体（A5 换版后的形态预演）。"""

            STEP_RATIOS = (0.10, 0.20, 0.30, 0.40)

        aggressive_t = _AggressiveT(
            version="I_test-aggressive",
            summary="synthetic variant with bigger steps",
            setpoint_lookup=lambda s, n: 0.8,
            performance_extractor=lambda signals: 0.5,
            sealed_validator=None,
        )

        def outcome(state, candidate):
            # 合成可控结局流：策略信念的 setpoint=0.8，真目标=0.9——步进越大
            # 离真目标越远结局越差（步进永远朝信念目标，激进步进越过真目标）
            if candidate is None:
                return 1.0 - abs(state["current"] - 0.9)  # 无更新臂：留在原地的质量
            new_value = candidate.metadata["optimization"]["new_value"]
            return 1.0 - abs(new_value - 0.9)

        worse = _probe(aggressive_t, policy_0, outcome=outcome).run()
        # I_t 步进更大 → 离真目标更远 → 结局更差 → Γ < 0
        assert worse["score"] is not None and worse["score"] < 0

        # 反转结局流：步进越大越好 → Γ > 0
        reversed_outcome = lambda state, candidate: (
            abs(state["current"] - 0.9) if candidate is None
            else abs(candidate.metadata["optimization"]["new_value"] - 0.9))
        better = _probe(aggressive_t, policy_0, outcome=reversed_outcome).run()
        assert better["score"] is not None and better["score"] > 0

    def test_byte_identical_determinism(self):
        """确定性格：固定双版本输入＋合成结局流 → 两次探针输出逐字节相等。"""
        policy_t, policy_0 = _policies()

        def outcome(state, candidate):
            if candidate is None:
                return 1.0  # 无更新臂基线
            return round(1.0 - abs(
                candidate.metadata["optimization"]["new_value"] - state["setpoint"]), 6)

        first = json.dumps(_probe(policy_t, policy_0, outcome=outcome).run(),
                           ensure_ascii=False, sort_keys=True)
        second = json.dumps(_probe(policy_t, policy_0, outcome=outcome).run(),
                            ensure_ascii=False, sort_keys=True)
        assert first == second, "配对探针失去确定性——重放式读数失效"

    def test_isolation_no_side_effects(self):
        """隔离格：探针只读不写——结局评估器调用计数即预算，无外部状态被改。"""
        policy_t, policy_0 = _policies()
        calls = []

        def outcome(state, candidate):
            calls.append(candidate.id if candidate is not None else None)
            return 0.5

        probe = _probe(policy_t, policy_0, outcome=outcome)
        before_ids = [s["current"] for s in probe._startingStates()]
        probe.run()
        after_ids = [s["current"] for s in probe._startingStates()]
        assert before_ids == after_ids, "探针改动了起始态（隔离失守）"
        assert len(calls) == 3 * len(_states()), "预算记账与实际评估数不符"


class TestGovernanceSurface:
    def test_orchestrator_status_surfaces_probe_readout(self, tmp_path, monkeypatch):
        """呈报格：get_status 挂 improver_paired_probe 读数（三态诚实）。"""
        from unittest.mock import MagicMock

        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
        orch = RSIOrchestrator(
            sleep_system=MagicMock(), emotion_system=MagicMock(),
            experience_system=MagicMock(), tool_memory_system=MagicMock(),
        )
        readout = orch.get_status().get("improver_paired_probe")
        assert isinstance(readout, dict), "配对探针读数未挂状态面"
        assert readout.get("state") in {"measured", "insufficient_data", "unevidenced"}, (
            f"三态词汇失守：{readout.get('state')}")


class TestDualControlArms:
    """A4 双对照臂：全循环（I_t 更新 S 与自身）vs 冻结 I_0（只更新 S）vs
    无持久更新（推理时搜索不落盘）。三臂同起始态同预算同评估器——隔离的是
    "改进器贡献"这一个变量。"""

    def _aggressive_t(self):
        class _AggressiveT(CandidatePolicy):
            STEP_RATIOS = (0.10, 0.20, 0.30, 0.40)

        return _AggressiveT(
            version="I_test-aggressive", summary="synthetic variant",
            setpoint_lookup=lambda s, n: 0.8,
            performance_extractor=lambda signals: 0.5,
            sealed_validator=None,
        )

    def test_three_arms_reported_with_realized_cost_within_cap(self):
        """预算格：三臂各自 realized cost 报出且不超帽（帽＝起始态数）。"""
        policy_t, policy_0 = _policies()
        readout = _probe(policy_t, policy_0).run()
        assert readout["state"] == "measured"
        arms = readout["arms"]
        assert set(arms.keys()) == {"full", "frozen_I_0", "no_update"}
        cap = len(_states())
        for name, arm in arms.items():
            assert arm["realized"] <= cap, f"{name} 臂 realized 超帽：{arm['realized']}"
        assert readout["realized_evaluations"] <= 3 * cap

    def test_no_update_arm_invariant_under_policy_swap(self):
        """变异格：把 I_t 换成激进变体 → 全循环臂读数变化，无更新臂纹丝不动。

        无更新臂从不评估候选（每态固定 1 次基线评估）——双对照真的隔离了
        "持久更新"这个变量。
        """
        def outcome(state, candidate):
            if candidate is None:
                return 0.5  # 无候选：基线质量恒定
            return 1.0 - abs(candidate.metadata["optimization"]["new_value"] - 0.9)

        baseline_probe = _probe(_policies()[0], _policies()[1], outcome=outcome)
        swapped_probe = _probe(self._aggressive_t(), _policies()[1], outcome=outcome)

        base = baseline_probe.run()
        swapped = swapped_probe.run()
        assert base["state"] == "measured" and swapped["state"] == "measured"
        assert base["arms"]["no_update"] == swapped["arms"]["no_update"], (
            "无更新臂跟着策略换动了——对照臂没有隔离住变量")
        assert base["arms"]["full"] != swapped["arms"]["full"], (
            "换 I_t 后全循环臂读数没变——臂读数没有跟着策略走")
        assert base["arms"]["frozen_I_0"] == swapped["arms"]["frozen_I_0"], (
            "冻结 I_0 臂不受 I_t 换版影响")

    def test_no_update_arm_evaluates_without_candidates(self):
        """无更新臂的评估形态：evaluator 收到 candidate=None（不落盘的基线质量）。"""
        seen = []
        policy_t, policy_0 = _policies()
        _probe(policy_t, policy_0, outcome=lambda s, c: seen.append(c) or 0.5).run()
        none_count = sum(1 for c in seen if c is None)
        assert none_count == len(_states()), (
            f"无更新臂评估次数 {none_count} ≠ 起始态数——基线臂没有按态各评一次")
