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


# ---------- F3 保真（拍板 D-B）与帧留痕钩子（设计文档 §3.2/§3.3） ----------

def test_missingResultFrameFailsHonestly():
    """无 result 帧 = runtime 未报告结果 = 诚实失败，不得拼接累积 chunk 冒充。"""
    from neurova.agent.neuacp.acp_client import NeuacpError

    async def run():
        executor, ctx = makeExecutor("no_result")
        await executor.start(ctx)
        return await executor.prompt("任务", lambda kind, text: None, None)

    with pytest.raises(NeuacpError, match="without result frame"):
        asyncio.run(run())


def test_resultFrameBackfillsRawRedacted():
    """result 帧在场时，raw 回填脱敏后的帧原文（不再恒 None）。"""
    async def run():
        executor, ctx = makeExecutor("ok")
        await executor.start(ctx)
        result = await executor.prompt("任务", lambda kind, text: None, None)
        await executor.close()
        return result

    result = asyncio.run(run())
    assert isinstance(result.raw, dict)
    assert result.raw["type"] == "result"
    assert result.raw["result"] == "答案正文"


def test_frameHooksRecordArgvInAndObserved():
    """spawn 后 out(argv)、行循环 in(逐帧)、wait 后 observed(exited) 依次落帧账本。"""
    from neurova.agent.neuacp.frame_log import readFrames

    async def run():
        executor, ctx = makeExecutor("ok")
        ctx.metadata = {"subagent_id": "sw_plugin_frames2"}
        await executor.start(ctx)
        result = await executor.prompt("任务", lambda kind, text: None, None)
        await executor.close()
        return result

    result = asyncio.run(run())
    assert result.text == "答案正文"
    records = readFrames("sw_plugin_frames2")
    directions = [r["direction"] for r in records]
    assert directions == ["out", "in", "in", "in", "observed"], f"帧序不符：{directions}"
    assert records[0]["frame"]["type"] == "argv"
    assert "--prompt" in records[0]["frame"]["command"]
    in_types = [r["frame"].get("type") for r in records[1:4]]
    assert in_types == ["system", "assistant", "result"]
    observed = records[-1]["frame"]
    assert observed["type"] == "exited"
    assert isinstance(observed.get("exit_code"), int)
    seqs = [r["seq"] for r in records]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_frameHooksSilentWithoutSubagentId():
    """metadata 无 subagent_id（无主会话）不落帧。"""
    from pathlib import Path

    from neurova.core.data_root import dataPath

    runs_dir = Path(dataPath("swarm_runs"))
    before = {p.name for p in runs_dir.glob("*.frames.jsonl")} if runs_dir.exists() else set()

    async def run():
        executor, ctx = makeExecutor("ok")
        ctx.metadata = {}
        await executor.start(ctx)
        await executor.prompt("任务", lambda kind, text: None, None)
        await executor.close()

    asyncio.run(run())
    after = {p.name for p in runs_dir.glob("*.frames.jsonl")} if runs_dir.exists() else set()
    assert after == before, "无主会话不得新增任何帧账本文件"
