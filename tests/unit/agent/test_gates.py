"""
P2-5 门控系统红测（对标 QP loop/gates 三态语义）
"""

import pytest

from neurova.agent.gates import (
    GateRunner,
    IterationGate,
    StopAction,
    StopDecision,
    StopGate,
    TokenBudgetGate,
    DoomLoopGate,
)


class TestStopAction:
    def test_three_states(self):
        assert StopAction.BYPASS.value == "bypass"
        assert StopAction.INTERRUPT_AND_CONTINUE.value == "interrupt_and_continue"
        assert StopAction.TERMINATE.value == "terminate"


class TestIterationGate:
    def test_under_limit_bypass(self):
        gate = IterationGate(max_rounds=20)
        decision = gate.check({"tool_rounds": 5})
        assert decision.action == StopAction.BYPASS

    def test_at_limit_terminates(self):
        gate = IterationGate(max_rounds=20)
        decision = gate.check({"tool_rounds": 20})
        assert decision.action == StopAction.TERMINATE
        assert "20" in decision.reason


class TestTokenBudgetGate:
    def test_under_budget_bypass(self):
        gate = TokenBudgetGate(max_tokens=100000)
        decision = gate.check({"round_usage": {"total_tokens": 50000}})
        assert decision.action == StopAction.BYPASS

    def test_over_budget_terminates(self):
        gate = TokenBudgetGate(max_tokens=100000)
        decision = gate.check({"round_usage": {"total_tokens": 100000}})
        assert decision.action == StopAction.TERMINATE


class TestDoomLoopGate:
    def test_first_pass_bypass(self):
        gate = DoomLoopGate()
        assert gate.check({"round_signature": "sig1"}).action == StopAction.BYPASS

    def test_repeated_signature_interrupts(self):
        gate = DoomLoopGate()
        gate.check({"round_signature": "sig1"})
        decision = gate.check({"round_signature": "sig1"})
        assert decision.action == StopAction.INTERRUPT_AND_CONTINUE
        assert "重复" in decision.continuation_prompt

    def test_max_interrupts_terminates_and_resets(self):
        gate = DoomLoopGate(max_interrupts=2)
        gate.check({"round_signature": "s"})
        gate.check({"round_signature": "s"})
        decision = gate.check({"round_signature": "s"})
        assert decision.action == StopAction.TERMINATE
        # 终止时重置：后续新序列不受污染
        assert gate.check({"round_signature": "fresh"}).action == StopAction.BYPASS

    def test_stale_window_recovers(self):
        """窗口过期：新签名出现时中断计数清零（间歇性重复不误杀）"""
        gate = DoomLoopGate()
        gate.check({"round_signature": "dup"})
        gate.check({"round_signature": "dup"})  # 1 次中断
        gate.check({"round_signature": "different"})  # 新序列 → 计数清零
        decision = gate.check({"round_signature": "dup"})  # 又重复 → 重新计 1
        assert decision.action == StopAction.INTERRUPT_AND_CONTINUE

    def test_distinct_signatures_no_interrupt(self):
        gate = DoomLoopGate()
        for i in range(5):
            d = gate.check({"round_signature": f"sig{i}"})
            assert d.action == StopAction.BYPASS


class TestGateRunner:
    def test_empty_runner_bypass(self):
        runner = GateRunner([])
        decision = runner.on_round_end({})
        assert decision.action == StopAction.BYPASS  # 显式 bypass（无须判 None）

    def test_terminate_priority_over_interrupt(self):
        """TERMINATE 优先于一切：同时有 interrupt gate 命中也返回 terminate"""
        runner = GateRunner()

        class _Terminate(StopGate):
            name, priority = "t", 50
            def check(self, ctx):
                return StopDecision(action=StopAction.TERMINATE, reason="t")

        class _Interrupt(StopGate):
            name, priority = "i", 10
            def check(self, ctx):
                return StopDecision(action=StopAction.INTERRUPT_AND_CONTINUE, continuation_prompt="x")

        runner.add_gate(_Interrupt())
        runner.add_gate(_Terminate())

        decision = runner.on_round_end({})
        assert decision.action == StopAction.TERMINATE

    def test_gate_exception_isolated_as_bypass(self):
        """gate 异常故障隔离为 BYPASS（不因门控故障瘫痪循环）"""

        class _Boom(StopGate):
            name, priority = "boom", 1
            def check(self, ctx):
                raise RuntimeError("gate down")

        runner = GateRunner([_Boom()])
        decision = runner.on_round_end({})
        assert decision.action == StopAction.BYPASS  # 故障隔离为显式 bypass

    def test_gates_returns_copy(self):
        class _Dummy(StopGate):
            name, priority = "d", 100
            def check(self, ctx):
                return StopDecision.bypass()

        runner = GateRunner([_Dummy()])
        gates = runner.gates
        gates.clear()
        assert len(runner.gates) == 1  # 返回副本，外部改动不影响内部

    def test_iteration_gate_via_runner(self):
        runner = GateRunner([IterationGate(max_rounds=2)])
        decision = runner.on_round_end({"tool_rounds": 5})
        assert decision.action == StopAction.TERMINATE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
