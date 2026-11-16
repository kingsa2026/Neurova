# -*- coding: utf-8 -*-
"""P9+ 运行态事件（工单：会话进度步骤条/排队卡）——移动 WS 中继补齐 PC 同款运行态。

## 断链（实测）

移动端 `chat:send` 此前直呼 `agent.chat_stream(...)`（句切假流式），绕过了
PC `/v1/chat/stream` 的整套运行态：无台账登记（排队位看不见）、无让位闸
（Agent 忙时移动端不排队）、管线 reasoning 事件不转发。PC 端同源能力：
`queued`（排队位）、`parked`（挂起）、`reasoning`（思考流）。

## 本批契约（移动 WS 新增事件，全部来自既有真实数据源）

- `chat:queued` {position}          ← AgentRunLedger.acquire() 的 queued 事件
- `chat:queued` {attempt, wait_seconds, reason} ← 让位闸 onWait（等待 Agent 空闲）
- `chat:reasoning` {content}        ← 管线 event_emitter("reasoning", ...)

红：这些事件今日一条都不发。

测试用确定性布景：先把 s-1 的台账行置为 running（占住队头），移动回合必然
排队；NEUROVA_RUN_QUEUE_WAIT=2 让排队超时快速收尾（error+done），不靠时序。
"""
from __future__ import annotations

import inspect
import json
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep
from neurova.core.identity_context import get_request_user_id

PAIRING_CODE = "MOBILE-CODE-1"
OWNER = "u-mobile"
AGENT_ID = "mobile-agent"


def _realSignature(methodName: str):
    from neurova.agent_core import Agent

    return inspect.signature(getattr(Agent, methodName))


def _checkAgainstRealSignature(agent, methodName: str, kwargs: Dict[str, Any], sink: List[dict]):
    _realSignature(methodName).bind(None, **kwargs)
    sink.append({**kwargs, "request_channel": get_request_user_id()})


class _ReasoningAgent:
    """无 chat_stream（走 agent.chat 分支）；首轮经 emitter 发 reasoning。"""

    def __init__(self) -> None:
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.calls: List[Dict[str, Any]] = []

    async def chat(self, **kwargs):
        _checkAgainstRealSignature(self, "chat", kwargs, self.calls)
        metadata = kwargs.get("metadata") or {}
        emitter = metadata.get("event_emitter")
        if callable(emitter):
            emitter("reasoning", "思考中：检索知识库")
        return {"text": "回复-1", "success": True}


@pytest.fixture(autouse=True)
def _freshRunStoreAndGate():
    """台账单例逐测重置并清空行；让位闸单例一并重置（前测的占位/计时状态不泄漏）。"""
    import asyncio

    from neurova.core import agent_run_store as ars
    from neurova.collaboration import glance_yield_rules as gyr

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
def wsClient(monkeypatch):
    agent = _ReasoningAgent()
    import neurova.api.endpoints as endpointsModule

    monkeypatch.setattr(endpointsModule, "get_agent_instance", lambda agent_id="": agent)

    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": "pair-1"},
    )

    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    client = TestClient(app)
    client.agent = agent  # type: ignore[attr-defined]
    return client


def _occupySession(sessionId: str) -> None:
    """把 s-1 的队头置为 running：移动回合必然排队，queued 事件确定性出现。"""
    from neurova.core import agent_run_store as ars

    store = ars.get_agent_run_store()
    blocker = store.intake(sessionId, OWNER, AGENT_ID, "占位轮")
    claimed = store.claim_next(sessionId)
    assert claimed == blocker, "布景失败：占位轮未被晋升 running"


class TestRunStateEvents:
    def test_queuedTurnEmitsChatQueuedWithPosition(self, wsClient, monkeypatch):
        """同会话已有运行中任务 → 移动回合排队，客户端收到 chat:queued 排队位。"""
        monkeypatch.setenv("NEUROVA_RUN_QUEUE_WAIT", "2")
        _occupySession("s-1")

        events: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            _send(ws, "第二轮", "s-1")
            try:
                deadline = time.time() + 15
                while time.time() < deadline:
                    payload = json.loads(ws.receive_text())
                    events.append(payload)
                    if payload.get("type") in ("chat:done", "error"):
                        break
            except Exception:
                pass  # 服务端 error+done 后关连接，属预期收尾

        queued = [e for e in events if e.get("type") == "chat:queued"]
        assert queued, (
            f"排队中的回合没有向客户端发任何 chat:queued：{[e.get('type') for e in events]}——"
            "移动中继绕过台账，排队卡无数据源")
        assert all(e.get("session_id") == "s-1" for e in queued)
        assert any(e.get("position") is not None for e in queued), queued

    def test_reasoningEventsForwardedAsChatReasoning(self, wsClient):
        """管线 event_emitter 的 reasoning 事件必须以 chat:reasoning 到达客户端。"""
        events: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "chat:send", "content": "第一轮", "session_id": "s-1"})
            deadline = time.time() + 15
            while time.time() < deadline:
                payload = json.loads(ws.receive_text())
                events.append(payload)
                if payload.get("type") == "chat:done":
                    break

        reasoning = [e for e in events if e.get("type") == "chat:reasoning"]
        assert reasoning, (
            f"管线 reasoning 事件未转发：{[e.get('type') for e in events]}")
        assert any("思考中" in (e.get("content") or "") for e in reasoning)


def _send(ws, content: str, sessionId: str) -> None:
    ws.send_json({"type": "chat:send", "content": content, "session_id": sessionId})
