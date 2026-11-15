# -*- coding: utf-8 -*-
"""P1（蜂群对照）：子代理工具面收窄。

- spawn 的 subagent_type 决定 member 任务的工具面白名单：
  general = 全量内置 − 递归派生；explore = 只读白名单；
- 执行咽喉对白名单外工具结构化拒绝（先于治理/审批，不可 bypass）；
- 主 Agent（未收窄）不受影响。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.swarm import (
    SUBAGENT_RUNNING,
    computeSubagentToolAllowlist,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.core.turn_context import (
    get_subagent_tool_allowlist,
    set_subagent_tool_allowlist,
    set_turn_identity,
)
from neurova.tool_executor import ToolExecutor

MEMBER_SESSION = "member-s2"


@pytest.fixture
def swarm(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "sched.json"))
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


@pytest.fixture
def executor():
    return ToolExecutor(MagicMock())


class TestAllowlistComputation:
    def test_explore_is_readonly_whitelist(self):
        allowlist = computeSubagentToolAllowlist("explore")
        assert "file_read" in allowlist
        assert "web_search" in allowlist
        assert "file_write" not in allowlist
        assert "computer_shell" not in allowlist
        assert "spawn_subagent" not in allowlist

    def test_general_excludes_recursive_spawn(self):
        allowlist = computeSubagentToolAllowlist("general")
        assert "file_write" in allowlist
        assert "spawn_subagent" not in allowlist

    def test_unknown_type_falls_back_to_general(self):
        allowlist = computeSubagentToolAllowlist("bogus")
        assert "spawn_subagent" not in allowlist


class TestSpawnRecordsTypeAndAllowlist:
    def test_background_spawn_records_type_and_allowlist(self, swarm, monkeypatch):
        monkeypatch.setattr(
            "neurova.security.governance_settings.load_governance_settings", lambda: {}
        )
        monkeypatch.setattr(swarm, "_resolve_agent", lambda agent_id: (MagicMock(), "child-agent", False))
        result = asyncio.run(
            ToolExecutor(MagicMock())._execute_spawn_subagent(
                {"task": "子任务", "subagent_type": "explore", "background": True}
            )
        )
        run = swarm._runs[result["subagent_id"]]
        assert run.subagent_type == "explore"
        assert "file_write" not in run.tool_allowlist
        assert run.to_dict()["subagent_type"] == "explore"


class TestEnforcement:
    def test_explore_allowlist_blocks_write(self):
        set_subagent_tool_allowlist(frozenset({"file_read", "web_search"}))
        set_turn_identity("子任务", MEMBER_SESSION)
        try:
            result = asyncio.run(_executor()._execute_single_tool("file_write", {"x": 1}))
            assert result["code"] == "subagent_tool_not_allowed"
            assert "file_write" in result["error"]
        finally:
            set_subagent_tool_allowlist(None)
            set_turn_identity("cleared", None)

    def test_allowed_tool_still_executes(self):
        set_subagent_tool_allowlist(frozenset({"get_datetime"}))
        set_turn_identity("子任务", MEMBER_SESSION)
        try:
            result = asyncio.run(_executor()._execute_single_tool("get_datetime", {}))
            # 面内只读工具不触发面边界拒绝（其余结果取决于工具自身执行）
            assert result.get("code") != "subagent_tool_not_allowed"
        finally:
            set_subagent_tool_allowlist(None)
            set_turn_identity("cleared", None)

    def test_general_child_cannot_spawn_grandchild(self):
        set_subagent_tool_allowlist(computeSubagentToolAllowlist("general"))
        set_turn_identity("子任务", MEMBER_SESSION)
        try:
            result = asyncio.run(_executor()._execute_single_tool("spawn_subagent", {"task": "x"}))
            assert result["code"] == "subagent_tool_not_allowed"
        finally:
            set_subagent_tool_allowlist(None)
            set_turn_identity("cleared", None)

    def test_skip_governance_does_not_bypass_allowlist(self):
        set_subagent_tool_allowlist(frozenset({"file_read"}))
        set_turn_identity("子任务", MEMBER_SESSION)
        try:
            result = asyncio.run(
                ToolExecutor(MagicMock())._execute_single_tool(
                    "file_write", {"x": 1}, skip_governance=True
                )
            )
            assert result["code"] == "subagent_tool_not_allowed"
        finally:
            set_subagent_tool_allowlist(None)
            set_turn_identity("cleared", None)

    def test_parent_without_allowlist_unaffected(self):
        set_turn_identity("任务", "parent-session")
        try:
            result = asyncio.run(
                _executor()._execute_single_tool("file_write", {"x": 1}, skip_governance=True)
            )
            # 主 Agent 未收窄：不出现面边界拒绝（其余结果取决于治理/执行，不在此钉）
            assert result.get("code") != "subagent_tool_not_allowed"
        finally:
            set_turn_identity("cleared", None)


def _executor():
    return ToolExecutor(MagicMock())


class TestMcpBorrow:
    """P3（蜂群对照 #8）：general 型借用父上下文 MCP 调用面；explore 不借"""

    def test_general_allowlist_unions_borrowed_mcp(self):
        import neurova.agent.swarm as swarm_mod

        borrowed = frozenset({"mcp.s1.search", "search"})
        monkeyborrowed = swarm_mod.computeSubagentToolAllowlist("general", borrowMcp=borrowed)
        assert "mcp.s1.search" in monkeyborrowed
        assert "search" in monkeyborrowed
        # 递归派生/续跑仍排除
        assert "spawn_subagent" not in monkeyborrowed
        assert "continue_subagent" not in monkeyborrowed

    def test_explore_never_borrows_mcp(self):
        allow = computeSubagentToolAllowlist("explore", borrowMcp=frozenset({"mcp.s1.search"}))
        assert "mcp.s1.search" not in allow

    def test_borrow_names_use_namespaced_and_bare_forms(self, monkeypatch):
        import neurova.tool_layers.mcp_client as mcp_mod
        from neurova.agent.swarm import mcpBorrowedToolNames

        class FakeClient:
            def list_tools(self):
                return [
                    {"name": "search", "server_id": "s1"},
                    {"name": "bare_tool"},
                ]

        monkeypatch.setattr(mcp_mod, "get_mcp_client", lambda *a, **k: FakeClient())
        names = mcpBorrowedToolNames()
        assert "mcp.s1.search" in names
        assert "search" in names
        assert "bare_tool" in names

    def test_borrow_enum_failure_returns_empty(self, monkeypatch):
        import neurova.tool_layers.mcp_client as mcp_mod
        from neurova.agent.swarm import mcpBorrowedToolNames

        def boom(*a, **k):
            raise RuntimeError("mcp down")

        monkeypatch.setattr(mcp_mod, "get_mcp_client", boom)
        assert mcpBorrowedToolNames() == frozenset()

    def test_spawn_freezes_mcp_snapshot_into_run(self, swarm, monkeypatch):
        import neurova.agent.swarm as swarm_mod
        from unittest.mock import AsyncMock, patch

        monkeypatch.setattr(
            swarm_mod, "mcpBorrowedToolNames", lambda: frozenset({"mcp.s1.search"})
        )
        agent = MagicMock()
        agent.config.name = "子"
        agent.chat = AsyncMock(return_value={"text": "ok"})

        async def _go():
            with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
                return await get_swarm_manager().spawn(task="任务", agent_id="researcher")

        result = asyncio.run(_go())
        run = get_swarm_manager()._runs[result["subagent_id"]]
        # spawn 时刻的 MCP 快照冻结进 run.tool_allowlist（执行期不再重查）
        assert "mcp.s1.search" in run.tool_allowlist
