# -*- coding: utf-8 -*-
"""移动 WS 通道对齐 PC 对话页能力契约档（产出物/回合控制/模型列表/上下文面板/用量）。

## 缺陷形状（红灯实证）

mobile `chat:send` 只收 content/agent_id/session_id——PC console 面（console.py
ChatRequest）的 model / thinking_effort / permission_mode / task_profile 四个回合
控制字段在移动通道被静默丢弃（管线消费点全部现成：chat_pipeline.py:946
permission_mode、2650 task_profile、2697 thinking_effort；model 走 agent.chat(model=)
热切换 console.py:1134 同款）。`_pump` 只转发 6 种管线事件——console 从 tool_result
派生的 artifact / plan_update / approval_required 三个增强事件与收尾 usage 事件在
移动端缺失（产出物列表整条断链）。`/v1/context/*` 与 `/v1/models` 是 JWT 面，
移动 WS 凭证不可直调——需要 WS 代理消息类型。

## 判据形状

沿用本目录契约档的防漂姿势：替身按 `Agent.chat` 真签名 bind。回合控制字段断言
逐条落在替身 captured kwargs 上；派生事件断言落在 WS 帧序列上；artifact 内容取回
断言属主放行与越权 404 同型（对齐 artifacts_api._get_owned_artifact 的 IDOR 口径）。
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep
from neurova.core.identity_context import get_request_user_id

PAIRING_CODE = "MOBILE-PARITY-1"
OWNER = "u-parity"
AGENT_ID = "parity-agent"
REPLY_TEXT = "## 完成\n\n产出已生成"


def _checkAgainstRealSignature(kwargs: Dict[str, Any], sink: List[dict]) -> None:
    """按真 `Agent.chat` 的签名 bind 一遍：参数名不对、必填没给，都在这一步抛。"""
    from neurova.agent_core import Agent

    inspect.signature(Agent.chat).bind(None, **kwargs)
    sink.append({**kwargs, "request_channel": get_request_user_id()})


class _ParityAgent:
    """发 tool_call/tool_result（含可提取产物路径）并记录全部入参的替身回合。"""

    def __init__(self, resultContent: Any) -> None:
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.calls: List[Dict[str, Any]] = []
        self.resultContent = resultContent

    async def chat(self, **kwargs):
        _checkAgainstRealSignature(kwargs, self.calls)
        emit = kwargs["metadata"]["event_emitter"]
        emit("tool_call", {"name": "file_operation", "arguments": "{}"})
        emit("tool_result", {"role": "tool", "name": "file_operation",
                             "content": self.resultContent})
        emit("content", REPLY_TEXT)
        return {"text": REPLY_TEXT, "success": True}


@pytest.fixture(autouse=True)
def _freshRunStateSingletons():
    """台账/让位闸单例逐测重置；产物注册表逐测清空（注册表是模块级单例）。"""
    import asyncio

    from neurova.collaboration import glance_yield_rules as gyr
    from neurova.core import agent_run_store as ars
    from neurova.api.endpoints import artifacts_api

    asyncio.run(gyr.reset_glance_yield_checker())
    ars.reset_agent_run_store()
    store = ars.get_agent_run_store()
    with store._lock:
        store._conn.execute("DELETE FROM agent_runs")
        store._conn.commit()
    yield
    artifacts_api._artifacts_store.clear()
    asyncio.run(gyr.reset_glance_yield_checker())
    ars.reset_agent_run_store()
    store = ars.get_agent_run_store()
    with store._lock:
        store._conn.execute("DELETE FROM agent_runs")
        store._conn.commit()


@pytest.fixture()
def wsClient(monkeypatch):
    agentHolder: Dict[str, Any] = {}

    def _install(agent: _ParityAgent) -> None:
        agentHolder["agent"] = agent
        import neurova.api.endpoints as endpointsModule

        monkeypatch.setattr(endpointsModule, "get_agent_instance",
                            lambda agent_id="": agent)

    wsState = {"install": _install, "agentHolder": agentHolder}

    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": "pair-parity-1"},
    )

    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    client = TestClient(app)
    client.wsState = wsState  # type: ignore[attr-defined]
    return client


def _drive(client, sendMsg: Dict[str, Any],
           followUps: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """一个 WS 连接内：chat:send 读到 done，再逐条发 followUps 各读一帧。"""
    events: List[Dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
        ws.send_json(sendMsg)
        while True:
            payload = json.loads(ws.receive_text())
            events.append(payload)
            if payload.get("type") in ("chat:done", "error"):
                break
        for extra in (followUps or []):
            ws.send_json(extra)
            events.append(json.loads(ws.receive_text()))
    return events


def _artifactFile() -> Path:
    """在 agent 工作区白名单根内落一个真实文件（注册与取回都要磁盘存在）。"""
    from neurova.core.agent_workspaces import get_agent_workspace_dir

    wsDir = Path(get_agent_workspace_dir(AGENT_ID))
    wsDir.mkdir(parents=True, exist_ok=True)
    target = wsDir / "parity_report.md"
    target.write_bytes("# 报告\n\n正文".encode("utf-8"))
    return target


class TestTurnControlFieldsReachThePipeline:
    def test_modelEffortPermissionProfileAllArrive(self, wsClient, monkeypatch):
        wsClient.wsState["install"](_ParityAgent({"success": True, "note": "x"}))
        _drive(wsClient, {"type": "chat:send", "content": "干一件事",
                          "agent_id": AGENT_ID, "session_id": "s-parity-1",
                          "model": "gpt-x",
                          "thinking_effort": "deep",
                          "permission_mode": "plan",
                          "task_profile": "heavy"})

        assert wsClient.wsState["agentHolder"]["agent"].calls, "一轮都没打到 agent"
        call = wsClient.wsState["agentHolder"]["agent"].calls[0]
        assert call.get("model") == "gpt-x", (
            f"chat:send 的 model 没走 agent.chat(model=) 热切换通道：{sorted(call)}")
        metadata = call.get("metadata") or {}
        assert metadata.get("thinking_effort") == "deep", (
            f"thinking_effort 被丢弃（metadata keys={sorted(metadata)}）")
        assert metadata.get("permission_mode") == "plan", (
            f"permission_mode 被丢弃（管线 chat_pipeline.setRequestPermissionMode "
            f"有现成消费点）：{sorted(metadata)}")
        assert metadata.get("task_profile") == "heavy", (
            f"task_profile 被丢弃（turn_profile 有现成消费点）：{sorted(metadata)}")

    def test_emptyFieldsAreNotInjected(self, wsClient):
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        _drive(wsClient, {"type": "chat:send", "content": "默认回合",
                          "agent_id": AGENT_ID, "session_id": "s-parity-2"})
        metadata = wsClient.wsState["agentHolder"]["agent"].calls[0].get("metadata") or {}
        assert "permission_mode" not in metadata, metadata
        assert "task_profile" not in metadata, metadata

    def test_invalidPermissionModeRejectedBeforeTurn(self, wsClient):
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        events = _drive(wsClient, {"type": "chat:send", "content": "越权模式",
                                   "agent_id": AGENT_ID, "session_id": "s-parity-3",
                                   "permission_mode": "root"})
        errors = [e for e in events if e.get("type") == "error"]
        assert errors, f"非法 permission_mode 未被拒绝：{events}"
        assert errors[0].get("code") == "invalid_permission_mode", errors[0]
        assert not wsClient.wsState["agentHolder"]["agent"].calls, (
            "拒绝后仍打了 agent——非法字段必须在回合前拦截")


class TestDerivedEventsReachTheMobileWire:
    def test_artifactDerivedFromToolResult(self, wsClient):
        target = _artifactFile()
        wsClient.wsState["install"](_ParityAgent(
            json.dumps({"success": True, "file_path": str(target)})))
        events = _drive(wsClient, {"type": "chat:send", "content": "写个报告",
                                   "agent_id": AGENT_ID, "session_id": "s-parity-4"})

        artifacts = [e for e in events if e.get("type") == "chat:artifact"]
        assert artifacts, (
            f"tool_result 里的产出没有被派生为 artifact 事件（kinds="
            f"{[e.get('type') for e in events]}）——产出物列表在移动端整条断链")
        data = artifacts[0]["data"]
        assert data.get("artifact_id"), data
        assert data.get("kind") == "markdown", data
        assert data.get("name") == "parity_report.md", data

    def test_planUpdateDerivedFromToolResult(self, wsClient):
        wsClient.wsState["install"](_ParityAgent(json.dumps({
            "success": True,
            "plan": [{"step": "读源码", "status": "done"},
                     {"step": "写契约档", "status": "pending"}],
            "explanation": "两步走"})))
        events = _drive(wsClient, {"type": "chat:send", "content": "做个计划",
                                   "agent_id": AGENT_ID, "session_id": "s-parity-5"})
        plans = [e for e in events if e.get("type") == "chat:plan_update"]
        assert plans, f"update_plan 结果没有派生 plan_update 事件：{[e.get('type') for e in events]}"
        assert plans[0]["data"]["plan"][0]["step"] == "读源码", plans[0]
        assert plans[0]["data"].get("explanation") == "两步走", plans[0]

    def test_usageEventArrivesBeforeDone(self, wsClient, monkeypatch):
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        stub = SimpleNamespace(last_call=lambda: {
            "model": "test-model", "provider": "stub",
            "prompt_tokens": 120, "completion_tokens": 45,
            "total_tokens": 165, "estimated": False})
        monkeypatch.setattr("neurova.core.usage_accounting.get_usage_accounting",
                            lambda: stub)
        events = _drive(wsClient, {"type": "chat:send", "content": "记一下用量",
                                   "agent_id": AGENT_ID, "session_id": "s-parity-6"})
        kinds = [e.get("type") for e in events]
        assert "chat:usage" in kinds, f"usage 事件缺失：{kinds}"
        assert kinds.index("chat:usage") < kinds.index("chat:done"), kinds
        usage = next(e for e in events if e["type"] == "chat:usage")["data"]
        assert usage["total_tokens"] == 165 and usage["estimated"] is False, usage


class TestWsProxiedQueries:
    def test_artifactContentOwnedAllowed(self, wsClient):
        target = _artifactFile()
        wsClient.wsState["install"](_ParityAgent(
            json.dumps({"success": True, "file_path": str(target)})))
        events = _drive(wsClient,
                        {"type": "chat:send", "content": "写报告", "agent_id": AGENT_ID,
                         "session_id": "s-parity-7"},
                        followUps=[{"type": "artifact:get", "artifact_id": "pending"}])
        # 先从派生事件拿真实 artifact_id 再回查（占位 followUp 的结果丢弃后重查）
        artifacts = [e for e in events if e.get("type") == "chat:artifact"]
        assert artifacts, events
        realId = artifacts[0]["data"]["artifact_id"]
        withClient = wsClient
        results: List[Dict[str, Any]] = []
        with withClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "artifact:get", "artifact_id": realId})
            results.append(json.loads(ws.receive_text()))
        assert results[0]["type"] == "artifact:content_result", results[0]
        assert results[0]["content"] == "# 报告\n\n正文", results[0]
        assert results[0]["encoding"] == "utf8", results[0]

    def test_artifactContentForeignDenied(self, wsClient):
        from neurova.api.endpoints.artifacts_api import register_artifact

        target = _artifactFile()
        info = register_artifact(str(target), agent_id=AGENT_ID, user_id="someone-else")
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        results: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "artifact:get", "artifact_id": info["artifact_id"]})
            results.append(json.loads(ws.receive_text()))
        assert results[0]["type"] == "error", results[0]
        assert results[0].get("code") == "artifact_not_found", results[0]

    def test_modelListOverWs(self, wsClient, monkeypatch):
        modelStub = SimpleNamespace(
            id="nex-n2.6", name="Nex N2.6", owned_by="moss",
            capabilities=["text"], context_window=131072, max_tokens=8192,
            max_output_tokens=None, max_output_tokens_source="",
            max_output_tokens_probed_at="", is_active=True, status="available",
            metadata={"connectable": True})
        managerStub = SimpleNamespace(get_all_models=lambda: [modelStub])
        monkeypatch.setattr("neurova.llm.provider_manager.get_provider_manager_for_user",
                            lambda user: managerStub)
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        results: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "model:list"})
            results.append(json.loads(ws.receive_text()))
        assert results[0]["type"] == "model:list_result", results[0]
        models = results[0]["models"]
        assert models and models[0]["model_id"] == "nex-n2.6", models
        assert models[0]["provider"] == "moss" and models[0]["connectable"] is True, models

    def test_contextCompositionOverWs(self, wsClient, monkeypatch):
        composition = {"agent_id": AGENT_ID, "total_tokens": 9000,
                       "context_window": 131072,
                       "messages": {"buckets": {"user": {"count": 4, "tokens": 3000}},
                                    "total_tokens": 6000},
                       "tools": {"system": {"count": 2, "tokens": 1500}},
                       "cache_hit_rate": 0.42, "cache_source": "stub"}
        monkeypatch.setattr("neurova.context.composition.get_last_composition",
                            lambda agent_id, session_id: composition)
        monkeypatch.setattr("neurova.context.composition.estimate_composition_from_history",
                            lambda agent_id, session_id: None)
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        results: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "context:composition", "agent_id": AGENT_ID,
                          "session_id": "s-parity-8"})
            results.append(json.loads(ws.receive_text()))
        assert results[0]["type"] == "context:composition_result", results[0]
        assert results[0]["data"]["total_tokens"] == 9000, results[0]
        assert results[0]["data"]["cache_hit_rate"] == 0.42, results[0]

    def test_contextCompositionNoDataIsHonest(self, wsClient, monkeypatch):
        monkeypatch.setattr("neurova.context.composition.get_last_composition",
                            lambda agent_id, session_id: None)
        monkeypatch.setattr("neurova.context.composition.estimate_composition_from_history",
                            lambda agent_id, session_id: None)
        wsClient.wsState["install"](_ParityAgent({"success": True}))
        results: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "context:composition", "agent_id": AGENT_ID,
                          "session_id": "s-parity-9"})
            results.append(json.loads(ws.receive_text()))
        assert results[0]["type"] == "context:composition_result", results[0]
        assert results[0]["data"] is None, results[0]
        assert results[0].get("reason") == "no_data", results[0]
