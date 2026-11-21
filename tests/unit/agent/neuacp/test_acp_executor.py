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


def test_chunkStreamsWhilePermissionPending():
    """M9：权限等待期间泵线程不被阻塞——裁决前的正文 chunk 应先于裁决到达。

    旧契约下权限处理器在泵线程同步等人审，agent 紧随权限请求之后发出的
    帧全部滞留；新契约下处理器先返回、裁决走工作线程，chunk 即时派发。
    注意：事件循环线程上不得用阻塞 Event.wait（会饿死同循环的 prompt 任务），
    一律 async 轮询。
    """
    import threading
    import time

    async def run():
        executor, ctx, _ = makeExecutor("acp_permission_then_chunk")
        askEntered = threading.Event()
        releaseAsk = threading.Event()

        def slow_asker(action, reason, context):
            askEntered.set()
            releaseAsk.wait(10)
            return {"approved": False}

        await executor.start(ctx)
        chunks = []
        promptTask = asyncio.create_task(executor.prompt(
            "改配置", lambda kind, text: chunks.append((kind, text)), slow_asker))
        deadline = time.time() + 10
        while not askEntered.is_set() and time.time() < deadline:
            await asyncio.sleep(0.05)
        assert askEntered.is_set(), "权限请求未到达裁决器"
        while not any("裁决等待期间" in text for _, text in chunks) and time.time() < deadline:
            await asyncio.sleep(0.05)
        assert any("裁决等待期间" in text for _, text in chunks), "权限等待期间泵线程必须继续派发帧（chunk 先于裁决到达）"
        releaseAsk.set()
        result = await promptTask
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("content", "权限被拒，任务中止") in chunks
    assert result.stop_reason == "end_of_turn"


