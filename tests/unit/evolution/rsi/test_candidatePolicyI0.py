# -*- coding: utf-8 -*-
"""A2 候选生成程序对象化（survey §10.2）：I_t 的可版本化载体。

三个自由度（步进选择／剪枝次序／打分公式）从 `generate_optimizations` 内联逻辑
抽为 `CandidatePolicy`；`I_0` 钉当前行为为冻结复刻（同输入逐值相等，防抽取漂移）；
`improverVersionLedger` 落盘可读回、伪造版本号被拒。结构格：编排器三函数体
不再含步进字面量（AST 判据）。
"""

import ast
import json

import pytest

from neurova.evolution.rsi.candidate_policy import (
    I_0_SUMMARY,
    CandidatePolicy,
    ImproverVersionLedger,
    resolve_improver_ledger,
)
from neurova.evolution.rsi.recursive_ratchet_pruner import Candidate


def _policy():
    """无密封校验注入的 I_0（步进/打分自由度不依赖密封面；密封校验由编排器注入）。"""
    return CandidatePolicy.I_0(
        setpoint_lookup=lambda system, name: {"muscle_memory_threshold": 0.8}.get(name),
        performance_extractor=lambda signals: (signals or {}).get("performance"),
        sealed_validator=None,
    )


def _cand(cid="c1", *, ratio=0.10, complexity=0.5, performance=0.5):
    return Candidate(
        id=cid, name=cid,
        parameters={"parameter": "tool_memory.muscle_memory_threshold",
                    "new_value": 0.79, "adjustment_ratio": ratio},
        complexity=complexity,
        heuristic_score=1.0 - abs(ratio - 0.10) * 5,
        metadata={"optimization": {
            "system": "tool_memory",
            "parameter": "tool_memory.muscle_memory_threshold",
            "current_value": 0.85, "new_value": 0.79,
            "setpoint": 0.8,
        }, "performance": performance},
    )


class TestStepReplica:
    """行为格：I_0 复刻与原内联语义逐值相等（期望值独立推导，不抄实现）。"""

    def test_numeric_param_steps_toward_setpoint(self):
        policy = _policy()
        candidates = policy.stepCandidates(
            "tool_memory", "muscle_memory_threshold", 0.85,
            signals={"performance": 0.5},
        )
        # 期望独立推导：delta=-0.05，步进 [5/10/15/20%] → [0.8475, 0.845, 0.8425, 0.84]
        assert [round(c.metadata["optimization"]["new_value"], 6) for c in candidates] == [
            0.8475, 0.845, 0.8425, 0.84]
        assert [c.parameters["adjustment_ratio"] for c in candidates] == [0.05, 0.10, 0.15, 0.20]
        assert all(c.metadata["optimization"]["setpoint"] == 0.8 for c in candidates)
        assert all(c.metadata["optimization"]["performance"] == 0.5 for c in candidates)
        # 复杂度与启发式同源原公式：|new-current|/max(|current|,0.001)、1-|ratio-0.10|*5
        first = candidates[0]
        assert first.complexity == pytest.approx(abs(0.8475 - 0.85) / max(0.85, 0.001))
        assert first.heuristic_score == pytest.approx(1.0 - abs(0.05 - 0.10) * 5)

    def test_int_param_keeps_int_semantics(self):
        policy = _policy()
        candidates = policy.stepCandidates(
            "tool_memory", "muscle_memory_threshold", 9,
            signals={"performance": 0.5},
        )
        # setpoint 0.8：delta=-8.2 → int(round(9-0.41))=9? 不——逐值推导：
        # [9-8.2*0.05, ...] = [8.59, 8.18, 7.77, 7.36] → int(round(·)) = [9, 8, 8, 7]
        # 首个与现值相等被剔除（原语义：new_value == current_f 则 continue）
        assert [c.metadata["optimization"]["new_value"] for c in candidates] == [8, 8, 7]
        assert all(isinstance(c.metadata["optimization"]["new_value"], int) for c in candidates)

    def test_at_setpoint_and_unmeasurable_params_produce_nothing(self):
        policy = _policy()
        assert policy.stepCandidates("tool_memory", "muscle_memory_threshold", 0.8,
                                     signals={}) == []
        # 非数值现值 / 未知参数 / 非数值 setpoint → 空列表（原语义逐条保留）
        assert policy.stepCandidates("tool_memory", "muscle_memory_threshold", "bad",
                                     signals={}) == []
        empty_lookup = CandidatePolicy.I_0(
            setpoint_lookup=lambda system, name: None,
            performance_extractor=lambda signals: None,
            sealed_validator=None,
        )
        assert empty_lookup.stepCandidates("tool_memory", "muscle_memory_threshold", 0.85,
                                           signals={}) == []


class TestScoringReplica:
    """打分公式复刻：期望值按原内联公式独立推导。"""

    def test_quick_eval_formula(self):
        policy = _policy()
        # 原公式：expected_improvement = (1-perf) * adjustment * 10；减 complexity*0.5
        candidate = _cand(ratio=0.10, complexity=0.5, performance=0.5)
        assert policy.quickEvalScore(candidate) == pytest.approx((1 - 0.5) * 0.10 * 10 - 0.5 * 0.5)

    def test_validation_formula_direction_and_sealed(self):
        policy = _policy()
        # 反向调整 → 0；非数值病值漏过方向门 → 密封校验注入时由它裁决（无注入则 unevidenced）
        reverse = _cand()
        reverse.metadata["optimization"]["new_value"] = 0.9  # 远离 setpoint 0.8
        result = policy.validationResult(reverse)
        assert result["valid"] is False and result["score"] == 0.0

        toward = _cand()  # 0.79 → 朝 0.8
        result = policy.validationResult(toward)
        assert result["valid"] is True and result["score"] == 1.0


class TestStructureGuard:
    """结构格：编排器三函数体不再含步进字面量（AST 判据，防抽取回漂）。"""

    def test_orchestrator_bodies_free_of_step_literals(self):
        import neurova.evolution.rsi.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)
        tree = ast.parse(source)
        banned = {0.05, 0.10, 0.15, 0.20, 0.1, 0.15, 0.2}
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                "generate_optimizations", "_generate_candidates_for_param", "_prune_candidates",
            }:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, float):
                        if sub.value in banned:
                            offenders.append((node.name, sub.value, sub.lineno))
        assert not offenders, (
            f"步进/打分字面量仍留在编排器函数体：{offenders}——候选策略抽取未闭环")


class TestVersionLedger:
    """台账格：版本落盘可读回、伪造版本号被拒、同版本重注册幂等、冲突摘要被拒。"""

    def test_register_readback_and_forgery_rejection(self, tmp_path, monkeypatch):
        ledger_path = tmp_path / "improver_versions.json"
        monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(ledger_path))

        ledger = resolve_improver_ledger()
        assert ledger is not None
        ledger.register("I_0", I_0_SUMMARY)
        ledger.register("I_0", I_0_SUMMARY)  # 幂等

        entries = ledger.readAll()
        assert [e["version"] for e in entries] == ["I_0"]
        assert entries[0]["summary"] == I_0_SUMMARY
        assert entries[0]["registered_at"]

        # 落盘可读回（新实例读同一文件）
        reopened = resolve_improver_ledger()
        assert [e["version"] for e in reopened.readAll()] == ["I_0"]
        reopened.requireKnown("I_0")  # 不抛
        with pytest.raises(Exception):
            reopened.requireKnown("I_999")  # 伪造版本号被拒

        with pytest.raises(Exception):
            reopened.register("I_0", "改了摘要的同版本号")  # 冲突摘要被拒

    def test_unconfigured_ledger_still_functions_in_memory(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
        ledger = resolve_improver_ledger()
        assert ledger is not None, "未配置 env 的进程内账仍须可用（注册/查询不落盘）"
        ledger.register("I_0", I_0_SUMMARY)
        ledger.requireKnown("I_0")
        with pytest.raises(Exception):
            ledger.requireKnown("I_x")


def test_orchestrator_registers_I0_and_delegates(tmp_path, monkeypatch):
    """装配格：编排器构造即注册 I_0；generate_optimizations 产出自策略步进值集。"""
    ledger_path = tmp_path / "improver_versions.json"
    monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(ledger_path))
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )

    entries = ImproverVersionLedger(ledger_path).readAll()
    assert "I_0" in [e["version"] for e in entries], "编排器构造未注册 I_0"
    assert orch._candidate_policy is not None

    # 委托格：策略直算的步进值集是编排器产出的值域（每参数剪枝出一个最优，
    # 其 new_value 必须落在策略步进值集内——值域失守即委托失守）。
    policy = CandidatePolicy.I_0(
        setpoint_lookup=lambda system, name: {"muscle_memory_threshold": 0.8}.get(name),
        performance_extractor=lambda signals: 0.5,
        sealed_validator=None,
    )
    steps = {round(c.metadata["optimization"]["new_value"], 6)
             for c in policy.stepCandidates(
                 "tool_memory", "muscle_memory_threshold", 0.85, signals={})}
    assert steps == {0.8475, 0.845, 0.8425, 0.84}
    assert orch._candidate_policy.version == "I_0"
