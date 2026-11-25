# -*- coding: utf-8 -*-
"""P0-02：本体 MCP 的租户、Agent 属主与请求身份边界。

协议用例走真实 MCP SDK + ASGITransport；断言拒绝发生在执行/写入之前，
而不是事后从结果里过滤越权数据。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture()
def mcpStore():
    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield store
    store.close()


@pytest.fixture()
def aliceIdentity(monkeypatch, mcpStore):
    import neurova.mcp_ontology_server as mod

    user = {
        "user_id": "u_alice",
        "username": "alice",
        "role": "user",
        "tenant_id": "tenant_alice",
        "auth_source": "jwt",
    }
    monkeypatch.setattr(mod, "_resolveIdentity", lambda scope: _resolved(user))
    monkeypatch.setattr(mod, "_store", lambda: mcpStore)
    return user


async def _resolved(user):
    return user


@pytest.fixture()
def asgiApp(aliceIdentity):
    from neurova.mcp_ontology_server import build_ontology_mcp_asgi

    asgi, lifespan = build_ontology_mcp_asgi()
    return {"asgi": asgi, "lifespan": lifespan}


@asynccontextmanager
async def _session(app):
    transport = httpx.ASGITransport(app=app["asgi"], client=("127.0.0.1", 9))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:9"
    ) as http:
        async with streamable_http_client(
            "http://127.0.0.1:9/", http_client=http
        ) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                yield session


async def _call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    return json.loads(result.content[0].text)


def _registerAction(store):
    from neurova.knowledge.ontology.action_registry import getActionRegistry

    getActionRegistry(store).upsert(
        "cancel_order",
        label="取消订单",
        boundTool="builtin:exec",
        riskTier="low",
        tenantId="tenant_alice",
    )


@pytest.mark.asyncio
async def test_asgiBoundaryPublishesSenderIdentity(monkeypatch, aliceIdentity):
    """ASGI 边界必须把 sender 写进唯一请求身份 ContextVar。"""
    import neurova.mcp_ontology_server as mod
    from neurova.core.identity_context import get_request_user_id

    async def readIdentity(request):
        return JSONResponse({"sender": get_request_user_id()})

    subApp = Starlette(routes=[Route("/", readIdentity)])
    monkeypatch.setattr(
        mod,
        "_SERVER",
        SimpleNamespace(streamable_http_app=lambda **kwargs: subApp),
    )
    asgi, _ = mod.build_ontology_mcp_asgi()
    transport = httpx.ASGITransport(app=asgi, client=("127.0.0.1", 9))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:9"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"sender": "u_alice"}


def test_agentResolverUsesCanonicalOwnerAcl(monkeypatch, aliceIdentity):
    """Agent 域解析复用唯一 can_access_agent，不另写属主比较。"""
    import neurova.mcp_ontology_server as mod
    from neurova.api import agent_access

    monkeypatch.setattr(
        agent_access,
        "agentOwnerById",
        lambda agentId: "u_bob" if agentId == "agent_bob" else "u_alice",
    )
    with pytest.raises(PermissionError):
        mod._agentIdOf(aliceIdentity, "agent_bob")
    assert mod._agentIdOf(aliceIdentity, "agent_alice") == "agent_alice"


@pytest.mark.asyncio
async def test_crossAgentActionRejectedBeforeExecutor(
    asgiApp, mcpStore, aliceIdentity, monkeypatch
):
    import neurova.mcp_ontology_server as mod

    _registerAction(mcpStore)
    resolved = []

    def resolveForActions(agentId):
        resolved.append(agentId)
        return None

    monkeypatch.setattr(mod, "_resolveAgentForActions", resolveForActions)
    async with asgiApp["lifespan"](asgiApp["asgi"]), _session(asgiApp) as session:
        payload = await _call(
            session,
            "ontology_act",
            {"action_id": "cancel_order", "agent_id": "agent_bob"},
        )
    assert payload.get("rejected") is True, payload
    assert payload.get("code") == "agent_access_denied", payload
    assert resolved == [], "越权动作不得解析或触达执行载体"


@pytest.mark.asyncio
async def test_crossAgentFactWriteRejectedBeforeAdmission(asgiApp, mcpStore):
    before = mcpStore._conn.execute("SELECT COUNT(*) FROM knowledge_facts").fetchone()[0]
    async with asgiApp["lifespan"](asgiApp["asgi"]), _session(asgiApp) as session:
        payload = await _call(
            session,
            "fact_submit",
            {
                "subject_label": "订单D01",
                "predicate_term_id": "is_a",
                "object_term": "Order",
                "evidence_text": "订单D01 is_a Order",
                "agent_id": "agent_bob",
            },
        )
    after = mcpStore._conn.execute("SELECT COUNT(*) FROM knowledge_facts").fetchone()[0]
    assert payload.get("code") == "agent_access_denied", payload
    assert after == before, "越权事实不得写入存储"


@pytest.mark.asyncio
async def test_crossAgentTeamToolRejectedBeforeNativePipeline(
    asgiApp, monkeypatch
):
    import neurova.mcp_ontology_server as mod

    calls = []

    class Executor:
        async def execute(self, nativeName, params):
            calls.append((nativeName, params))
            return {"success": True}

    monkeypatch.setattr(
        mod,
        "_resolveAgentForActions",
        lambda agentId: {"executor": Executor(), "agent": None},
    )
    async with asgiApp["lifespan"](asgiApp["asgi"]), _session(asgiApp) as session:
        payload = await _call(session, "team_list", {"agent_id": "agent_bob"})
    assert payload.get("code") == "agent_access_denied", payload
    assert calls == [], "越权团队工具不得进入原生执行管道"


@pytest.mark.asyncio
async def test_crossAgentDerivationRejected(asgiApp):
    async with asgiApp["lifespan"](asgiApp["asgi"]), _session(asgiApp) as session:
        payload = await _call(
            session,
            "ontology_derive",
            {"subject_label": "订单D01", "agent_id": "agent_bob"},
        )
    assert payload.get("code") == "agent_access_denied", payload


@pytest.mark.asyncio
async def test_simulationDropsClientIdentityAndPassesTrustedIdentity(
    asgiApp, monkeypatch
):
    """客户端 scope 的 tenant/agent 不得保留；可信身份单独显式传入。"""
    import neurova.knowledge.ontology.simulation as simulation
    from neurova.api import agent_access

    monkeypatch.setattr(
        agent_access, "agentOwnerById", lambda agentId: "u_alice"
    )
    captured = {}

    def runSimulation(store, scope, hypotheses, **kwargs):
        captured.update(scope=dict(scope), hypotheses=hypotheses, kwargs=kwargs)
        return {"simulation_id": "sim_isolated"}

    monkeypatch.setattr(simulation, "runSimulation", runSimulation)
    async with asgiApp["lifespan"](asgiApp["asgi"]), _session(asgiApp) as session:
        payload = await _call(
            session,
            "ontology_simulate",
            {
                "scope_json": json.dumps(
                    {
                        "agentId": "agent_bob",
                        "tenantId": "tenant_bob",
                        "subjectKeys": ["订单D01"],
                    }
                ),
                "hypotheses_json": "{}",
            },
        )
    assert payload == {"simulation_id": "sim_isolated"}
    assert "agentId" not in captured["scope"]
    assert "tenantId" not in captured["scope"]
    assert captured["scope"]["subjectKeys"] == ["订单D01"]
    assert captured["kwargs"]["trustedIdentity"] == {
        "agentId": "default",
        "tenantId": "tenant_alice",
    }


def test_simulationRejectsConflictingClientIdentity():
    """直接调用 simulation 时，冲突 scope 身份也必须显式失败。"""
    from neurova.knowledge.ontology.simulation import runSimulation

    with pytest.raises(ValueError, match="trustedIdentity"):
        runSimulation(
            None,
            scope={"agentId": "agent_bob", "tenantId": "tenant_bob"},
            hypotheses={},
            trustedIdentity={"agentId": "agent_alice", "tenantId": "tenant_alice"},
        )
