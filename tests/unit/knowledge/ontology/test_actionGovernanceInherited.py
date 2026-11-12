# -*- coding: utf-8 -*-
"""W4 治理链继承（specs/2026-11-12 §6，D5 门面转交）：MCP ontology_act 在册；
动作执行转交 ToolExecutor.execute 单管道（治理/审批/审计/mcp_grants 全继承，
门面自身不复制判定）；审批重放 skip_governance 语义不动。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.action_registry import ActionRegistry

_SERVICE_TOKEN = "test-mcp-service-token"


@pytest.fixture()
def mcp_store():
    s = KnowledgeFactStore(":memory:")
    applyTo(s._conn)
    yield s
    s.close()


@pytest.fixture()
def asgi_app(mcp_store, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    import neurova.mcp_ontology_server as mod

    monkeypatch.setattr(mod, "_store", lambda: mcp_store)
    # 门面转交链路的替身：agent 解析与执行器都打桩，动作行在册
    reg = ActionRegistry(mcp_store)
    reg.upsert(actionId="echo_action", label="回声", boundTool="noop_tool",
               registeredTools=["noop_tool"])
    monkeypatch.setattr(mod, "_resolveAgentForActions",
                        lambda agentId: {"executor": _FakeExecutor(), "agent": None})
    from neurova.mcp_ontology_server import build_ontology_mcp_asgi

    asgi_entry, lifespan_cm = build_ontology_mcp_asgi()
    return {"asgi": asgi_entry, "lifespan": lifespan_cm}


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, tool_name, params):
        self.calls.append((tool_name, params))
        return {"success": True, "result": "echoed"}


def _client(app, headers):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 9))
    return httpx.AsyncClient(transport=transport, headers=headers,
                             base_url="http://127.0.0.1:9")


@asynccontextmanager
async def _session(app, headers):
    http_client = _client(app, headers)
    async with streamable_http_client("http://127.0.0.1:9/", http_client=http_client) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield session, http_client


class TestMcpOntologyAct:
    @pytest.mark.asyncio
    async def test_actInRegistryAndDelegates(self, asgi_app):
        """ontology_act 在册；门面转交（不复制执行语义）。"""
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            tools = await session.list_tools()
            assert "ontology_act" in {t.name for t in tools.tools}
            res = await session.call_tool(
                "ontology_act", {"action_id": "echo_action", "params_json": "{}"})
            payload = json.loads(res.content[0].text)
            assert payload.get("executed") is True, payload

    @pytest.mark.asyncio
    async def test_unknownActionStructuredReject(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "ontology_act", {"action_id": "ghost_action", "params_json": "{}"})
            payload = json.loads(res.content[0].text)
            assert payload.get("rejected") is True and payload.get("detail")
