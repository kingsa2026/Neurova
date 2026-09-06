"""认知三链路巡检 P2 防回归：降级工具的降权必须在排序中生效。

根因：EvolutionOrchestrator.on_before_tool_selection 构建的 weights 字典
对 degraded 工具 ×0.7，但唯一生产消费方（context/orchestrator.
_apply_tool_lifecycle）只读 filtered/ranking，weights 被丢弃——降级惩罚
从未生效。
"""
import pytest


class _FakeWeights:
    def __init__(self, base):
        self._base = base

    def get_ranked_tools(self, names):
        return sorted(names, key=lambda n: -self._base.get(n, 1.0))

    def get_effective_weight(self, name):
        return self._base.get(name, 1.0)


class _FakeLifecycle:
    def __init__(self, states):
        self._states = states

    def get_state(self, tool):
        from types import SimpleNamespace

        v = self._states.get(tool, "active")
        return SimpleNamespace(value=v)


def _make_orchestrator(weights_base, states):
    from neurova.evolution.closed_loop import EvolutionOrchestrator

    orch = EvolutionOrchestrator.__new__(EvolutionOrchestrator)
    orch.tool_weights = _FakeWeights(weights_base)
    orch.tool_lifecycle = _FakeLifecycle(states)
    return orch


def test_degraded_tools_rank_after_active_with_equal_weight():
    orch = _make_orchestrator(
        weights_base={"good_tool": 1.0, "bad_tool": 1.0},
        states={"bad_tool": "degraded"},
    )
    result = orch.on_before_tool_selection(available_tools=["bad_tool", "good_tool"])
    ranking = result["ranking"]
    assert ranking.index("good_tool") < ranking.index("bad_tool"), (
        "同等权重下降级工具应排在活跃工具之后（×0.7 惩罚的排序形态）"
    )
    # weights 字典仍带惩罚值（诊断面）
    assert result["weights"]["bad_tool"] == pytest.approx(0.7)


def test_degraded_penalty_can_overcome_small_weight_gap():
    orch = _make_orchestrator(
        weights_base={"a": 1.0, "b": 0.8},
        states={"b": "degraded"},
    )
    result = orch.on_before_tool_selection(available_tools=["a", "b"])
    ranking = result["ranking"]
    assert ranking.index("a") < ranking.index("b")
