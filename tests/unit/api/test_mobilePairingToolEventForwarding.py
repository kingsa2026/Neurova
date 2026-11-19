# -*- coding: utf-8 -*-
"""移动 WS 通道透传 tool_call/tool_result 事件（对齐 PC 工具卡片）契约档。

## 缺陷形状（红灯实证）

`_pump` 事件泵只认 content/reasoning/retry/upstream_status——
`openai_loop._predict_stream_once` 产出的 tool_call/tool_result 在移动泵里被静默丢弃，
手机端永远看不到工具卡（PC 端同源事件早已有卡片渲染）。
且 turnMetadata 未开 `emit_tool_events` 门：即便泵转发，管线侧也不会产这两类事件。

## 判据形状

替身 agent 按 `Agent.chat` 真签名 bind（沿用本目录批 17 契约档 `test_mobilePairingChatSendContract.py`
的防漂姿势——手抄签名清单会随生产签名一起漂），经 `metadata["event_emitter"]` 依次发
reasoning / tool_call / tool_result / content，断言 WS 侧逐一收到 `chat:*` 对应事件、
载荷原样透传、metadata 真的开了门；再以"只发工具事件、不发 content"的替身钉住
兜底 chunk（正文经 done 前的兜底路径补发，前端不留空白轮）。
"""
from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep
from neurova.core.identity_context import get_request_user_id

PAIRING_CODE = "MOBILE-TOOL-1"
OWNER = "u-mobile-tool"
AGENT_ID = "mobile-tool-agent"

TOOL_CALL_PAYLOAD = {"id": "call-1", "type": "function",
                     "function": {"name": "get_datetime",
                                  "arguments": '{"timezone":"Asia/Shanghai"}'}}
TOOL_RESULT_PAYLOAD = {"role": "tool", "tool_call_id": "call-1",
                       "name": "get_datetime",
                       "content": '{"datetime":"2026-11-20 05:13:39"}'}
REPLY_TEXT = "## 当前时间\n\n- 星期五"


def _checkAgainstRealSignature(agent, kwargs: Dict[str, Any], sink: List[dict]) -> None:
    """按真 `Agent.chat` 的签名 bind 一遍：参数名不对、必填没给，都在这一步抛。"""
    from neurova.agent_core import Agent

    inspect.signature(Agent.chat).bind(None, **kwargs)
    sink.append({**kwargs, "request_channel": get_request_user_id()})


class _ToolEmittingAgent:
    """经 metadata.event_emitter 发工具/思考/正文事件的替身回合。"""

    def __init__(self, withContent: bool) -> None:
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.withContent = withContent
        self.calls: List[Dict[str, Any]] = []

    async def chat(self, **kwargs):
        _checkAgainstRealSignature(self, kwargs, self.calls)
        emit = kwargs["metadata"]["event_emitter"]
        emit("reasoning", "正在查找时间工具")
        emit("tool_call", TOOL_CALL_PAYLOAD)
        emit("tool_result", TOOL_RESULT_PAYLOAD)
        if self.withContent:
            emit("content", REPLY_TEXT)
        return {"text": REPLY_TEXT, "success": True}


@pytest.fixture(autouse=True)
def _freshRunStateSingletons():
    """台账/让位闸单例逐测重置并清空行：本档的占位行与计时状态不泄漏进其他测试。"""
    import asyncio

    from neurova.collaboration import glance_yield_rules as gyr
    from neurova.core import agent_run_store as ars

    asyncio.run(gyr.reset_glance_yield_checker())
    ars.reset_agent_run_store()
    store = ars.get_agent_run_store()
    with store._lock:
        store._conn.execute("DELETE FROM agent_runs")
        store._conn.commit()
    yield
    asyncio.run(gyr.reset_glance_yield_checker())
    ars.reset_agent_run_store()
    store = ars.get_agent_run_store()
    with store._lock:
        store._conn.execute("DELETE FROM agent_runs")
        store._conn.commit()


@pytest.fixture()
def wsClient(monkeypatch, request):
    withContent = request.param if getattr(request, "param", None) is not None else True
    agent = _ToolEmittingAgent(withContent)
    # `get_agent_instance` 在 `_handle_chat_send` 里就近 import——必须打在出处
    # `neurova.api.endpoints` 上（打在 mobile_pairing 模块上是 AttributeError）。
    import neurova.api.endpoints as endpointsModule

    monkeypatch.setattr(endpointsModule, "get_agent_instance", lambda agent_id="": agent)

    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": "pair-tool-1"},
    )

    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    client = TestClient(app)
    client.agent = agent  # type: ignore[attr-defined]
    return client


def _driveChat(client, sessionId: str = "s-tool-1") -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
        ws.send_json({"type": "chat:send", "content": "现在几点",
                      "session_id": sessionId})
        while True:
            payload = json.loads(ws.receive_text())
            events.append(payload)
            if payload.get("type") in ("chat:done", "error"):
                break
    return events


class TestToolEventsReachTheMobileWire:
    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_toolEventsAreForwardedNotDropped(self, wsClient):
        events = _driveChat(wsClient)

        failed = [e for e in events if e.get("code") == "chat_failed"]
        assert not failed, f"回合失败：{failed[0].get('message')!r}"

        kinds = [e["type"] for e in events]
        assert "chat:tool_call" in kinds, (
            f"工具调用事件在移动泵里被丢弃（kinds={kinds}）——"
            "手机端永远看不到工具卡，与 PC 端同源事件不对齐")
        assert "chat:tool_result" in kinds, f"工具结果事件被丢弃（kinds={kinds}）"
        assert "chat:reasoning" in kinds, f"思考事件被丢弃（kinds={kinds}）"
        assert kinds[-1] == "chat:done", kinds

    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_toolPayloadsPassThroughIntact(self, wsClient):
        events = _driveChat(wsClient)

        toolCall = next(e for e in events if e["type"] == "chat:tool_call")
        assert toolCall["data"] == TOOL_CALL_PAYLOAD, (
            f"tool_call 载荷变形：{toolCall['data']!r}")
        assert toolCall["data"]["function"]["name"] == "get_datetime"
        toolResult = next(e for e in events if e["type"] == "chat:tool_result")
        assert toolResult["data"] == TOOL_RESULT_PAYLOAD, (
            f"tool_result 载荷变形：{toolResult['data']!r}")

    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_turnMetadataOpensTheToolEventGate(self, wsClient):
        """管线侧按 `emit_tool_events` 决定是否产工具事件：移动回合必须开门。"""
        _driveChat(wsClient)

        assert wsClient.agent.calls, "一轮都没打到 agent"
        metadata = wsClient.agent.calls[0].get("metadata") or {}
        assert metadata.get("emit_tool_events") is True, (
            f"turnMetadata 没开 emit_tool_events 门（metadata keys={sorted(metadata)}）——"
            "泵转发了管线也不产事件")


class TestToolOnlyTurnStillLeavesNoBlankRound:
    @pytest.mark.parametrize("wsClient", [False], indirect=True)
    def test_fallbackChunkCoversToolOnlyTurns(self, wsClient):
        events = _driveChat(wsClient)

        chunks = [e for e in events if e["type"] == "chat:chunk"]
        assert len(chunks) == 1, f"兜底 chunk 应恰好补一条：{len(chunks)} 条"
        assert chunks[0]["content"] == REPLY_TEXT, chunks[0]
        assert events[-1]["type"] == "chat:done", events
        # 工具事件依旧在线上（本替身不发 content，工具卡仍要出）
        kinds = [e["type"] for e in events]
        assert "chat:tool_call" in kinds and "chat:tool_result" in kinds, kinds
