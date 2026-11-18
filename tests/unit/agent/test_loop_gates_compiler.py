"""QwenPaw 对照批 B1：声明式停止门编译。

- specs 未声明（None/[]）→ compileLoopGates 返回 None（调用方回落默认装配，
  默认行为零变化）；
- 声明即完全按声明编译（不与默认装配并集）；
- 未知 kind / 未知参数 / 重复 kind 一律 ValueError（fail-closed）；
- 未显式给参的门从配置单源 limits 取默认（与既有装配同源）；
- `_buildGateRunner` 接线钉住（编译器被删=接线断，测试即红）。
"""

import inspect

import pytest

from neurova.agent.gates import (
    DoomLoopGate,
    GateRunner,
    IterationGate,
    TokenBudgetGate,
)
from neurova.agent.loop_gates_compiler import compileLoopGates

LIMITS = {
    "token_budget": 100000,
    "max_loop_rounds": 20,
    "goal_max_continuations": 2,
    "doom_loop_window_size": 6,
    "doom_loop_similarity_threshold": 1.0,
    "doom_loop_max_interrupts": 2,
}


def test_none_spec_returns_none():
    assert compileLoopGates(None, LIMITS) is None
    assert compileLoopGates([], LIMITS) is None


def test_compile_iteration_with_explicit_rounds():
    runner = compileLoopGates([{"kind": "iteration", "max_rounds": 12}], LIMITS)
    assert isinstance(runner, GateRunner)
    gates = runner.gates
    assert len(gates) == 1 and isinstance(gates[0], IterationGate)
    assert gates[0].max_rounds == 12


def test_compile_multiple_kinds_in_order():
    runner = compileLoopGates([
        {"kind": "token_budget", "max_tokens": 5000},
        {"kind": "iteration", "max_rounds": 8},
        {"kind": "doom_loop", "similarity_threshold": 0.95},
    ], LIMITS)
    kinds = [type(g) for g in runner.gates]
    assert kinds == [TokenBudgetGate, IterationGate, DoomLoopGate]
    doom = runner.gates[2]
    assert doom.similarity_threshold == 0.95
    assert doom.window_size == LIMITS["doom_loop_window_size"], "未声明参数取配置单源默认"


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="未知"):
        compileLoopGates([{"kind": "quantum_barrier"}], LIMITS)


def test_unknown_param_rejected():
    with pytest.raises(ValueError, match="未知参数"):
        compileLoopGates([{"kind": "iteration", "max_rounds": 5, "mode": "turbo"}], LIMITS)


def test_duplicate_kind_rejected():
    with pytest.raises(ValueError, match="重复"):
        compileLoopGates([
            {"kind": "iteration", "max_rounds": 5},
            {"kind": "iteration", "max_rounds": 9},
        ], LIMITS)


def test_wiring_in_build_gate_runner():
    from neurova.agent.loops.base import BaseAgentLoop

    source = inspect.getsource(BaseAgentLoop._buildGateRunner)
    assert "compileLoopGates" in source, (
        "_buildGateRunner 必须先走声明编译（无声明才回落默认装配）——接线被删即本用例红"
    )
