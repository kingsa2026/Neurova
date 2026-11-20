# -*- coding: utf-8 -*-
"""A3 红灯：NeuacpMemberAdapter——swarm 成员鸭子面契约测试。

覆盖：chat 返回 {"text"} 且经 metadata["event_emitter"] 流式输出、
config.name、current_session_id、llm_client 注入、permission fail-closed、
stream=False 兼容。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.neuacp.executor import NeuacpSessionContext

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


def makeAdapter(mode, *, name="OpenCode 编码代理", permission_asker=None, verify_channel=None):
    executor = NeuacpStdioExecutor(
        [sys.executable, str(FAKE_AGENT)],
        cwd=str(FAKE_AGENT.parent),
        env_extra={"FAKE_ACP_MODE": mode},
    )
    adapter = NeuacpMemberAdapter(
        executor,
        name=name,
        cwd=str(FAKE_AGENT.parent),
        permission_asker=permission_asker,
        verify_channel=verify_channel,
    )
    return adapter


def test_chatReturnsTextAndStreamsViaMetadataEmitter():
    async def run():
        adapter = makeAdapter("acp_flow")
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("写个登录页", stream=True, session_id="m-9", metadata=metadata)
        await adapter.close()
        return chunks, response

    chunks, response = asyncio.run(run())
    assert chunks == [("content", "你好 Neuacp"), ("reasoning", "思考中")]
    assert response == {"text": "你好 Neuacp"}


def test_configNameAndCurrentSessionIdExposed():
    async def run():
        adapter = makeAdapter("acp_flow", name="Qoder 编码代理")
        assert adapter.config.name == "Qoder 编码代理"
        await adapter.chat("任务", stream=True, session_id="m-42", metadata={"event_emitter": lambda k, t: None})
        await adapter.close()
        return adapter

    adapter = asyncio.run(run())
    assert adapter.current_session_id == "m-42"


def test_missingEmitterStillReturnsText():
    async def run():
        adapter = makeAdapter("acp_flow")
        response = await adapter.chat("任务", stream=True, session_id="m-1", metadata={})
        await adapter.close()
        return response

    assert asyncio.run(run()) == {"text": "你好 Neuacp"}


def test_verifyChannelInjected():
    class FakeVerifyChannel:
        async def chat(self, messages, **kwargs):
            return None

    channel = FakeVerifyChannel()
    adapter = makeAdapter("acp_flow", verify_channel=channel)
    assert adapter.llm_client is channel


def test_permissionFailClosedWithoutAsker():
    async def run():
        adapter = makeAdapter("acp_permission", permission_asker=None)
        chunks = []
        metadata = {"event_emitter": lambda kind, text: chunks.append((kind, text))}
        response = await adapter.chat("改配置", stream=True, session_id="m-2", metadata=metadata)
        await adapter.close()
        return chunks, response

    chunks, response = asyncio.run(run())
    assert ("content", "权限被拒，任务中止") in chunks
    # deny 前的 content chunk 也会累积进最终文本（agent 先干活再请求权限）
    assert response == {"text": "你好 Neuacp权限被拒，任务中止"}


def test_permissionAskerReceivesAction():
    async def run():
        asks = []

        def asker(action, reason, context):
            asks.append(action)
            return {"approved": True}

        adapter = makeAdapter("acp_permission", permission_asker=asker)
        await adapter.chat("改配置", stream=True, session_id="m-3", metadata={"event_emitter": lambda k, t: None})
        await adapter.close()
        return asks

    asks = asyncio.run(run())
    assert asks and "写入 src/app.py" in asks[0]


def test_streamFalseStillReturnsText():
    async def run():
        adapter = makeAdapter("acp_flow")
        response = await adapter.chat("任务", stream=False, session_id="m-4", metadata={})
        await adapter.close()
        return response

    assert asyncio.run(run()) == {"text": "你好 Neuacp"}


# ── F2/F3 接线（线丁）：permission_decided 落账 + 工具镜像脱敏 ──────────


def makeBoundAdapter(events):
    """默认审批 asker（_approvalPermissionAsker）+ 已 bindRun 的适配器。"""
    adapter = makeAdapter("acp_flow")
    run = SimpleNamespace(subagent_id="swarm_perm", trace_id="tr-perm",
                          agent_name="外部成员", last_event_id="")
    adapter.bindRun(run, lambda r, t, p=None: events.append((t, p)))
    return adapter


def test_permissionDecidedLoggedOnApproveAndDeny(monkeypatch):
    """approve/deny 两路裁决都落 permission_decided 事件，payload 五键齐备，
    deny 理由里夹带的 api_key 形态被脱敏成 [redacted]。"""
    import json as _json

    import neurova.agent.approval_chain as approval_chain

    decisions = iter([
        {"approved": True, "pending": False, "denied": False, "reason": "ok"},
        {"approved": False, "pending": False, "denied": True,
         "reason": "denied api_key=sk-abcdef123456"},
    ])

    async def fakeRequest(run, action, **kwargs):
        return next(decisions)

    monkeypatch.setattr(approval_chain, "requestRunApproval", fakeRequest)
    monkeypatch.setattr(approval_chain, "approvalWaitSeconds", lambda: 1.0)

    events = []
    adapter = makeBoundAdapter(events)

    async def drive():
        adapter._loop = asyncio.get_running_loop()
        first = await asyncio.to_thread(adapter._permission_asker, "acp:fs:write", "写文件", "ctx")
        second = await asyncio.to_thread(adapter._permission_asker, "acp:fs:read", "读文件", "ctx")
        return first, second

    first, second = asyncio.run(drive())
    assert first["approved"] is True
    assert second["denied"] is True
    assert [t for t, _ in events] == ["permission_decided", "permission_decided"]
    approvePayload = events[0][1]
    denyPayload = events[1][1]
    assert set(approvePayload) == {"action", "approved", "pending", "denied", "reason"}
    assert approvePayload["action"] == "acp:fs:write"
    assert approvePayload["approved"] is True and approvePayload["denied"] is False
    assert denyPayload["action"] == "acp:fs:read"
    assert denyPayload["denied"] is True and denyPayload["pending"] is False
    # 值级脱敏：理由里夹带的 sk- 形态不得原样落账
    assert "[redacted]" in denyPayload["reason"]
    assert "sk-abcdef123456" not in _json.dumps(denyPayload, ensure_ascii=False)


def test_permissionDecidedLoggedOnBridgeFailure(monkeypatch):
    """桥接失败路径（fail-closed deny）同样落账——run 存在即记。"""
    import neurova.agent.approval_chain as approval_chain

    async def boom(run, action, **kwargs):
        raise RuntimeError("审批链不可用")

    monkeypatch.setattr(approval_chain, "requestRunApproval", boom)

    events = []
    adapter = makeBoundAdapter(events)

    async def drive():
        adapter._loop = asyncio.get_running_loop()
        return await asyncio.to_thread(adapter._permission_asker, "acp:fs:write", "写文件", "ctx")

    decision = asyncio.run(drive())
    assert decision["denied"] is True
    assert "approval_bridge_failed" in decision["reason"]
    assert [t for t, _ in events] == ["permission_decided"]
    assert events[0][1]["denied"] is True
    assert "审批链不可用" in events[0][1]["reason"]


def test_mirrorToolCallRedactsBeforeLedgerAndTrace():
    """_mirrorToolCall 的 update 先过 redactFrame 再进账本与轨迹：
    凭据字段/凭据形状 → [redacted]，且原 update 不被就地改写。"""
    import json as _json

    adapter = makeAdapter("acp_flow")
    run = SimpleNamespace(subagent_id="swarm_mir", trace_id="tr-mir",
                          agent_name="外部成员")
    ledger = []
    recorded = []

    class FakeRecorder:
        def record_event(self, trace_id, level, payload, span_id=None):
            recorded.append(payload)

    adapter.bindRun(run, lambda r, t, p=None: ledger.append(p),
                    recorder=FakeRecorder(), spanId="span-1")
    update = {
        "type": "tool_call",
        "tool": "write_file",
        "params": {"path": "src/app.py", "api_key": "sk-secret9999"},
        "credential": "hunter2",
        # ghp_ 规则要求后缀 ≥20 位（SENSITIVE_RULES 单源口径）
        "note": "token is ghp_0123456789abcdefghijklmnopqrst",
    }
    adapter._mirrorToolCall(update)

    assert len(ledger) == 1 and len(recorded) == 1
    mirrored = ledger[0]
    # 结构级：凭据字段名整体打码
    assert mirrored["params"]["api_key"] == "[redacted]"
    assert mirrored["credential"] == "[redacted]"
    # 值级：普通字段里的凭据形状（ghp_…）也被脱敏
    assert "ghp_0123456789abcdefghijklmnopqrst" not in _json.dumps(mirrored, ensure_ascii=False)
    assert "hunter2" not in _json.dumps(mirrored, ensure_ascii=False)
    # 轨迹收到的是同一份脱敏副本
    assert recorded[0]["tool_call"]["params"]["api_key"] == "[redacted]"
    assert recorded[0]["event"] == "tool_call"
    # 原 update 不被就地改写
    assert update["params"]["api_key"] == "sk-secret9999"
    assert update["credential"] == "hunter2"
