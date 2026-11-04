"""N2：sync_nodes 工具让新注册的技能/自定义节点立即可用。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.tool_executor import ToolExecutor


def _executor():
    agent = SimpleNamespace(
        _current_user_id="u1",
        config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
    )
    return ToolExecutor(agent)


class _FakeRegistry:
    def __init__(self):
        self.synced = 0

    def sync_all(self):
        self.synced += 1
        return {"tools": 1, "skills": 2, "mcp": 0, "custom": 1}

    def list_all(self):
        return [object(), object(), object(), object()]


class TestSyncNodesTool:
    def test_schemaAndDispatchRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_capability

        assert "sync_nodes" in _BUILTIN_SCHEMAS
        assert ToolExecutor._builtin_dispatch.get("sync_nodes") == "_execute_sync_nodes"
        cap = get_builtin_tool_capability("sync_nodes")
        assert cap is not None and cap.readOnly is False

    @pytest.mark.asyncio
    async def test_syncAllCallsRegistryAndReportsCounts(self, monkeypatch):
        fake = _FakeRegistry()
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.node_registry.get_node_registry",
            lambda: fake,
        )
        result = await _executor()._execute_builtin_tool("sync_nodes", {"scope": "all"})
        assert result["success"] is True
        assert result["counts"]["skills"] == 2
        assert result["registered"] == 4
        assert fake.synced == 1

    @pytest.mark.asyncio
    async def test_unknownScopeIsRejected(self):
        result = await _executor()._execute_builtin_tool(
            "sync_nodes", {"scope": "no_such_scope"}
        )
        assert result["success"] is False
        assert "未知同步范围" in result["error"]
