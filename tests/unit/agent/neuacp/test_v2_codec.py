# -*- coding: utf-8 -*-
"""G6 红灯：ACP v2 编解码层（codec_v2）契约测试。

三层覆盖：
1. 纯函数单测——v2 schema 形状构造（initialize/info、new/resume/prompt/
   cancel/permission）与 SessionUpdate 24 分支 → 内部事件模型映射；
2. 客户端版本策略——握手协商出整数版本后选择 codec（v2=V2Codec，
   v1=既有路径 codec 为 None）；
3. 真 stdio 集成——经 v2_strict_agent.py（按 v2 schema 严格校验、不符回
   -32602）跑通 握手/流式/权限/按 requestId 取消/未知分支跳过。

另含 strict agent 自证（裸 NDJSON 直发违规形状必收 -32602），钉住「线上
形状错误会被真 agent 拒绝」这一前提。
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import queue as queueMod
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_client import NeuacpClient, NeuacpProtocolError
from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.codec_v2 import (
    V2Codec,
    V2ProtocolError,
    buildCancelRequestParams,
    buildInitializeParams,
    buildNewSessionParams,
    buildPermissionResponse,
    buildPromptParams,
    buildResumeParams,
    parseInitializeResponse,
    parseNewSessionResponse,
    parsePromptResponse,
    parseSessionUpdate,
)
from neurova.agent.neuacp.executor import NeuacpSessionContext

V2_AGENT = Path(__file__).with_name("v2_strict_agent.py")
V1_FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")

_OPTIONS = [
    {"optionId": "opt-allow", "name": "允许", "kind": "allow_once"},
    {"optionId": "opt-reject", "name": "拒绝", "kind": "reject_once"},
]


def _update(kind, **fields):
    """构造 v2 session/update params（UpdateSessionNotification 信封）。"""
    return {"sessionId": "sess-v2-1", "update": {"sessionUpdate": kind, **fields}}


# ---------- 1. 出站：v2 请求形状构造 ----------

def test_initializeParams_carriesInfoAndIntegerVersion():
    import neurova

    params = buildInitializeParams(2, {"fonts": {"list": []}})
    assert params["protocolVersion"] == 2 and isinstance(params["protocolVersion"], int)
    # v2 必填 info（Implementation{name, version}），能力字段名为 capabilities
    assert params["info"]["name"] == "neurova"
    assert params["info"]["version"] == neurova.__version__
    assert params["capabilities"] == {"fonts": {"list": []}}
    # v1 的 clientCapabilities 字段不得出现在 v2 握手里
    assert "clientCapabilities" not in params


def test_parseInitializeResponse_okAndFailsClosed():
    ok = {"protocolVersion": 2, "info": {"name": "agent", "version": "2.0.0"},
          "capabilities": {}, "authMethods": []}
    assert parseInitializeResponse(ok)["protocolVersion"] == 2
    with pytest.raises(V2ProtocolError):
        parseInitializeResponse({"protocolVersion": 2, "capabilities": {}})  # 缺 info
    with pytest.raises(V2ProtocolError):
        parseInitializeResponse({"info": {"name": "agent", "version": "2.0.0"}})  # 缺版本号字段
    with pytest.raises(V2ProtocolError):
        parseInitializeResponse({"protocolVersion": "2",
                                 "info": {"name": "agent", "version": "2.0.0"}})  # 版本须整数


def test_newSessionParams_requiresAbsoluteCwd():
    assert buildNewSessionParams("E:/Projects/Neurova") == {
        "cwd": "E:/Projects/Neurova", "mcpServers": []}
    servers = [{"name": "m", "command": ["npx", "x"]}]
    assert buildNewSessionParams("/tmp/w", servers)["mcpServers"] == servers


def test_parseNewSessionResponse_failsClosedOnMissingSessionId():
    assert parseNewSessionResponse({"sessionId": "s1"}) == {"sessionId": "s1"}
    with pytest.raises(V2ProtocolError):
        parseNewSessionResponse({"configOptions": []})


def test_resumeParams_requiresTriple():
    assert buildResumeParams("s1", "E:/w") == {"sessionId": "s1", "cwd": "E:/w"}
    assert buildResumeParams("s1", "E:/w", {"type": "start"}) == {
        "sessionId": "s1", "cwd": "E:/w", "replayFrom": {"type": "start"}}


def test_promptParams_isContentBlockArray():
    params = buildPromptParams("s1", "写个登录页")
    # v2：prompt 是内容块数组（v1 时代字符串形状会被真 agent -32602 拒绝）
    assert params == {"sessionId": "s1",
                      "prompt": [{"type": "text", "text": "写个登录页"}]}
    assert isinstance(params["prompt"], list)


def test_parsePromptResponse_requiresMessageId():
    assert parsePromptResponse({"messageId": "m1"}) == {"messageId": "m1"}
    with pytest.raises(V2ProtocolError):
        parsePromptResponse({})  # v2 应答必带 messageId（不再是 stopReason）


def test_cancelRequestParams_carriesRequestId():
    assert buildCancelRequestParams(7) == {"requestId": 7}


def test_permissionResponse_selectsMatchingOption():
    allowed = buildPermissionResponse({"approved": True}, {"options": _OPTIONS})
    assert allowed == {"outcome": {"outcome": "selected", "optionId": "opt-allow"}}
    denied = buildPermissionResponse({"approved": False}, {"options": _OPTIONS})
    assert denied == {"outcome": {"outcome": "selected", "optionId": "opt-reject"}}


def test_permissionResponse_failsClosedToCancelledWithoutMatchingOption():
    # 只给了 allow 选项却要拒绝：无法如实 selected，回 cancelled（fail-closed，
    # v2 规定非 selected/cancelled 的形状不得被 agent 当作批准）
    only_allow = [{"optionId": "a", "name": "允许", "kind": "allow_once"}]
    assert buildPermissionResponse({"approved": False}, {"options": only_allow}) == \
        {"outcome": {"outcome": "cancelled"}}
    assert buildPermissionResponse({"approved": True}, {"options": []}) == \
        {"outcome": {"outcome": "cancelled"}}


# ---------- 2. 入站：SessionUpdate 24 分支 → 内部事件模型 ----------

def test_agentMessageChunk_mapsToContentStream():
    event = parseSessionUpdate(_update("agent_message_chunk", messageId="m1",
                                       content={"type": "text", "text": "你好"}))
    assert event["event"] == "content"
    assert event["text"] == "你好"
    assert event["messageId"] == "m1"
    assert event["update"]["sessionUpdate"] == "agent_message_chunk"


def test_agentMessageChunk_nonTextBlock_yieldsEmptyText():
    event = parseSessionUpdate(_update("agent_message_chunk", messageId="m1",
                                       content={"type": "image", "data": "xx", "mimeType": "image/png"}))
    assert event["event"] == "content"
    assert event["text"] == ""  # 非文本块不臆造文本，交由消费方按空跳过


def test_agentThoughtChunk_mapsToReasoningStream():
    event = parseSessionUpdate(_update("agent_thought_chunk", messageId="m2",
                                       content={"type": "text", "text": "思考中"}))
    assert event["event"] == "reasoning"
    assert event["text"] == "思考中"


def test_agentMessageAndThought_mapToMessage():
    message = parseSessionUpdate(_update("agent_message", messageId="m3",
                                         content=[{"type": "text", "text": "A"},
                                                  {"type": "text", "text": "B"}]))
    assert message["event"] == "message"
    assert message["text"] == "AB"
    thought = parseSessionUpdate(_update("agent_thought", messageId="m4",
                                         content=[{"type": "text", "text": "想"}]))
    assert thought["event"] == "message"
    assert thought["text"] == "想"


def test_toolCallBranches_mapToToolCallMirror():
    raw = {"sessionUpdate": "tool_call_update", "toolCallId": "tc-1",
           "title": "写入 src/app.py", "kind": "edit", "status": "completed"}
    event = parseSessionUpdate({"sessionId": "sess-v2-1", "update": raw})
    assert event["event"] == "tool_call"
    assert event["update"]["toolCallId"] == "tc-1"
    chunk = parseSessionUpdate(_update("tool_call_content_chunk", toolCallId="tc-1",
                                       content={"type": "content",
                                                "content": {"type": "text", "text": "out"}}))
    assert chunk["event"] == "tool_call"
    assert chunk["update"]["toolCallId"] == "tc-1"


def test_planBranches_mapToPlan():
    plan = parseSessionUpdate(_update("plan_update", plan={
        "type": "items", "entries": [{"content": "步骤一", "priority": "high", "status": "pending"}]}))
    assert plan["event"] == "plan"
    assert plan["update"]["plan"]["entries"][0]["content"] == "步骤一"
    removed = parseSessionUpdate(_update("plan_removed", planId="p1"))
    assert removed["event"] == "plan"
    assert removed["update"]["planId"] == "p1"


def test_usageBranch_mapsToUsage():
    event = parseSessionUpdate(_update("usage_update", used=100, size=1000,
                                       cost={"amount": 0.5, "currency": "USD"}))
    assert event["event"] == "usage"
    assert event["update"]["used"] == 100
    assert event["update"]["cost"]["currency"] == "USD"


def test_compactionBranches_mapToCompaction():
    upd = parseSessionUpdate(_update("compaction_update", compactionId="c1", status="in_progress"))
    assert upd["event"] == "compaction"
    chunk = parseSessionUpdate(_update("compaction_summary_chunk", compactionId="c1",
                                       content={"type": "text", "text": "摘要"}))
    assert chunk["event"] == "compaction"


def test_stateUpdate_idle_mapsToStopWithReason():
    event = parseSessionUpdate(_update("state_update", state="idle", stopReason="end_of_turn"))
    assert event["event"] == "stop"
    assert event["stopReason"] == "end_of_turn"
    no_reason = parseSessionUpdate(_update("state_update", state="idle"))
    assert no_reason["event"] == "stop"
    assert no_reason["stopReason"] == ""


def test_stateUpdate_nonIdle_skipped():
    for state in ("running", "requires_action", "unknown"):
        event = parseSessionUpdate(_update("state_update", state=state))
        assert event["event"] == "skip", state
        assert event["reason"].startswith("state_")


def test_userEchoBranches_skipped():
    # 用户回显不是产出：v1 执行体同样不消费 user_message_chunk
    chunk = parseSessionUpdate(_update("user_message_chunk", messageId="u1",
                                       content={"type": "text", "text": "用户的话"}))
    assert chunk["event"] == "skip"
    message = parseSessionUpdate(_update("user_message", messageId="u1",
                                         content=[{"type": "text", "text": "用户的话"}]))
    assert message["event"] == "skip"


def test_terminalBranches_skipped():
    assert parseSessionUpdate(_update("terminal_update", terminalId="t1"))["event"] == "skip"
    assert parseSessionUpdate(_update("terminal_output_chunk", terminalId="t1", data="out"))["event"] == "skip"


def test_unstableBranches_skipped():
    # schema 标注 UNSTABLE 的分支：subagent_update / session_message(_chunk)
    assert parseSessionUpdate(_update("subagent_update", sessionId="s2"))["event"] == "skip"
    assert parseSessionUpdate(_update("session_message", messageId="m9"))["event"] == "skip"
    assert parseSessionUpdate(_update("session_message_chunk", messageId="m9",
                                      content={"type": "text", "text": "x"}))["event"] == "skip"


def test_sessionManagementBranches_skipped():
    assert parseSessionUpdate(_update("available_commands_update", availableCommands=[]))["event"] == "skip"
    assert parseSessionUpdate(_update("config_option_update", configOptions=[]))["event"] == "skip"
    assert parseSessionUpdate(_update("session_info_update"))["event"] == "skip"
    assert parseSessionUpdate(_update("notice", severity="info", title="提示"))["event"] == "skip"


def test_unknownBranch_skippedWithRawPayloadPreserved():
    event = parseSessionUpdate(_update("_custom_future", payload={"x": 1}))
    assert event["event"] == "skip"
    assert event["reason"] == "unknown_session_update_type"
    assert event["update"]["payload"] == {"x": 1}  # 原样归档，不臆造字段


def test_missingUpdate_skippedDefensively():
    assert parseSessionUpdate({})["event"] == "skip"


def test_v2Codec_facadeDelegates():
    codec = V2Codec()
    assert codec.protocol_version == 2
    assert codec.cancel_method == "$/cancel_request"
    assert codec.promptParams("s1", "任务") == buildPromptParams("s1", "任务")
    assert codec.cancelRequestParams(3) == {"requestId": 3}


# ---------- 3. 客户端版本策略（真 stdio） ----------

def test_clientStartV2_selectsV2Codec():
    client = NeuacpClient([sys.executable, str(V2_AGENT)],
                          env_extra={"V2_STRICT_MODE": "ok"})
    try:
        handshake = client.start(protocol_version="2")
        assert handshake["protocolVersion"] == 2
        assert handshake["info"]["name"] == "strict-v2-agent"
        assert isinstance(client.codec, V2Codec)
    finally:
        client.terminate()


def test_clientStartV1_keepsLegacyPathWithoutCodec():
    client = NeuacpClient([sys.executable, str(V1_FAKE_AGENT)],
                          env_extra={"FAKE_ACP_MODE": "ok"})
    try:
        handshake = client.start(protocol_version="1")
        assert handshake["protocolVersion"] == "1"  # v1 假 agent 的既有应答形态
        assert client.codec is None  # v1 不引入 codec，走既有路径
    finally:
        client.terminate()


def test_clientStartV2_failsClosedOnVersionMismatch():
    client = NeuacpClient([sys.executable, str(V2_AGENT)],
                          env_extra={"V2_STRICT_MODE": "bad_version"})
    with pytest.raises(NeuacpProtocolError):
        client.start(protocol_version="2")
    assert not client.is_alive


# ---------- 4. strict agent 自证：违规线上形状必收 -32602 ----------

def _rawExchange(requests, mode="ok", expect=1, timeout=15.0):
    """裸 NDJSON 直发若干请求，收 expect 行应答/通知（验证 agent 严格性）。"""
    proc = subprocess.Popen(
        [sys.executable, str(V2_AGENT)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        env={**os.environ, "V2_STRICT_MODE": mode})
    lines = queueMod.Queue()

    def reader():
        for raw in proc.stdout:
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        for obj in requests:
            proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
            proc.stdin.flush()
        received = []
        while len(received) < expect:
            raw = lines.get(timeout=timeout)
            if raw is None:
                break
            received.append(json.loads(raw.decode("utf-8")))
        return received
    finally:
        proc.kill()


def test_strictAgent_rejectsInitializeWithoutInfo():
    (reply,) = _rawExchange([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": 2, "clientCapabilities": {}}},
    ], expect=1)
    assert reply["error"]["code"] == -32602
    assert "info" in reply["error"]["message"]


def test_strictAgent_rejectsStringProtocolVersion():
    (reply,) = _rawExchange([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2", "info": {"name": "n", "version": "1"}}},
    ], expect=1)
    assert reply["error"]["code"] == -32602


def test_strictAgent_rejectsStringPrompt():
    replies = _rawExchange([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": 2, "info": {"name": "n", "version": "1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(V2_AGENT.parent)}},
        {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
         "params": {"sessionId": "sess-v2-1", "prompt": "写个登录页"}},
    ], expect=3)
    assert replies[0]["result"]["protocolVersion"] == 2
    assert replies[1]["result"]["sessionId"] == "sess-v2-1"
    assert replies[2]["error"]["code"] == -32602
    assert "prompt" in replies[2]["error"]["message"]


def test_strictAgent_cancelRequiresRequestId():
    replies = _rawExchange([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": 2, "info": {"name": "n", "version": "1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(V2_AGENT.parent)}},
        {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
         "params": {"sessionId": "sess-v2-1", "prompt": [{"type": "text", "text": "长任务"}]}},
        {"jsonrpc": "2.0", "method": "$/cancel_request", "params": {}},          # 缺 requestId
        {"jsonrpc": "2.0", "method": "$/cancel_request", "params": {"requestId": "3"}},  # 非整数
        {"jsonrpc": "2.0", "method": "$/cancel_request", "params": {"requestId": 3}},    # 合规（= prompt 请求 id）
    ], mode="acp_cancel", expect=8)
    notices = [r for r in replies if r.get("method") == "session/update"
               and r["params"]["update"].get("sessionUpdate") == "notice"]
    assert len(notices) == 2  # 两次违规取消都被 agent 以 notice 点名
    assert all(n["params"]["update"]["title"] == "invalid_cancel_request" for n in notices)
    idle = [r for r in replies if r.get("method") == "session/update"
            and r["params"]["update"].get("sessionUpdate") == "state_update"]
    assert idle and idle[-1]["params"]["update"].get("stopReason") == "cancelled"


# ---------- 5. 执行体集成（真 stdio，经 codec 分发） ----------

def makeV2Executor(mode, on_permission=None):
    tool_events = []
    executor = NeuacpStdioExecutor(
        [sys.executable, str(V2_AGENT)],
        cwd=str(V2_AGENT.parent),
        env_extra={"V2_STRICT_MODE": mode},
        protocol_version="2",
        request_timeout=15.0,
        on_tool_call=lambda update: tool_events.append(update),
    )
    ctx = NeuacpSessionContext(member_session_id="m-v2", task_text="写个登录页",
                               cwd=str(V2_AGENT.parent))
    return executor, ctx, tool_events


def test_v2Executor_fullFlow_streamsAndCompletes():
    async def run():
        executor, ctx, _ = makeV2Executor("ok")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), None)
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert chunks == [("content", "你好 Neuacp"), ("reasoning", "思考中")]
    assert result.text == "你好 Neuacp"
    assert result.stop_reason == "end_of_turn"


def test_v2Executor_unknownUpdates_doNotBreakFlow():
    # ok 模式在 prompt 期还会推 notice 与 _future_kind 两个未知/未消费分支：
    # 执行体按「未知类型跳过」归档，不臆造事件、不中断回合。
    async def run():
        executor, ctx, _ = makeV2Executor("ok")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("写个登录页", lambda kind, text: chunks.append((kind, text)), None)
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("content", "你好 Neuacp") in chunks
    assert result.stop_reason == "end_of_turn"


def test_v2Executor_permissionAllowRoundTrip():
    async def run():
        executor, ctx, _ = makeV2Executor("acp_permission")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("改配置", lambda kind, text: chunks.append((kind, text)),
                                       lambda a, r, c: {"approved": True})
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    # v2 裁决应答须为 selected opt-allow；agent 校验通过才继续产出
    assert ("content", "你好 Neuacp") in chunks
    assert result.stop_reason == "end_of_turn"


def test_v2Executor_permissionDenyStopsTask():
    async def run():
        executor, ctx, _ = makeV2Executor("acp_permission")
        await executor.start(ctx)
        chunks = []
        result = await executor.prompt("改配置", lambda kind, text: chunks.append((kind, text)),
                                       lambda a, r, c: {"approved": False})
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("content", "权限被拒，任务中止") in chunks
    assert result.stop_reason == "end_of_turn"


def test_v2Executor_cancelByRequestId():
    async def run():
        executor, ctx, _ = makeV2Executor("acp_cancel")
        await executor.start(ctx)
        chunks = []
        task = asyncio.create_task(
            executor.prompt("长任务", lambda kind, text: chunks.append((kind, text)), None))
        # 等 agent 推出「等待取消」块（证明 prompt 请求已在线上），再发取消
        deadline = time.time() + 10
        while time.time() < deadline and not chunks:
            await asyncio.sleep(0.05)
        await executor.cancel()
        result = await task
        await executor.close()
        return chunks, result

    chunks, result = asyncio.run(run())
    assert ("content", "等待取消") in chunks
    assert result.stop_reason == "cancelled"
