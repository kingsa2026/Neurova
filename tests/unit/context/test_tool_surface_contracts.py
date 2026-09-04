"""§6 改进项组 1（A1+A2+A4）契约测试——工具注入面单源化/可见性门控/字符预算。

A1 单源化：get_tools_description 消费 build_tools_for_llm 的**已筛选**清单（现状已
如此），但清单渲染是第二轮独立遍历——本契约锁定"渲染遍历同一份对象"，并要求
清单条目数 == tools 参数条目数（防双重注入漂移）。

A2 可见性门控：DEGRADED 工具不进 LLM 工具面（tools 参数与描述清单均不可见），
ARCHIVED/FROZEN 维持原有过滤；非 evolution 场景零变化。

A4 字符预算：工具描述清单超过预算（默认 18000 字符）时降级渲染——先截断参数段，
再只保留 name+截断 description；tools 参数（schema 面）不受预算影响。
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _tool(name, desc="d", params=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": params or {"type": "object", "properties": {}, "required": []},
        },
    }


def _make_orchestrator(tool_names, lifecycle=None):
    """构造带 _apply_tool_lifecycle 依赖的最小 orchestrator。"""
    import neurova.context.orchestrator as orch_mod

    self_mock = MagicMock()
    self_mock._agent = MagicMock()
    self_mock.config = MagicMock()
    # _build_tools_for_llm 走真实函数需要 tool_router 等，这里直接打桩返回清单
    tools = [_tool(n) for n in tool_names]
    return orch_mod, self_mock, tools


class TestA1SingleSource(unittest.TestCase):
    """A1：描述清单与 tools 参数单源。"""

    def test_description_count_matches_tools_count(self):
        import asyncio
        from neurova.context.orchestrator import ContextOrchestrator

        orch = object.__new__(ContextOrchestrator)
        sample = [_tool("web_search", "搜索"), _tool("file_read", "读文件")]

        with patch.object(
            ContextOrchestrator, "build_tools_for_llm", new=AsyncMock(return_value=sample)
        ):
            desc = asyncio.run(orch.get_tools_description())

        listed = [line for line in desc.splitlines() if line.startswith("- **")]
        self.assertEqual(len(listed), len(sample), "描述清单条目数应等于 tools 参数条目数")
        self.assertIn("web_search", desc)
        self.assertIn("file_read", desc)


class TestA2VisibilityGate(unittest.TestCase):
    """A2：DEGRADED 工具从 LLM 工具面隐藏（env 门控，默认关）。"""

    def _run(self, env_val):
        import asyncio
        import os
        from neurova.context.orchestrator import ContextOrchestrator

        orch = object.__new__(ContextOrchestrator)
        evolution = MagicMock()
        evolution.on_before_tool_selection.return_value = {
            "ranking": ["ok_tool", "bad_tool"],
            "weights": {"ok_tool": 1.0, "bad_tool": 0.5},
            "filtered": [],
        }
        evolution.tool_lifecycle.get_state.side_effect = lambda n: (
            MagicMock(value="degraded") if n == "bad_tool" else MagicMock(value="active")
        )
        orch._agent = MagicMock()
        orch._agent.evolution = evolution
        # 模拟底层聚合结果（绕过 _build_tools_for_llm 的 router 依赖）
        tools = [_tool("ok_tool"), _tool("bad_tool")]

        env = {"NEUROVA_HIDE_DEGRADED_TOOLS": env_val} if env_val is not None else {}
        with patch.dict(os.environ, env, clear=False):
            if env_val is None:
                os.environ.pop("NEUROVA_HIDE_DEGRADED_TOOLS", None)
            return asyncio.run(orch._apply_visibility_gate(tools))

    def test_default_off(self):
        """默认（env 未设）：零行为变化。"""
        names = [t["function"]["name"] for t in self._run(None)]
        self.assertEqual(sorted(names), ["bad_tool", "ok_tool"])

    def test_env_on_hides_degraded(self):
        names = [t["function"]["name"] for t in self._run("1")]
        self.assertEqual(names, ["ok_tool"])

    def test_gate_tolerates_missing_evolution(self):
        import asyncio
        from neurova.context.orchestrator import ContextOrchestrator

        orch = object.__new__(ContextOrchestrator)
        orch._agent = MagicMock()
        orch._agent.evolution = None
        tools = [_tool("t")]
        out = asyncio.run(orch._apply_visibility_gate(tools))
        self.assertEqual(len(out), 1)


class TestA4CharBudget(unittest.TestCase):
    """A4：描述清单字符预算降级渲染。"""

    def _render(self, tools, budget):
        from neurova.context.orchestrator import render_tools_description

        return render_tools_description(tools, max_chars=budget)

    def test_within_budget_full_render(self):
        tools = [_tool("a", "short")]
        desc = self._render(tools, 18000)
        self.assertIn("**a**", desc)
        self.assertIn("short", desc)

    def test_over_budget_drops_params_first(self):
        """超预算：先去参数段，仍超再截断 description，总量不超预算。"""
        tools = [
            _tool(
                f"tool_{i}",
                "x" * 400,
                {"type": "object", "properties": {f"p{j}": {"type": "string"} for j in range(10)}, "required": []},
            )
            for i in range(60)
        ]
        desc = self._render(tools, 12000)
        self.assertLessEqual(len(desc), 12000)
        self.assertIn("tool_0", desc)  # 名字保留

    def test_budget_floor_keeps_all_names(self):
        """预算极小时仍保留全部工具名（只截描述，不删条目）。"""
        tools = [_tool(f"t{i}", "y" * 500) for i in range(5)]
        desc = self._render(tools, 600)
        for i in range(5):
            self.assertIn(f"t{i}", desc)


if __name__ == "__main__":
    unittest.main()
