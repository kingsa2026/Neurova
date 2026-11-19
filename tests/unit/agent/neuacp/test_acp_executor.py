# -*- coding: utf-8 -*-
"""A2 红灯：NeuacpStdioExecutor 契约测试。

覆盖：session/new→prompt 事件流映射（content/reasoning→emitter）、
结果文本累积、cancelled 停止原因、session/request_permission 往返
（allow/deny 两路）。
"""
import asyncio
import sys
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.executor import NeuacpSessionContext

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


def makeExecutor(mode, on_permission=None):
    tool_events = []
    executor = NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": mode},
        on_tool_call=lambda update: tool_events.append(update),
    )
    ctx = NeuacpSessionContext(member_session_id="m-1", task_text="写个登录页", cwd=str(FAKE_AGENT.parent))
    return executor, ctx, tool_events


def test_promptStreamsChunksAndReturnsText():
    async def run():
        executor, ctx, _ = makeExecutor("acp_flow")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), None)
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert chunks == [("content", "你好 Neuacp"), ("reasoning", "思考中")]
    assert result.text == "你好 Neuacp"
    assert result.stop_reason == "end_of_turn"


def test_promptCancelledStopReason():
    async def run():
        executor, ctx, _ = makeExecutor("acp_cancelled")
        await executor.start(ctx)
        result = await executor.prompt("写个登录页", lambda kind, text: None, None)
        await executor.close()
        return result

    result = asyncio.run(run())
    assert result.stop_reason == "cancelled"
    assert result.text == ""


def test_permissionAllowRoundTrip():
    async def run():
        asks = []

        def on_permission(action, reason, context):
            asks.append((action, reason, context))
            return {"approved": True}

        executor, ctx, _ = makeExecutor("acp_permission", on_permission=on_permission)
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("改配置", lambda kind, text: chunks.append((kind, text)), on_permission)
        await executor.close()
        return asks, chunks, result

    asks, chunks, result = asyncio.run(run())
    assert len(asks) == 1
    assert "写入 src/app.py" in asks[0][0]
    assert ("content", "你好 Neuacp") in chunks
    assert result.stop_reason == "end_of_turn"


def test_permissionDenyStopsTask():
    async def run():
        executor, ctx, _ = makeExecutor("acp_permission")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("改配置", lambda kind, text: chunks.append((kind, text)), lambda a, r, c: {"approved": False})
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("content", "权限被拒，任务中止") in chunks
    assert result.stop_reason == "end_of_turn"


def test_closeIsIdempotent():
    async def run():
        executor, ctx, _ = makeExecutor("acp_flow")
        await executor.start(ctx)
        await executor.close()
        await executor.close()

    asyncio.run(run())
