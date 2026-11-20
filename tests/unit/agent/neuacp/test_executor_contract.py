# -*- coding: utf-8 -*-
"""F4 内核级同构桩契约测试（设计文档 §3.4）。

同一份剧本分别驱动 wire 桩（NeuacpStdioExecutor 挂 fake_acp_agent.py 真子进程）
与 scripted 桩（NeuacpScriptedExecutor，无子进程无二进制），断言**可观测结局
一致**：emitter 调用序列、结果 text/stop_reason 一致；双方 frames 流都含
out+in 记录（wire 侧 setFrameKey 挂点未交付则按 getattr 守卫跳过该侧断言）。

另覆盖 scripted 桩专属语义：permission deny 中止（stop_reason=cancelled）、
tool_call 送达镜像 handler、crash 诚实失败、cancel 中止 sleep、exit_code
非 0 失败、start 可重入复位、帧写入 fail-open（frame_log 并行交付期缺席
不阻断执行）。

数据根隔离：沿用 tests/conftest.py 的会话级 NEUROVA_DATA_DIR 隔离，帧键
每条用例独立命名，不触碰生产 data/。
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_client import NeuacpError
from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.executor import NeuacpExecResult, NeuacpExecutor, NeuacpSessionContext
from neurova.agent.neuacp.scripted_executor import NeuacpScriptedExecutor

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")

# 共享剧本：与 fake_acp_agent.py 的 acp_permission(allow) 模式逐拍对齐——
# 同一段 content/thought chunk + 一次权限往返 + end_of_turn。
SHARED_SCRIPT = [
    {"emit": ["content", "你好 Neuacp"]},
    {"emit": ["reasoning", "思考中"]},
    {"request_permission": {"action": "acp:demo:edit", "reason": "契约测试", "context": "contract"}},
    {"result": {"stopReason": "end_of_turn"}},
]
SHARED_WIRE_MODE = "acp_permission"
SHARED_CHUNKS = [("content", "你好 Neuacp"), ("reasoning", "思考中")]


def _allow(_action, _reason, _context):
    return {"approved": True}


def _makeCtx(cwd="", metadata=None):
    return NeuacpSessionContext(
        member_session_id="m-contract",
        task_text="写个登录页",
        cwd=cwd,
        metadata=metadata or {},
    )


def _runWire(mode, on_permission=None, frame_key=None):
    """驱动 wire 桩（真子进程），返回 (chunks, result)。"""
    chunks = []
    executor = NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": mode},
    )
    setFrameKey = getattr(executor, "setFrameKey", None)
    if frame_key and callable(setFrameKey):
        setFrameKey(frame_key)
    ctx = _makeCtx(cwd=str(FAKE_AGENT.parent))

    async def run():
        await executor.start(ctx)
        result = await executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), on_permission)
        await executor.close()
        return result

    result = asyncio.run(run())
    return chunks, result


def _runScripted(script, on_permission=None, frame_key=None, metadata=None):
    """驱动 scripted 桩（无子进程），返回 (chunks, result)。"""
    chunks = []
    executor = NeuacpScriptedExecutor(script=script)
    if frame_key:
        executor.setFrameKey(frame_key)
    ctx = _makeCtx(metadata=metadata)

    async def run():
        await executor.start(ctx)
        result = await executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), on_permission)
        await executor.close()
        return result

    result = asyncio.run(run())
    return chunks, result


def _installFrameStub(monkeypatch):
    """注入 frame_log 局部替身（并行交付前即可验证帧写入行为）。返回写入记录列表。"""
    recorded = []

    def appendFrame(key, direction, frame, **_kwargs):
        recorded.append({"key": key, "direction": direction, "frame": frame})
        return len(recorded)

    stub = types.SimpleNamespace(
        appendFrame=appendFrame,
        readFrames=lambda key, afterSeq=0, limit=1000: [rec for rec in recorded if rec["key"] == key],
    )
    monkeypatch.setitem(sys.modules, "neurova.agent.neuacp.frame_log", stub)
    return recorded


def _tryReadFrames(key):
    """读真帧流；frame_log 并行交付未就绪或读取失败时返回 None（调用方跳过断言）。"""
    try:
        from neurova.agent.neuacp.frame_log import readFrames
    except Exception:
        return None
    try:
        return readFrames(key)
    except Exception:
        return None


# ---------- 契约：同一剧本，可观测结局一致 ----------


def test_sameScriptYieldsSameEmitterSequenceAndResult():
    wire_chunks, wire_result = _runWire(SHARED_WIRE_MODE, on_permission=_allow)
    scripted_chunks, scripted_result = _runScripted(SHARED_SCRIPT, on_permission=_allow)
    assert scripted_chunks == wire_chunks
    assert scripted_chunks == SHARED_CHUNKS
    assert scripted_result.text == wire_result.text
    assert scripted_result.stop_reason == wire_result.stop_reason
    assert scripted_result.text == "你好 Neuacp"
    assert scripted_result.stop_reason == "end_of_turn"


def test_framesStreamsContainInOutOnBothSides():
    # scripted 侧：显式 setFrameKey，帧流应同时含 in 与 out 记录
    scripted_key = "contract-frames-scripted"
    _runScripted(SHARED_SCRIPT, on_permission=_allow, frame_key=scripted_key)
    scripted_frames = _tryReadFrames(scripted_key)
    if scripted_frames is not None:
        directions = {rec.get("direction") for rec in scripted_frames if isinstance(rec, dict)}
        assert "in" in directions, f"scripted 帧流缺 in 记录: {scripted_frames}"
        assert "out" in directions, f"scripted 帧流缺 out 记录: {scripted_frames}"

    # wire 侧：setFrameKey 挂点未交付（getattr 落空）则跳过该侧断言
    wire_key = "contract-frames-wire"
    chunks = []
    executor = NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": SHARED_WIRE_MODE},
    )
    setFrameKey = getattr(executor, "setFrameKey", None)
    if callable(setFrameKey):
        setFrameKey(wire_key)
    ctx = _makeCtx(cwd=str(FAKE_AGENT.parent))

    async def run():
        await executor.start(ctx)
        result = await executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), _allow)
        await executor.close()
        return result

    asyncio.run(run())
    if callable(setFrameKey):
        wire_frames = _tryReadFrames(wire_key)
        if wire_frames is not None:
            directions = {rec.get("direction") for rec in wire_frames if isinstance(rec, dict)}
            assert "in" in directions, f"wire 帧流缺 in 记录: {wire_frames}"
            assert "out" in directions, f"wire 帧流缺 out 记录: {wire_frames}"


def test_scriptedExecutorSatisfiesExecutorProtocol():
    executor = NeuacpScriptedExecutor(script=[])
    assert isinstance(executor, NeuacpExecutor)
    assert callable(executor.setToolCallHandler)
    assert callable(executor.attachProcessPool)
    assert callable(executor.setFrameKey)


def test_attachProcessPoolIsNoOp():
    executor = NeuacpScriptedExecutor(script=[{"emit": ["content", "ok"]}, {"result": {"stopReason": "end_of_turn"}}])
    executor.attachProcessPool(object(), ("tenant", "tool"))
    ctx = _makeCtx()

    async def run():
        await executor.start(ctx)
        return await executor.prompt("写个登录页", lambda kind, text: None, None)

    result = asyncio.run(run())
    assert result.text == "ok"


# ---------- scripted 专属：帧同构（frame_log 局部替身） ----------


def test_scriptedFramesMirrorWireShapes(monkeypatch):
    recorded = _installFrameStub(monkeypatch)
    script = [
        {"emit": ["content", "你好"]},
        {"emit": ["reasoning", "想"]},
        {"tool_call": {"title": "写文件", "toolCallId": "tc-9"}},
        {"request_permission": {"action": "acp:demo:edit", "reason": "r"}},
        {"result": {"stopReason": "end_of_turn"}},
    ]
    _runScripted(script, on_permission=_allow, frame_key="frame-shape-1")
    frames = [(rec["direction"], rec["frame"]) for rec in recorded]
    assert ("in", {"type": "session_update", "sessionUpdate": "agent_message_chunk", "content": {"text": "你好"}}) in frames
    assert ("in", {"type": "session_update", "sessionUpdate": "agent_thought_chunk", "content": {"text": "想"}}) in frames
    assert ("in", {"type": "session_update", "sessionUpdate": "tool_call", "tool_call": {"title": "写文件", "toolCallId": "tc-9"}}) in frames
    assert ("in", {"type": "permission_request", "action": "acp:demo:edit", "reason": "r"}) in frames
    assert ("out", {"type": "permission_response", "approved": True}) in frames
    assert ("in", {"result": {"stopReason": "end_of_turn"}}) in frames
    # 权限因果序与 wire 同构：请求帧（in）先于应答帧（out）
    first_permission_index = next(i for i, (d, f) in enumerate(frames) if f.get("type") == "permission_request")
    response_index = next(i for i, (d, f) in enumerate(frames) if f.get("type") == "permission_response")
    assert first_permission_index < response_index


def test_frameKeyFallsBackToContextMetadata(monkeypatch):
    recorded = _installFrameStub(monkeypatch)
    executor = NeuacpScriptedExecutor(script=[{"emit": ["content", "x"]}])
    ctx = _makeCtx(metadata={"subagent_id": "run-42"})

    async def run():
        await executor.start(ctx)
        await executor.prompt("写个登录页", lambda kind, text: None, None)

    asyncio.run(run())
    assert recorded, "start(ctx) 应从 metadata.subagent_id 取 frame_key 并落帧"
    assert all(rec["key"] == "run-42" for rec in recorded)


def test_explicitFrameKeyWinsOverMetadata(monkeypatch):
    recorded = _installFrameStub(monkeypatch)
    executor = NeuacpScriptedExecutor(script=[{"emit": ["content", "x"]}])
    executor.setFrameKey("explicit-key")
    ctx = _makeCtx(metadata={"subagent_id": "meta-key"})

    async def run():
        await executor.start(ctx)
        await executor.prompt("写个登录页", lambda kind, text: None, None)

    asyncio.run(run())
    assert recorded, "显式 setFrameKey 后仍应落帧"
    assert all(rec["key"] == "explicit-key" for rec in recorded)


def test_noFrameKeySkipsFrameWrites(monkeypatch):
    recorded = _installFrameStub(monkeypatch)
    _runScripted([{"emit": ["content", "x"]}])
    assert recorded == [], "frame_key 未设时不得落帧（无主不留痕）"


def test_frameFailureDoesNotBlockExecution(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    stub = types.SimpleNamespace(appendFrame=boom, readFrames=lambda *a, **k: [])
    monkeypatch.setitem(sys.modules, "neurova.agent.neuacp.frame_log", stub)
    chunks, result = _runScripted(
        [{"emit": ["content", "照常"]}, {"result": {"stopReason": "end_of_turn"}}],
        frame_key="frame-fail-k",
    )
    assert chunks == [("content", "照常")]
    assert result.text == "照常"
    assert result.stop_reason == "end_of_turn"


# ---------- scripted 专属：permission 裁决 ----------


def test_permissionDenyAbortsRemainingSteps():
    script = [
        {"emit": ["content", "开头"]},
        {"request_permission": {"action": "acp:demo:edit", "reason": "要写盘"}},
        {"emit": ["content", "不应出现"]},
        {"result": {"stopReason": "end_of_turn"}},
    ]
    asks = []

    def deny(action, reason, context):
        asks.append((action, reason, context))
        return {"approved": False}

    chunks, result = _runScripted(script, on_permission=deny)
    assert asks == [("acp:demo:edit", "要写盘", "scripted")]
    assert chunks == [("content", "开头")]
    assert result.text == "开头"
    assert result.stop_reason == "cancelled"


def test_permissionDefaultsAndAllowContinues():
    asks = []
    script = [
        {"request_permission": {}},
        {"emit": ["content", "继续"]},
        {"result": {"stopReason": "end_of_turn"}},
    ]
    chunks, result = _runScripted(script, on_permission=lambda a, r, c: (asks.append((a, r, c)), {"approved": True})[1])
    assert asks == [("acp:demo:edit", "", "scripted")]
    assert chunks == [("content", "继续")]
    assert result.text == "继续"
    assert result.stop_reason == "end_of_turn"


def test_permissionWithoutAskerDeniesFailClosed():
    script = [{"request_permission": {}}, {"emit": ["content", "不应出现"]}]
    chunks, result = _runScripted(script, on_permission=None)
    assert chunks == []
    assert result.stop_reason == "cancelled"


def test_permissionAskerCrashDeniesFailClosed():
    def boom(_action, _reason, _context):
        raise RuntimeError("审批链崩了")

    chunks, result = _runScripted(
        [{"request_permission": {}}, {"emit": ["content", "不应出现"]}],
        on_permission=boom,
    )
    assert chunks == []
    assert result.stop_reason == "cancelled"


# ---------- scripted 专属：tool_call / crash / exit_code ----------


def test_toolCallReachesMirrorHandler():
    seen = []
    executor = NeuacpScriptedExecutor(script=[{"tool_call": {"title": "读取文件", "toolCallId": "tc-1"}}])
    executor.setToolCallHandler(seen.append)
    ctx = _makeCtx()

    async def run():
        await executor.start(ctx)
        return await executor.prompt("写个登录页", lambda kind, text: None, None)

    result = asyncio.run(run())
    assert seen == [{"title": "读取文件", "toolCallId": "tc-1"}]
    assert result.stop_reason == "end_of_turn"


def test_toolCallWithoutHandlerIsIgnored():
    executor = NeuacpScriptedExecutor(script=[{"tool_call": {"title": "x"}}, {"result": {"stopReason": "end_of_turn"}}])
    ctx = _makeCtx()

    async def run():
        await executor.start(ctx)
        return await executor.prompt("写个登录页", lambda kind, text: None, None)

    result = asyncio.run(run())
    assert result.stop_reason == "end_of_turn"


def test_crashRaisesHonestNeuacpError(monkeypatch):
    recorded = _installFrameStub(monkeypatch)
    executor = NeuacpScriptedExecutor(script=[{"crash": "segfault"}])
    executor.setFrameKey("crash-k")
    ctx = _makeCtx()

    async def run():
        await executor.start(ctx)
        await executor.prompt("写个登录页", lambda kind, text: None, None)

    with pytest.raises(NeuacpError, match="external agent crashed during prompt: segfault"):
        asyncio.run(run())
    observed = [(rec["direction"], rec["frame"]) for rec in recorded]
    assert ("observed", {"type": "crashed", "reason": "segfault"}) in observed


def test_nonZeroExitCodeFailsHonestly():
    executor = NeuacpScriptedExecutor(script=[{"emit": ["content", "部分"]}, {"exit_code": 2}])
    ctx = _makeCtx()

    async def run():
        await executor.start(ctx)
        await executor.prompt("写个登录页", lambda kind, text: None, None)

    with pytest.raises(NeuacpError, match="scripted executor exited with code 2"):
        asyncio.run(run())


def test_zeroExitCodeContinues():
    chunks, result = _runScripted(
        [{"exit_code": 0}, {"emit": ["content", "继续"]}, {"result": {"stopReason": "end_of_turn"}}]
    )
    assert chunks == [("content", "继续")]
    assert result.text == "继续"
    assert result.stop_reason == "end_of_turn"


# ---------- scripted 专属：cancel / start 复位 / result / 空剧本 ----------


def test_cancelAbortsSleepAndSkipsRest():
    script = [
        {"emit": ["content", "前半"]},
        {"sleep": 30},
        {"emit": ["content", "后半"]},
        {"result": {"stopReason": "end_of_turn"}},
    ]
    executor = NeuacpScriptedExecutor(script=script)
    ctx = _makeCtx()
    chunks = []

    async def run():
        await executor.start(ctx)
        task = asyncio.create_task(executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), None))
        await asyncio.sleep(0.1)
        await executor.cancel()
        result = await task
        await executor.close()
        return result

    result = asyncio.run(run())
    assert chunks == [("content", "前半")]
    assert result.text == "前半"
    assert result.stop_reason == "cancelled"
    assert "后半" not in result.text


def test_startResetsStateForReruns():
    script = [{"emit": ["content", "第一轮"]}, {"result": {"stopReason": "end_of_turn"}}]
    executor = NeuacpScriptedExecutor(script=script)
    ctx = _makeCtx()

    async def run():
        await executor.start(ctx)
        first = await executor.prompt("写个登录页", lambda kind, text: None, None)
        await executor.start(ctx)
        second = await executor.prompt("写个登录页", lambda kind, text: None, None)
        return first, second

    first, second = asyncio.run(run())
    assert first.text == "第一轮"
    assert second.text == "第一轮"
    assert second.stop_reason == "end_of_turn"


def test_resultStepCarriesRawAndStopReason():
    raw = {"stopReason": "max_tokens", "usage": {"outputTokens": 10}}
    chunks, result = _runScripted([{"emit": ["content", "部分"]}, {"result": raw}])
    assert chunks == [("content", "部分")]
    assert result.text == "部分"
    assert result.stop_reason == "max_tokens"
    assert result.raw == raw


def test_emptyScriptReturnsEndOfTurn():
    chunks, result = _runScripted([])
    assert chunks == []
    assert result.text == ""
    assert result.stop_reason == "end_of_turn"
    assert isinstance(result, NeuacpExecResult)
