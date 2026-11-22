"""U11 失败分级重试守卫（D4 升级计划）。

契约（与 tool_layers/mcp_resilience.py 分工：它管 MCP 连接级，本卡管工具调用级）：
- 仅 transport/连接级失败允许换连接/会话重试；
- 应用层失败零重试；
- 变异类工具（写/发）默认不重试，除非 schema runtime 声明 idempotent；
- 执行器公开入口对"同参重复调用"执行上述纪律：上一轮同参调用以
  不可重试形态失败后，紧随的同参调用被结构化拒绝（TOOL_RETRY_SUPPRESSED），
  不再产生第二次真实执行。

红（现网行为）：应用层失败/变异工具超时后，同参调用会再次真实执行。
绿：transport 重试保留、应用层零重试、变异工具默认不重试。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import neurova.tool_executor as tool_executor_module
from neurova.tool_executor import ToolExecutor


@pytest.fixture
def journalOff(monkeypatch):
    """关掉工具调用账本（它对同参失败调用本就回放不重跑）——
    本卡验证的是**执行器自身的重试纪律**，须在账本缺席时独立成立。"""
    monkeypatch.setenv("NEUROVA_TOOL_JOURNAL", "0")
    from neurova.core import tool_call_journal as journal_module

    journal_module.reset_tool_call_journal()
    yield
    journal_module.reset_tool_call_journal()


def _makeExecutor(monkeypatch):
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id="u1", agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    executor = ToolExecutor(agent)

    async def _noGovernance(tool_name, params):
        return None

    monkeypatch.setattr(executor, "_governance_precheck", _noGovernance)
    return executor


class TestFailureClassification:
    def test_connectionErrorIsTransport(self):
        from neurova.tool_executor import classifyToolFailure

        verdict = classifyToolFailure("web_fetch", error=ConnectionError("connection reset by peer"))
        assert verdict["failure_class"] == "transport"
        assert verdict["retry_allowed"] is True

    def test_timeoutIsTransport(self):
        from neurova.tool_executor import classifyToolFailure

        verdict = classifyToolFailure("web_fetch", error=asyncio.TimeoutError("timed out"))
        assert verdict["failure_class"] == "transport"

    def test_applicationErrorIsNotRetryable(self):
        from neurova.tool_executor import classifyToolFailure

        verdict = classifyToolFailure("file_edit", error=ValueError("未找到目标文本"))
        assert verdict["failure_class"] == "application"
        assert verdict["retry_allowed"] is False

    def test_u3NotExecutedPayloadIsTransport(self):
        """U3 契约：REMOTE_NOT_EXECUTED 且 executed=False = 确认未执行，可重试。"""
        from neurova.tool_executor import classifyToolFailure

        verdict = classifyToolFailure("computer_ssh_exec", result={
            "error_code": "REMOTE_NOT_EXECUTED", "executed": False, "retryable": True,
            "error": "连接在命令下发前中断",
        })
        assert verdict["failure_class"] == "transport"
        assert verdict["retry_allowed"] is True

    def test_u3UnknownExecutionIsNotRetryable(self):
        from neurova.tool_executor import classifyToolFailure

        verdict = classifyToolFailure("computer_ssh_exec", result={
            "error_code": "REMOTE_NOT_EXECUTED", "executed": "unknown", "retryable": False,
            "error": "已获部分输出后中断",
        })
        assert verdict["retry_allowed"] is False

    def test_mutationToolTransportFailureDefaultsToNoRetry(self):
        """变异类工具（exec_command 未声明 idempotent）：即使 transport 失败也不自动重试。"""
        from neurova.tool_executor import retryDecisionFor

        decision = retryDecisionFor("exec_command", error=ConnectionError("reset"))
        assert decision["allowed"] is False
        assert "idempotent" in decision["reason"] or "变异" in decision["reason"]

    def test_idempotentDeclaredMutationTransportFailureRetries(self):
        """声明 idempotent 的变异工具（file_write）：transport 失败保留重试。"""
        from neurova.tool_executor import retryDecisionFor

        decision = retryDecisionFor("file_write", error=ConnectionError("reset"))
        assert decision["allowed"] is True

    def test_readonlyToolTransportFailureRetries(self):
        from neurova.tool_executor import retryDecisionFor

        decision = retryDecisionFor("memory_search", error=ConnectionError("reset"))
        assert decision["allowed"] is True


class TestExecutorRetryGate:
    @pytest.mark.asyncio
    async def test_applicationFailureIsNotReExecuted(self, monkeypatch, journalOff):
        """红：应用层失败后同参调用会再次真实执行；
        绿：第二次同参调用被结构化拒绝（TOOL_RETRY_SUPPRESSED），零重试。"""
        executor = _makeExecutor(monkeypatch)
        monkeypatch.setattr(
            tool_executor_module, "get_builtin_tool_params",
            lambda name: {"type": "object"} if name == "fake_read" else None,
        )
        calls = []

        async def failingCore(tool_name, params):
            calls.append(dict(params))
            return ({"success": False, "error": "查询语法错误: near 'SELEC'"}, False, "builtin")

        monkeypatch.setattr(executor, "_execute_tool_core", failingCore)

        first = await executor.execute("fake_read", {"q": "same"})
        assert first.get("error"), first
        second = await executor.execute("fake_read", {"q": "same"})
        assert second.get("error_code") == "TOOL_RETRY_SUPPRESSED", second
        assert len(calls) == 1, f"应用层失败不得重试执行，实际执行 {len(calls)} 次"

    @pytest.mark.asyncio
    async def test_mutationToolTimeoutIsNotReExecuted(self, monkeypatch, journalOff):
        """红：变异工具（exec_command）超时形态失败后同参调用再次真实执行（双执行风险）；
        绿：重试被拒（变异工具未声明 idempotent，默认不重试）。"""
        executor = _makeExecutor(monkeypatch)
        calls = []

        async def timingOutCore(tool_name, params):
            calls.append(dict(params))
            return (
                {"success": False, "error": "工具执行超时（0.3s）", "executed": "unknown"},
                False,
                "builtin",
            )

        monkeypatch.setattr(executor, "_execute_tool_core", timingOutCore)

        await executor.execute("exec_command", {"command": "sleep 100"})
        second = await executor.execute("exec_command", {"command": "sleep 100"})
        assert second.get("error_code") == "TOOL_RETRY_SUPPRESSED", second
        assert len(calls) == 1, f"变异工具超时后不得二次执行，实际执行 {len(calls)} 次"

    @pytest.mark.asyncio
    async def test_readonlyTransportFailureRetryIsPreserved(self, monkeypatch):
        """transport 重试保留：只读工具连接级失败后，同参重试仍真实执行（换连接重试）。"""
        executor = _makeExecutor(monkeypatch)
        monkeypatch.setattr(
            tool_executor_module, "get_builtin_tool_params",
            lambda name: {"type": "object"} if name == "memory_search" else None,
        )
        calls = []

        async def transportFail(tool_name, params):
            calls.append(dict(params))
            raise ConnectionError("connection reset by peer")

        monkeypatch.setattr(executor, "_execute_tool_core", transportFail)

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await executor.execute("memory_search", {"query": "q"})
        assert len(calls) == 2, "transport 级失败的重试必须保留（不得被一刀切封锁）"

    @pytest.mark.asyncio
    async def test_suppressionIsScopedToSameParams(self, monkeypatch, journalOff):
        """抑制只作用于**同参**重试：不同参数的新调用不受牵连；
        同参的不可重试失败在抑制窗内保持拒绝。"""
        executor = _makeExecutor(monkeypatch)
        monkeypatch.setattr(
            tool_executor_module, "get_builtin_tool_params",
            lambda name: {"type": "object"} if name == "fake_tool" else None,
        )
        calls = []

        async def flakyCore(tool_name, params):
            calls.append(dict(params))
            if params.get("a") == 1:
                return ({"success": False, "error": "查询语法错误: near 'SELEC'"}, False, "builtin")
            return ({"success": True, "result": "ok"}, True, "builtin")

        monkeypatch.setattr(executor, "_execute_tool_core", flakyCore)

        first = await executor.execute("fake_tool", {"a": 1})
        assert first.get("success") is False
        blocked = await executor.execute("fake_tool", {"a": 1})
        assert blocked.get("error_code") == "TOOL_RETRY_SUPPRESSED", blocked
        # 不同参数 = 新调用，不受同参抑制影响
        ok = await executor.execute("fake_tool", {"a": 2})
        assert ok.get("success") is True, ok
        assert len(calls) == 2, "仅两次真实执行（a=1 首次 + a=2），同参重试被拦"
