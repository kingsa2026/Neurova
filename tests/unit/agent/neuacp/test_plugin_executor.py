# -*- coding: utf-8 -*-
"""A8 红灯：NeuacpPluginExecutor（插件形态，ZCode 首个落地）契约测试。

覆盖：--prompt 注入、NDJSON 事件流映射（assistant→content、thinking→
reasoning、result→结果文本）、未知行容错、非零退出判失败、close 幂等。
"""
import asyncio
import sys
from pathlib import Path

import pytest

from neurova.agent.neuacp.executor import NeuacpSessionContext
from neurova.agent.neuacp.plugin_executor import NeuacpPluginExecutor

FAKE_CLI = Path(__file__).with_name("fake_zcode_cli.py")


def makeExecutor(mode="ok", **kwargs):
    executor = NeuacpPluginExecutor(
        [sys.executable, str(FAKE_CLI)],
        cwd=str(FAKE_CLI.parent),
        env_extra={"FAKE_ZCODE_MODE": mode},
        **kwargs,
    )
    ctx = NeuacpSessionContext(member_session_id="m-1", task_text="修个 bug", cwd=str(FAKE_CLI.parent))
    return executor, ctx


def test_promptStreamsChunksAndReturnsResultText():
    async def run():
        executor, ctx = makeExecutor("ok")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("修个 bug", lambda kind, text: chunks.append((kind, text)), None)
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("content", "答案正文") in chunks
    assert result.text == "答案正文"
    assert result.stop_reason == "end_of_turn"


def test_thinkingBlockMapsToReasoning():
    async def run():
        executor, ctx = makeExecutor("thinking")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("任务", lambda kind, text: chunks.append((kind, text)), None)
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("reasoning", "先想一下") in chunks
    assert ("content", "答案正文") in chunks
    assert result.text == "答案正文"


def test_nonZeroExitMarksFailure():
    async def run():
        executor, ctx = makeExecutor("fail")
        await executor.start(ctx)
        return await executor.prompt("任务", lambda kind, text: None, None)

    with pytest.raises(Exception):
        asyncio.run(run())


def test_garbageLinesTolerated():
    async def run():
        executor, ctx = makeExecutor("garbage")
        await executor.start(ctx)
        result = await executor.prompt("任务", lambda kind, text: None, None)
        await executor.close()
        return result

    result = asyncio.run(run())
    assert result.text == "答案正文"


def test_closeIsIdempotent():
    async def run():
        executor, ctx = makeExecutor("ok")
        await executor.start(ctx)
        await executor.prompt("任务", lambda kind, text: None, None)
        await executor.close()
        await executor.close()

    asyncio.run(run())
