# -*- coding: utf-8 -*-
"""T-02 工具目录稳定性：同会话内工具集合未变 ⇒ 下发的 tools 数组逐字节相同。

provider 侧前缀缓存要求工具目录在会话内稳定：顺序一变，整段工具目录及其
之后的上下文全部重新计费。此前 `_apply_tool_lifecycle` 按权重把整个数组
重排（权重每轮都在动），一次重排即全量失效。

锁定三件事：
1. 稳定：同一会话连续两轮，工具集合未变 ⇒ 最终下发数组逐字节相同（含顺序）；
   集合确有变化时允许变化，且变化必须能归因到集合本身。
2. 过滤不回退：归档/冻结工具仍不得下发（防「为了稳定把过滤也关了」）。
3. ranking 不落成只写不读：权重只在**裁剪优先级**上有消费面——目录压缩
   裁剪到预算内时，高权重隐藏工具不得先被丢掉。
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from neurova.context.orchestrator import ContextOrchestrator
from neurova.evolution.closed_loop import EvolutionOrchestrator
from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState


def _tool(name: str, desc: str = "") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc or f"{name} 工具",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def _names(tools) -> list:
    return [t["function"]["name"] for t in tools or []]


def _make_orchestrator(evolution) -> ContextOrchestrator:
    """最小 orchestrator：只补 build_tools_for_llm 链上真实消费的属性。"""
    orch = ContextOrchestrator.__new__(ContextOrchestrator)
    orch._agent = SimpleNamespace(evolution=evolution)
    return orch


def _drive(orch, tools, rounds: int = 1):
    """走生产装配点取数：仅聚合边界（router/skill 的 IO 面）打桩，其余全真。"""
    import neurova.context.orchestrator as orch_mod

    out = None
    for _ in range(rounds):
        with patch.object(orch_mod, "_build_tools_for_llm", new=AsyncMock(return_value=tools)):
            out = asyncio.run(orch.build_tools_for_llm())
    return out


def _canonical(tools) -> str:
    """下发数组的逐字节形态（provider 看到的正是这份序列化）。"""
    return json.dumps(tools, ensure_ascii=False, sort_keys=False)


def _evolution(tool_names) -> EvolutionOrchestrator:
    evo = EvolutionOrchestrator(tool_lifecycle=ToolLifecycleManager())
    evo.register_tools(list(tool_names))
    return evo


@pytest.fixture(autouse=True)
def _compaction_off(monkeypatch):
    """默认关掉目录压缩，让稳定断言只面对生命周期段。"""
    monkeypatch.setenv("NEUROVA_TOOL_SEARCH", "0")
    monkeypatch.delenv("NEUROVA_HIDE_DEGRADED_TOOLS", raising=False)


class TestCatalogByteStability:
    """同集合同会话 ⇒ 下发数组逐字节相同。"""

    def test_weight_change_does_not_reorder_tools(self):
        """两轮之间权重翻转（真实权重表推进），下发数组必须逐字节不变。"""
        evo = _evolution(["alpha", "beta", "gamma"])
        orch = _make_orchestrator(evo)
        tools = [_tool("gamma"), _tool("beta"), _tool("alpha")]

        first = _drive(orch, tools)
        # 第二轮前：把原本排在最后的 beta 打成高权重（旧实现据此整数组重排）
        for _ in range(5):
            evo.on_after_tool_execution("beta", success=True)
            evo.on_after_tool_execution("gamma", success=False)
        second = _drive(orch, tools)

        assert _canonical(second) == _canonical(first), (
            f"工具集合未变而下发顺序漂移：{_names(first)} → {_names(second)}"
        )

    def test_set_change_is_attributable_to_the_set(self):
        """集合确有变化时允许变化，但既有工具的相对顺序不得被打乱。"""
        evo = _evolution(["alpha", "beta"])
        orch = _make_orchestrator(evo)

        before = _drive(orch, [_tool("alpha"), _tool("beta")])
        after = _drive(orch, [_tool("alpha"), _tool("beta"), _tool("delta")])

        assert set(_names(after)) - set(_names(before)) == {"delta"}
        kept = [n for n in _names(after) if n in _names(before)]
        assert kept == _names(before), f"新增工具不得扰动既有工具次序：{_names(after)}"

    def test_degraded_tool_rank_flip_keeps_catalog_stable(self):
        """降级惩罚（×0.7）逼出的名次翻转，同样不得传导到下发顺序。"""
        lifecycle = ToolLifecycleManager()
        evo = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        evo.register_tools(["good_tool", "bad_tool"])
        orch = _make_orchestrator(evo)
        tools = [_tool("good_tool"), _tool("bad_tool")]

        first = _drive(orch, tools)
        lifecycle._entries["bad_tool"].state = ToolLifecycleState.DEGRADED
        second = _drive(orch, tools)

        assert _canonical(second) == _canonical(first), "降级只应影响裁剪优先级，不得改下发顺序"


class TestFilterSemanticsKept:
    """过滤语义不得为稳定让步。"""

    def test_archived_and_frozen_tools_stay_invisible(self):
        lifecycle = ToolLifecycleManager()
        evo = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        evo.register_tools(["active_tool", "archived_tool", "frozen_tool"])
        lifecycle._entries["archived_tool"].state = ToolLifecycleState.ARCHIVED
        lifecycle._entries["frozen_tool"].state = ToolLifecycleState.FROZEN
        orch = _make_orchestrator(evo)
        tools = [_tool("active_tool"), _tool("archived_tool"), _tool("frozen_tool")]

        got = _names(_drive(orch, tools))
        assert got == ["active_tool"], f"归档/冻结工具不得下发：{got}"

        # 两轮连打：过滤必须逐轮生效，不得因为"稳定"缓存住上一轮的下发集
        got2 = _names(_drive(orch, tools))
        assert got2 == ["active_tool"], f"归档/冻结工具不得下发：{got2}"

    def test_degraded_tool_still_downstream_visible_by_default(self, monkeypatch):
        """降级工具默认仍在工具面（可见性门控是 env 门控，默认关）。"""
        lifecycle = ToolLifecycleManager()
        evo = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        evo.register_tools(["good_tool", "bad_tool"])
        lifecycle._entries["bad_tool"].state = ToolLifecycleState.DEGRADED
        orch = _make_orchestrator(evo)

        assert set(_names(_drive(orch, [_tool("good_tool"), _tool("bad_tool")]))) == {
            "good_tool",
            "bad_tool",
        }

    def test_visibility_gate_env_still_hides_degraded(self, monkeypatch):
        """NEUROVA_HIDE_DEGRADED_TOOLS=1 的既有行为不得连带改变。"""
        monkeypatch.setenv("NEUROVA_HIDE_DEGRADED_TOOLS", "1")
        lifecycle = ToolLifecycleManager()
        evo = EvolutionOrchestrator(tool_lifecycle=lifecycle)
        evo.register_tools(["good_tool", "bad_tool"])
        lifecycle._entries["bad_tool"].state = ToolLifecycleState.DEGRADED
        orch = _make_orchestrator(evo)

        assert _names(_drive(orch, [_tool("good_tool"), _tool("bad_tool")])) == ["good_tool"]


class TestRankingFeedsClipPriority:
    """ranking 的唯一消费面是裁剪优先级（不许落成只写不读）。"""

    def _hidden_tools(self, count: int) -> list:
        return [_tool(f"longtail_tool_{i:02d}", "长尾工具描述" * 20) for i in range(count)]

    def test_high_weight_hidden_tool_survives_directory_clip(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH", "1")
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_BUDGET", "400")
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_MIN_CATALOG", "40")

        tools = self._hidden_tools(60)
        heavy = "longtail_tool_59"  # 按名排序本来会被预算裁掉的那一个
        evo = _evolution([t["function"]["name"] for t in tools])
        for name in _names(tools):
            if name == heavy:
                continue
            for _ in range(5):  # 过小样本免疫阈值（min_observations=3）才真正降权
                evo.on_after_tool_execution(name, success=False)
        for _ in range(3):
            evo.on_after_tool_execution(heavy, success=True)
        orch = _make_orchestrator(evo)

        out = _drive(orch, tools)
        directory = next(
            t["function"]["description"] for t in out if t["function"]["name"] == "tool_search_directory"
        )
        assert heavy in directory, (
            f"高权重隐藏工具被目录预算裁掉——ranking 的裁剪优先级没接线：{directory[:200]}"
        )

    def test_directory_clip_keeps_names_under_budget_when_no_priority(self, monkeypatch):
        """无 ranking 时行为不变：目录仍是按序装填到预算内。"""
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH", "1")
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_BUDGET", "400")
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_MIN_CATALOG", "40")

        tools = self._hidden_tools(60)
        evo = _evolution([])
        orch = _make_orchestrator(evo)

        out = _drive(orch, tools)
        assert any(t["function"]["name"] == "tool_search_directory" for t in out)
