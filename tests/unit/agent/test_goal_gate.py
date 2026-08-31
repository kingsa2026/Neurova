"""
P2-5 goal 模式门控测试（GoalGate：目标达成判定 + 轮次预算）
"""

import pytest

from neurova.agent.gates import DoomLoopGate, GoalGate, GateRunner, StopAction


class TestGoalGate:
    def test_completion_check_achieved_terminates(self):
        gate = GoalGate(
            goal={"id": "g1", "description": "部署完成"},
            completion_check=lambda goal, ctx: (True, "所有服务已上线"),
        )
        decision = gate.check({"tool_rounds": 3})
        assert decision.action == StopAction.TERMINATE
        assert "目标达成" in decision.reason
        assert "所有服务已上线" in decision.reason

    def test_not_achieved_continues_within_budget(self):
        gate = GoalGate(
            goal={"id": "g1"},
            completion_check=lambda goal, ctx: (False, ""),
            max_rounds=15,
        )
        decision = gate.check({"tool_rounds": 3})
        assert decision.action == StopAction.BYPASS

    def test_round_budget_exhausted_terminates(self):
        gate = GoalGate(
            goal={"id": "g1"},
            completion_check=lambda goal, ctx: (False, ""),
            max_rounds=5,
        )
        decision = gate.check({"tool_rounds": 5})
        assert decision.action == StopAction.TERMINATE
        assert "轮次预算耗尽" in decision.reason

    def test_completion_check_exception_treated_as_not_achieved(self):
        def boom(goal, ctx):
            raise RuntimeError("rubric down")

        gate = GoalGate(goal={"id": "g1"}, completion_check=boom, max_rounds=15)
        decision = gate.check({"tool_rounds": 2})
        assert decision.action == StopAction.BYPASS  # 异常不终止

    def test_via_runner_with_doom_loop(self):
        """goal 模式组合：GoalGate + DoomLoopGate 共同治理"""
        gate = GoalGate(
            goal={"id": "g1"},
            completion_check=lambda goal, ctx: (ctx.get("tool_rounds", 0) >= 4, "done"),
            max_rounds=10,
        )
        runner = GateRunner([gate, DoomLoopGate()])
        decision = runner.on_round_end({"tool_rounds": 4, "round_signature": "s4"})
        assert decision.action == StopAction.TERMINATE
        assert "目标达成" in decision.reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
