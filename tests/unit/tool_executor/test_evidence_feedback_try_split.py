# -*- coding: utf-8 -*-
"""P2-10 tool_executor 证据落账与反馈链 try 拆分红测（全库断点审计 2026-11-12）。

缺陷：execute_tool 的 finally 里 `record_tool_execution`（证据落账）与
`on_tool_executed`（进化权重/元认知事件/指标/能力缺口的单一咽喉）共享同一个
try——落账抛异常（如 deepcopy 失败）时反馈链整体跳过，与 H5 注释
"所有路径统一触发"自相矛盾。

修复口径（审计开方）：拆两个 try，各记各的堆栈，互不拖累。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_try_split")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_try_split")

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def executor():
    from neurova.tool_executor import ToolExecutor

    agent = MagicMock()
    agent._current_user_input = "hi"
    return ToolExecutor(agent)


@pytest.mark.asyncio
async def test_ledger_failure_does_not_skip_feedback_hook(executor, monkeypatch):
    import neurova.skills.creation_governance as cg

    def _boom(*a, **k):
        raise RuntimeError("deepcopy 失败（模拟证据落账异常）")

    monkeypatch.setattr(cg, "record_tool_execution", _boom)

    calls = []
    executor.on_tool_executed = lambda **kw: calls.append(kw)

    async def _core(tool_name, params):
        return {"ok": True}, True, "builtin"

    executor._execute_tool_core = _core

    result = await executor.execute_tool("some_tool", {"x": 1}, user_input="hi")

    assert result, "工具结果不应被落账异常吞掉"
    assert len(calls) == 1, (
        f"证据落账抛异常时 on_tool_executed 被整体跳过（P2-10）：calls={calls}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
