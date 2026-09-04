"""P2 四项契约测试（A6 Tool Search / B4 command-dispatch / E3 MCP 授权 / D3 升级车道）。

A6：目录压缩（direct 保留+隐藏目录+控制工具）、BM25 排序、控制工具执行拦截
   （tool_call 解包走完整执行管道、tool_search/tool_describe 读活动目录）。
B4：/技能名 → 直达映射工具（env 门控，默认关；未声明映射照常走 LLM）。
E3：mcp.{server}.{tool} 授权铸造/命中短路/非 MCP 不铸造。
D3：回溯型提问+首查无强命中 → 深检索合并去重；非回溯/强命中不升级。
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _tool(name, desc="d"):
    return {
        "type": "function",
        "function": {"name": name, "description": desc,
                     "parameters": {"type": "object", "properties": {}, "required": []}},
    }


class TestA6ToolSearch(unittest.TestCase):
    def test_compaction_requires_min_catalog(self):
        from neurova.context.tool_search import apply_tool_search_compaction

        tools = [_tool(f"t{i}") for i in range(10)]
        self.assertIsNone(apply_tool_search_compaction(tools, ["t0"], min_catalog=40))

    def test_compaction_keeps_direct_and_controls(self):
        from neurova.context.tool_search import apply_tool_search_compaction, get_active_catalog

        tools = [_tool("core_one"), _tool("core_two")] + [
            _tool(f"mcp.srv{i}.op", f"capability {i}") for i in range(45)
        ]
        out = apply_tool_search_compaction(tools, ["core_one", "core_two"], min_catalog=40)
        names = [t["function"]["name"] for t in out]
        self.assertIn("core_one", names)
        self.assertIn("core_two", names)
        for c in ("tool_search", "tool_describe", "tool_call"):
            self.assertIn(c, names)
        self.assertNotIn("mcp.srv3.op", names)
        self.assertEqual(len(get_active_catalog()), 45)

    def test_bm25_ranks_relevant_first(self):
        from neurova.context.tool_search import build_catalog, search_catalog

        tools = [_tool("weather", "current weather and forecasts"),
                 _tool("file_read", "read a file from disk"),
                 _tool("web_search", "search the web for information")]
        entries = build_catalog(tools)
        hits = search_catalog("check the weather", entries, limit=2)
        self.assertEqual(hits[0]["name"], "weather")

    def test_executor_intercepts_control_tools(self):
        """tool_call 解包真实执行；tool_search 读目录；目录外工具拒绝。"""
        from neurova.tool_executor import ToolExecutor
        from neurova.context import tool_search as ts

        executor = object.__new__(ToolExecutor)
        calls = []

        async def _fake_single(name, params, skip_governance=False):
            calls.append(name)
            return {"ok": True, "tool": name}

        executor._execute_single_tool = _fake_single

        with patch.object(ts, "_ACTIVE_CATALOG", [
            {"name": "mcp.s1.op", "description": "d", "schema": _tool("mcp.s1.op"), "params_text": ""}
        ]):
            out = asyncio.run(executor.execute("tool_call", {"name": "mcp.s1.op", "arguments": {"a": 1}}))
            self.assertEqual(out["tool"], "mcp.s1.op")
            self.assertEqual(calls, ["mcp.s1.op"])

            out = asyncio.run(executor.execute("tool_search", {"query": "op"}))
            self.assertIn("results", out)

            out = asyncio.run(executor.execute("tool_describe", {"name": "mcp.s1.op"}))
            self.assertIn("schema", out)

            out = asyncio.run(executor.execute("tool_call", {"name": "not_in_catalog"}))
            self.assertIn("error", out)

    def test_directory_never_exceeds_budget(self):
        from neurova.context.tool_search import build_catalog, render_directory

        entries = build_catalog([_tool(f"t{i}", "x" * 200) for i in range(200)])
        d = render_directory(entries, max_chars=5000)
        self.assertLessEqual(len(d), 5000 + 120)


class TestB4CommandDispatch(unittest.TestCase):
    def _pipeline(self, skill_cfg, user_input="/deploy prod"):
        from neurova.agent.chat_pipeline import ChatPipeline

        p = object.__new__(ChatPipeline)
        agent = MagicMock()
        registry = MagicMock()
        skill = MagicMock()
        skill.config = skill_cfg
        registry.has_skill.return_value = True
        registry.skills = {"deploy": (skill, None)}
        agent._skill_registry = registry
        agent._current_user_input = user_input
        p._agent = agent
        agent.tool_executor = MagicMock()
        agent.tool_executor.execute = AsyncMock(return_value={"result": "deployed"})

        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input=user_input)
        return p, ctx

    def test_disabled_by_default(self):
        p, ctx = self._pipeline({"command_dispatch": {"tool": "computer_shell"}})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEUROVA_SKILL_COMMAND_DISPATCH", None)
            asyncio.run(p._check_command_dispatch(ctx))
        p.tool_executor.execute.assert_not_called()
        self.assertFalse(getattr(p, "_command_dispatch_replied", False))

    def test_dispatch_direct_executes_and_flags(self):
        p, ctx = self._pipeline(
            {"command_dispatch": {"tool": "computer_shell", "params": {"cwd": "/x"}}},
            "/deploy prod",
        )
        # registry skills 键用 / 后的技能名
        p._agent._skill_registry.skills = {"deploy": p._agent._skill_registry.skills["deploy"]}
        with patch.dict(os.environ, {"NEUROVA_SKILL_COMMAND_DISPATCH": "1"}):
            asyncio.run(p._check_command_dispatch(ctx))
        p.tool_executor.execute.assert_called_once()
        args = p.tool_executor.execute.call_args
        self.assertEqual(args[0][0], "computer_shell")
        self.assertEqual(args[0][1].get("input"), "prod")
        # 第二遍审计：标志改为 ctx 轮次态（实例标志会在异常路径跨轮滞留）
        self.assertTrue(ctx.metadata.get("command_dispatched"))
        self.assertIn("命令分发", ctx.reply)

    def test_skill_without_dispatch_falls_through(self):
        p, ctx = self._pipeline({}, "/deploy prod")
        p._agent._skill_registry.skills = {"deploy": p._agent._skill_registry.skills["deploy"]}
        with patch.dict(os.environ, {"NEUROVA_SKILL_COMMAND_DISPATCH": "1"}):
            asyncio.run(p._check_command_dispatch(ctx))
        p.tool_executor.execute.assert_not_called()


class TestE3McpGrants(unittest.TestCase):
    def test_grant_lifecycle(self):
        from neurova.security.mcp_grants import reset_tool_grant_store

        reset_tool_grant_store()
        with tempfile.TemporaryDirectory() as td:
            from neurova.security import mcp_grants

            store = mcp_grants.ToolGrantStore(str(Path(td) / "g.json"))
            self.assertFalse(store.has_grant("srv", "op"))
            store.mint_grant("srv", "op", approved_by="u1")
            self.assertTrue(store.has_grant("srv", "op"))
            # 幂等
            store.mint_grant("srv", "op")
            self.assertEqual(len(store.list_grants()), 1)
            # 持久化（新实例可读）
            store2 = mcp_grants.ToolGrantStore(str(Path(td) / "g.json"))
            self.assertTrue(store2.has_grant("srv", "op"))
            store.revoke_grant("srv", "op")
            self.assertFalse(store.has_grant("srv", "op"))

    def test_parse_mcp_name(self):
        from neurova.security.mcp_grants import parse_mcp_tool_name

        self.assertEqual(parse_mcp_tool_name("mcp.s1.op"), ("s1", "op"))
        self.assertIsNone(parse_mcp_tool_name("web_search"))
        self.assertIsNone(parse_mcp_tool_name("mcp.s1"))

    def test_executor_grant_short_circuits_governance(self):
        """授权命中 → 跳过治理预检（直达执行）；未命中 → 正常预检。"""
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        executor._builtin_param_names = MagicMock(return_value={})
        executor._agent = MagicMock()
        executor._agent._current_user_input = ""

        async def _core(name, params, timeout=None):
            return ({"ok": True}, True, "builtin")

        executor.tool_coordinator = MagicMock()
        executor.tool_coordinator.run_with_timeout = AsyncMock(side_effect=_core)
        executor.on_tool_executed = MagicMock()

        async def _precheck(name, params):
            return {"error": "需要审批", "pending_approval": True}

        executor._governance_precheck = _precheck

        with tempfile.TemporaryDirectory() as td:
            from neurova.security import mcp_grants

            with patch.object(mcp_grants, "_store", mcp_grants.ToolGrantStore(str(Path(td) / "g.json"))):
                store = mcp_grants.get_tool_grant_store()
                store.mint_grant("s1", "op", approved_by="u")

                out = asyncio.run(executor.execute("mcp.s1.op", {}))
                self.assertEqual(out.get("ok"), True)

                out2 = asyncio.run(executor.execute("mcp.s2.other", {}))
                self.assertIn("pending_approval", out2)

    def test_approve_endpoint_mints_grant(self):
        """审批 approve + remember + MCP 工具 → 铸造授权。"""
        source = Path("neurova/api/endpoints/governance.py").read_text(encoding="utf-8")
        self.assertIn("mint_grant", source)
        self.assertIn('startswith("mcp.")', source)


class TestD3ActiveMemoryEscalation(unittest.TestCase):
    def _result(self, quality, memories):
        # D3 回滚用 dataclasses.replace —— 必须是真实 dataclass（与 RetrievalResult 同构）
        from dataclasses import dataclass, field

        @dataclass
        class _R:
            memories: list
            quality: float
            quality_level: object
            source: str = "test"

        return _R(memories=memories, quality=quality, quality_level=type("L", (), {"value": "medium"})())

    def _run(self, first_quality, user_input, deep_memories):
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.agent.chat_pipeline import _is_past_seeking

        p = object.__new__(ChatPipeline)
        p._memory_key = lambda m: str(m)
        agent = MagicMock()
        agent.config.agent_id = "default"
        p._agent = agent
        p._memory_retrieval_chain = MagicMock()
        p._memory_retrieval_chain.retrieve = AsyncMock(
            return_value=self._result(0.8, deep_memories)
        )

        from types import SimpleNamespace as SN

        ctx = SN(user_input=user_input, session_id="s", trace_id=None)
        first = self._result(first_quality, ["existing"])

        with patch.dict(os.environ, {"NEUROVA_ACTIVE_MEMORY": "1"}):
            return asyncio.run(p._active_memory_escalation(ctx, first, "default")), _is_past_seeking(user_input)

    def test_past_seeking_low_quality_escalates(self):
        out, seeking = self._run(0.2, "我们上次聊了什么？", ["deep_hit_1"])
        self.assertTrue(seeking)
        self.assertIn("deep_hit_1", out.memories)
        self.assertEqual(len(out.memories), 2)

    def test_strong_hit_no_escalation(self):
        out, _ = self._run(0.9, "我们上次聊了什么？", ["deep_hit_1"])
        self.assertEqual(out.memories, ["existing"])

    def test_not_past_seeking_no_escalation(self):
        out, seeking = self._run(0.2, "今天天气怎么样", ["deep_hit_1"])
        self.assertFalse(seeking)
        self.assertEqual(out.memories, ["existing"])


if __name__ == "__main__":
    unittest.main()

class TestClosureAudit(unittest.TestCase):
    """闭环审计（全批改动跨交互复核）补遗契约。"""

    def test_a6_directory_not_duplicated_in_markdown(self):
        """A6×A4 交互：目录伪条目只出现在 tools 参数，markdown 渲染跳过。"""
        from neurova.context.orchestrator import render_tools_description
        from neurova.context.tool_search import build_catalog, render_directory

        entries = build_catalog([
            {"type": "function", "function": {"name": f"mcp.s{i}.op",
             "description": f"capability {i} — operation", "parameters": {}}}
            for i in range(120)
        ])
        directory = render_directory(entries, max_chars=18000)
        tools = [
            _tool("memory_search", "mem"),
            _tool("tool_search", "search"),
            {"type": "function", "function": {
                "name": "tool_search_directory",
                "description": "隐藏目录 " + directory,
                "parameters": {"type": "object", "properties": {}, "required": []}}},
        ]
        md = render_tools_description(tools)  # 默认 18000 预算
        self.assertNotIn("tool_search_directory", md, "目录伪条目不得进 markdown（双份注入）")
        self.assertNotIn("capability 119", md)
        # 直连工具仍完整渲染
        self.assertIn("memory_search", md)

    def test_b4_dispatch_prevents_double_execution(self):
        """B4×肌肉记忆交互：命令分发后同一输入不再触发肌肉记忆自动执行。"""
        p, ctx = TestB4CommandDispatch()._pipeline(
            {"command_dispatch": {"tool": "computer_shell"}},
            "/deploy prod",
        )
        p._agent._skill_registry.skills = {"deploy": p._agent._skill_registry.skills["deploy"]}
        p._agent.tool_memory = MagicMock()
        p._agent.tool_memory.check_tool_memory.return_value = (
            {"tool_name": "computer_shell"}, "auto_execute"
        )
        with patch.dict(os.environ, {"NEUROVA_SKILL_COMMAND_DISPATCH": "1"}):
            asyncio.run(p._check_command_dispatch(ctx))
            self.assertTrue(ctx.metadata.get("command_dispatched"))
            asyncio.run(p._check_tool_memory(ctx))
        # 肌肉记忆检查被跳过（不会二次执行）
        p.tool_memory.check_tool_memory.assert_not_called()
