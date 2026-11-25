# -*- coding: utf-8 -*-
"""KNOW-04：MCP 知识信息源全操作按租户校验归属。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-04）：McpSourceStore 的
list/get/update/delete/markPulled 均无 tenant；API 限 admin 但 admin 可为任意
tenant，且请求体可指定 tenant_id——跨租户读取、修改、删除、拉取信息源。
判据：tenant 从认证上下文注入；所有操作校验归属（他租户源不可见、不可改、
不可删、不可拉）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.mcp_source import McpSourceStore

T1_ADMIN = {"user_id": "1", "username": "root", "role": "admin",
            "tenant_id": "t1", "neuser_id": "1"}
T2_ADMIN = {"user_id": "3", "username": "root2", "role": "admin",
            "tenant_id": "t2", "neuser_id": "3"}
PREFIX = "/v1/knowledge"


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


@pytest.fixture()
def api(tmp_path, monkeypatch):
    st = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: st)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(T1_ADMIN)
    import socket as _socket
    monkeypatch.setattr(
        _socket, "getaddrinfo",
        lambda host, port, **kw: [(None, None, None, '', ('93.184.216.34', 443))])
    yield type("Api", (), {"client": TestClient(app), "store": st})()
    st.close()


def _spec(**overrides):
    base = {"name": "源A", "endpoint": "https://example.com/mcp",
            "auth_token": "tok", "tool_name": "echo", "tool_args": {},
            "agent_id": "default", "tenant_id": "t1"}
    base.update(overrides)
    return base


class TestStoreTenantScope:
    def test_listFiltersByTenant(self, store):
        s = McpSourceStore(store)
        s.register(_spec(name="t1源"), created_by="1")
        s.register(_spec(name="t2源", tenant_id="t2"), created_by="3")

        t1Names = [r["name"] for r in s.list(tenantId="t1")]
        t2Names = [r["name"] for r in s.list(tenantId="t2")]
        assert t1Names == ["t1源"], "t1 列表只见 t1 源"
        assert t2Names == ["t2源"], "t2 列表只见 t2 源"

    def test_getRejectsWrongTenant(self, store):
        s = McpSourceStore(store)
        src = s.register(_spec(), created_by="1")
        assert s.get(src["source_id"], tenantId="t1") is not None
        assert s.get(src["source_id"], tenantId="t2") is None, \
            "他租户不得读取信息源（含 token）"

    def test_updateRejectsWrongTenant(self, store):
        s = McpSourceStore(store)
        src = s.register(_spec(name="原名"), created_by="1")
        assert s.update(src["source_id"], _spec(name="篡改"), tenantId="t2") \
            is None, "他租户更新必须落空"
        assert s.get(src["source_id"], tenantId="t1")["name"] == "原名"

    def test_deleteRejectsWrongTenant(self, store):
        s = McpSourceStore(store)
        src = s.register(_spec(), created_by="1")
        s.delete(src["source_id"], tenantId="t2")
        assert s.get(src["source_id"], tenantId="t1") is not None, \
            "他租户删除不得生效"

    def test_markPulledIsTenantScoped(self, store):
        s = McpSourceStore(store)
        src = s.register(_spec(), created_by="1")
        s.markPulled(src["source_id"], "ok", tenantId="t2")
        assert s.get(src["source_id"], tenantId="t1")["last_status"] == "never", \
            "他租户不得改写拉取状态"


class TestApiTenantAcl:
    def test_registerTenantFromAuthContext(self, api):
        """请求体 tenant_id 不再决定归属：tenant 从认证上下文注入。"""
        resp = api.client.post(PREFIX + "/mcp/sources",
                               json=_spec(tenant_id="t2"))
        assert resp.status_code == 200, resp.text
        sourceId = resp.json()["data"]["source_id"]
        row = api.store._conn.execute(
            "SELECT tenant_id FROM knowledge_mcp_sources WHERE source_id = ?",
            (sourceId,)).fetchone()
        assert row["tenant_id"] == "t1", "归属租户＝认证上下文租户，不是请求体自报"

    def test_listScopedToCallerTenant(self, api):
        api.client.post(PREFIX + "/mcp/sources", json=_spec())
        api.client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(T2_ADMIN)
        listing = api.client.get(PREFIX + "/mcp/sources")
        assert listing.json()["data"]["total"] == 0, "t2 管理员看不到 t1 的源"

    def test_crossTenantPullIs404(self, api, monkeypatch):
        resp = api.client.post(PREFIX + "/mcp/sources", json=_spec())
        sourceId = resp.json()["data"]["source_id"]
        api.client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(T2_ADMIN)
        pulled = api.client.post(PREFIX + f"/mcp/sources/{sourceId}/pull")
        assert pulled.status_code == 404, "他租户拉取按不存在处理（不泄露存在性）"
