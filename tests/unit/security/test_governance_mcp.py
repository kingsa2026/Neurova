"""
P0-2 治理穿透修复红测

三个洞（评测文档 M3/M4 + fail-open，tool_executor.py / mcp_client.py）：
- M3: ToolRouter 主路径优先 call_tool（tool_router.py:532-534），而防火墙
  检查只在 execute_tool——MCP 工具执行整体绕过防火墙
- M4: _governance_precheck 只提取 command/code/file_path/path 四个约定
  键名，MCP 工具参数换任意键名即静默放行
- fail-open: 治理模块故障/评估异常时一律放行

修复语义：
- MCP 工具（mcp.* 命名空间）全参数整体扫描（scan_all=True）
- 治理不可用分级 fail-closed：MCP/未知来源 deny，内置白名单放行
- 防火墙检查移入唯一执行入口 call_tool（execute_tool 委托，不重复）
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.security.governance import (
    GovernanceDecision,
    GovernancePolicy,
    GovernanceResult,
)
import neurova.security.governance as governance_module


# ── 测试基础设施 ─────────────────────────────────────────────────


def _make_executor():
    """最小 ToolExecutor：__init__ 仅挂 _agent/_messages_list/_tool_engine"""
    from neurova.tool_executor import ToolExecutor

    agent = SimpleNamespace(
        _current_user_id="u_test",
        config=SimpleNamespace(user_id="u_test", agent_id="a_test"),
    )
    return ToolExecutor(agent)


def _fake_policy(capture: dict, decision=GovernanceDecision.ALLOW) -> GovernancePolicy:
    """跳过 __init__ 的 GovernancePolicy 壳：evaluate 记参返回固定裁决"""
    policy = GovernancePolicy.__new__(GovernancePolicy)
    policy.tool_overrides = {}

    def fake_evaluate(command, tool_name="shell", user_id=None, file_paths=None):
        capture.update(
            command=command, tool_name=tool_name,
            user_id=user_id, file_paths=file_paths,
        )
        return GovernanceResult(decision=decision, reasons=["fake"])

    policy.evaluate = fake_evaluate
    return policy


def _make_client():
    """已连接 s1 的 MCPToolClient：假会话 + 可观测防火墙"""
    from neurova.tool_layers.mcp_client import MCPToolClient

    client = MCPToolClient(user_id="u_test")
    client._servers["s1"] = {
        "config": {"transport": "http", "timeout_ms": 1000},
        "connected": True,
        "tools": [{"name": "t1", "parameters": {}}],
        "last_error": None,
        "last_connected": None,
    }
    session = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")], isError=False
        )
    )
    client._sessions["s1"] = session
    firewall = MagicMock(return_value=True)  # check_permission
    client._firewall = firewall  # 预置，绕过懒加载
    return client, session, firewall


# ── 1. evaluate_tool_call：全参数扫描入口（M4 修复核心） ──────────


class TestEvaluateToolCall:
    def test_scan_all_reaches_evaluate_with_full_content(self):
        """scan_all=True：任意键名的参数值必须整体进入裁决文本"""
        policy = GovernancePolicy.__new__(GovernancePolicy)
        capture = {}
        policy.evaluate = lambda command, tool_name="shell", user_id=None, file_paths=None: (
            capture.update(command=command, tool_name=tool_name, file_paths=file_paths),
            GovernanceResult(decision=GovernanceDecision.ALLOW),
        )[1]
        verdict = policy.evaluate_tool_call("mcp.s1.t", {"exec": "rm -rf /"}, scan_all=True)
        assert verdict.decision == GovernanceDecision.ALLOW
        assert "rm -rf /" in capture["command"]
        assert capture["tool_name"] == "mcp.s1.t"

    def test_scan_all_extracts_path_like_param(self):
        policy = GovernancePolicy.__new__(GovernancePolicy)
        capture = {}
        policy.evaluate = lambda command, tool_name="shell", user_id=None, file_paths=None: (
            capture.update(file_paths=file_paths),
            GovernanceResult(decision=GovernanceDecision.ALLOW),
        )[1]
        policy.evaluate_tool_call(
            "mcp.s1.fs", {"target": "C:/Users/x/secret.txt", "mode": "read"}, scan_all=True
        )
        assert capture["file_paths"] == "C:/Users/x/secret.txt"

    def test_empty_params_returns_none(self):
        policy = GovernancePolicy.__new__(GovernancePolicy)
        policy.evaluate = MagicMock(side_effect=AssertionError("不应触发 evaluate"))
        assert policy.evaluate_tool_call("mcp.s1.t", {}, scan_all=True) is None
        assert policy.evaluate_tool_call("mcp.s1.t", {}, scan_all=False) is None

    def test_non_mcp_extraction_contract_unchanged(self):
        """非 scan_all 保持原四键名语义：exec 等其他键不进裁决文本"""
        policy = GovernancePolicy.__new__(GovernancePolicy)
        capture = {}
        policy.evaluate = lambda command, tool_name="shell", user_id=None, file_paths=None: (
            capture.update(command=command, file_paths=file_paths),
            GovernanceResult(decision=GovernanceDecision.ALLOW),
        )[1]
        policy.evaluate_tool_call(
            "bash", {"command": "ls -la", "file_path": "/tmp/a", "exec": "injected"},
            scan_all=False,
        )
        assert capture["command"] == "ls -la"
        assert capture["file_paths"] == "/tmp/a"
        assert "injected" not in capture["command"]


# ── 2. 预检接线：MCP 走 scan_all、非 MCP 无裁决内容跳过 ───────────


class TestPrecheckWiring:
    @pytest.mark.asyncio
    async def test_precheck_mcp_uses_scan_all(self, monkeypatch):
        capture = {}
        policy = _fake_policy(capture)
        monkeypatch.setattr(governance_module, "get_governance", lambda: policy)
        ex = _make_executor()
        result = await ex._governance_precheck(
            "mcp.s1.danger_tool", {"exec": "rm -rf /"}
        )
        assert result is None  # ALLOW → 放行
        assert capture["command"] and "rm -rf /" in capture["command"]
        assert capture["user_id"] == "u_test"

    @pytest.mark.asyncio
    async def test_precheck_non_mcp_unknown_key_skips(self, monkeypatch):
        """非 MCP 工具且无 command/code/file_path/path 键 → 原样放行不评估"""
        capture = {}
        policy = _fake_policy(capture)
        monkeypatch.setattr(governance_module, "get_governance", lambda: policy)
        ex = _make_executor()
        result = await ex._governance_precheck("my_dyn_tool", {"exec": "anything"})
        assert result is None
        assert capture == {}

    @pytest.mark.asyncio
    async def test_precheck_mcp_deny_blocks(self, monkeypatch):
        capture = {}
        policy = _fake_policy(capture, decision=GovernanceDecision.DENY)
        monkeypatch.setattr(governance_module, "get_governance", lambda: policy)
        ex = _make_executor()
        result = await ex._governance_precheck("mcp.s1.t", {"exec": "x"})
        assert result is not None and result.get("success") is False
        assert result.get("governance", {}).get("decision") == "deny"


# ── 3. 治理不可用：分级 fail-closed ──────────────────────────────


class TestGovernanceUnavailable:
    @pytest.mark.asyncio
    async def test_governance_down_mcp_denied(self, monkeypatch):
        monkeypatch.setattr(
            governance_module, "get_governance",
            MagicMock(side_effect=RuntimeError("governance down")),
        )
        ex = _make_executor()
        result = await ex._governance_precheck("mcp.s1.t", {"exec": "ls"})
        assert result is not None and result.get("success") is False
        assert "治理" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_governance_down_unknown_denied(self, monkeypatch):
        monkeypatch.setattr(
            governance_module, "get_governance",
            MagicMock(side_effect=RuntimeError("governance down")),
        )
        ex = _make_executor()
        result = await ex._governance_precheck("my_custom_dynamic_tool", {"input": "x"})
        assert result is not None and result.get("success") is False

    @pytest.mark.asyncio
    async def test_governance_down_builtin_allowed(self, monkeypatch):
        """内置白名单工具不因治理故障被误杀"""
        monkeypatch.setattr(
            governance_module, "get_governance",
            MagicMock(side_effect=RuntimeError("governance down")),
        )
        ex = _make_executor()
        result = await ex._governance_precheck("calculator", {"expression": "1+1"})
        assert result is None


# ── 4. 防火墙进入唯一执行入口 call_tool（M3 修复） ────────────────


class TestCallToolFirewall:
    @pytest.mark.asyncio
    async def test_call_tool_invokes_firewall(self):
        client, session, firewall = _make_client()
        await client.call_tool("s1", "t1", {"a": 1})
        firewall.check_permission.assert_called_once_with("u_test", "mcp_tool", "t1")

    @pytest.mark.asyncio
    async def test_call_tool_firewall_denies(self):
        """拒绝时抛 PermissionError 且不触达服务端（router 主路径被堵死）"""
        client, session, firewall = _make_client()
        firewall.check_permission.return_value = False
        with pytest.raises(PermissionError):
            await client.call_tool("s1", "t1", {"a": 1})
        session.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_tool_firewall_checked_exactly_once(self):
        """execute_tool 委托 call_tool：校验恰好一次，不重复"""
        client, session, firewall = _make_client()
        await client.execute_tool("s1", "t1", {})
        assert firewall.check_permission.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
