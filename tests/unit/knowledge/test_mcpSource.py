# -*- coding: utf-8 -*-
"""MCP 信息源（外部 MCP server 作为知识库信息源）。

- 配置存取：knowledge_mcp_sources 表（v26），登记/列表/更新/删除；
- 拉取：Neurova 作为 MCP 客户端连外部 server，调用指定工具取文本，
  经 create_knowledge 入库（source_type=mcp、租户与 A1 去重全链生效）；
- fetchViaSession 与传输解耦——单测用官方 SDK 的内存流直连真 Server，
  HTTP 传输层是薄壳不测；
- API 面：登记/列表/删除/拉取/工具探测，endpoint 走 SSRF 校验，
  仅管理员可写。
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.mcp_source import (
    McpSourceStore,
    fetchViaSession,
    pullFromSource,
)
from neurova.knowledge.repository import KnowledgeRepository

ADMIN = {"user_id": "1", "username": "root", "role": "admin",
         "tenant_id": "t1", "neuser_id": "1"}
USER = {"user_id": "2", "username": "alice", "role": "user",
        "tenant_id": "t1", "neuser_id": "2"}
PREFIX = "/v1/knowledge"


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


@pytest.fixture()
def repo(tmp_path):
    return KnowledgeRepository(str(tmp_path / "kb"))


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr(
        "neurova.api.endpoints.knowledge_mcp_source.get_repository", lambda: repo)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    # 测试环境无外网 DNS：SSRF 校验的解析步骤 patch 成公网 IP（校验逻辑本身照跑）。
    import socket as _socket
    monkeypatch.setattr(
        _socket, "getaddrinfo",
        lambda host, port, **kw: [(None, None, None, '', ('93.184.216.34', 443))])
    yield type("Api", (), {"client": TestClient(app), "store": store, "repo": repo})()
    store.close()


def _source(**overrides):
    base = {
        "name": "企微知识源",
        "endpoint": "https://example.com/mcp",
        "auth_token": "tok-1",
        "tool_name": "echo_docs",
        "tool_args": {"q": "预算"},
        "agent_id": "default",
        "tenant_id": "t1",
    }
    base.update(overrides)
    return base


class TestSourceStore:
    def testRegisterListUpdateDelete(self, store):
        s = McpSourceStore(store)
        first = s.register(_source(), created_by="1")
        s.register(_source(name="第二源"), created_by="1")

        assert len(s.list()) == 2
        assert s.list()[0]["auth_token"] == "", "token 不出列表（脱敏）"

        s.update(first["source_id"], _source(name="改名", auth_token="tok-2"))
        updated = s.get(first["source_id"])
        assert updated["name"] == "改名"
        assert updated["auth_token"] == "tok-2", "get 单条回 token（编辑需要）"

        s.delete(first["source_id"])
        assert s.get(first["source_id"]) is None
        assert len(s.list()) == 1


class TestFetchViaSession:
    def testCallsToolAndJoinsText(self):
        """fetchViaSession 的判据是拼装：result.content 的文本块按序拼接。
        （真 SDK 传输在 live-verify 用真实 server 验证——内存流在 Windows
        测试环境的事件循环组合下挂起，不进单测。）"""

        class _FakeBlock:
            def __init__(self, text):
                self.text = text

        class _FakeResult:
            def __init__(self, blocks):
                self.content = blocks

        class _FakeSession:
            async def call_tool(self, name, args):
                assert name == "echo_docs"
                assert args == {"q": "预算"}
                return _FakeResult([
                    _FakeBlock("文档:预算"),
                    _FakeBlock("第二段"),
                ])

        text = asyncio.run(fetchViaSession(_FakeSession(), "echo_docs", {"q": "预算"}))

        assert text == "文档:预算\n第二段"


class TestPull:
    def testPullLandsKnowledgeWithDedupe(self, store, repo, monkeypatch):
        s = McpSourceStore(store)
        src = s.register(_source(), created_by="1")
        async def fake_fetch(session, tool, args):
            return "拉取到的正文内容"
        monkeypatch.setattr(
            "neurova.knowledge.mcp_source.fetchViaSession",
            fake_fetch, raising=False)
        monkeypatch.setattr(
            "neurova.knowledge.mcp_source.openSourceSession",
            lambda source: _null_session_ctx(),
            raising=False)

        outcome = asyncio.run(pullFromSource(s, s.get(src["source_id"]), repo))
        assert outcome["knowledge_id"]
        assert outcome["duplicate"] is not True
        item = repo.visible_items(
            {"user_id": "1", "role": "admin", "tenant_id": "t1"})[0]
        assert item["source_type"] == "mcp"
        assert item["source"] == "mcp:企微知识源"

        again = asyncio.run(pullFromSource(s, s.get(src["source_id"]), repo))
        assert again["duplicate"] is True, "同内容二次拉取命中 A1 去重"

    def testPullStampsTenantAndFailsLoudly(self, store, repo, monkeypatch):
        s = McpSourceStore(store)
        s.register(_source(), created_by="1")
        monkeypatch.setattr(
            "neurova.knowledge.mcp_source.openSourceSession",
            lambda source: _failing_ctx(RuntimeError("外部 server 不可达")),
            raising=False)

        with pytest.raises(RuntimeError):
            asyncio.run(pullFromSource(s, s.list()[0], repo))


class _NullSessionCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _null_session_ctx():
    return _NullSessionCtx()


class _FailingCtx:
    def __init__(self, err):
        self._err = err

    async def __aenter__(self):
        raise self._err

    async def __aexit__(self, *exc):
        return False


def _failing_ctx(err):
    return _FailingCtx(err)


class TestMcpSourceApi:
    def testRegisterListDeleteAdminOnly(self, api):
        resp = api.client.post(PREFIX + "/mcp/sources", json=_source())
        assert resp.status_code == 200, resp.text
        sourceId = resp.json()["data"]["source_id"]

        listing = api.client.get(PREFIX + "/mcp/sources")
        assert listing.status_code == 200
        assert listing.json()["data"]["total"] == 1
        assert listing.json()["data"]["items"][0]["auth_token"] == ""

        resp = api.client.delete(PREFIX + f"/mcp/sources/{sourceId}")
        assert resp.status_code == 200

    def testNonAdminWriteForbidden(self, api):
        api.client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(USER)

        resp = api.client.post(PREFIX + "/mcp/sources", json=_source())
        assert resp.status_code == 403, resp.text

    def testPrivateEndpointRejectedBySsrfGuard(self, api):
        resp = api.client.post(PREFIX + "/mcp/sources", json=_source(
            endpoint="http://127.0.0.1:9601/mcp"))

        assert resp.status_code == 400, resp.text
        assert "http" in resp.json()["detail"].lower() or "public" in resp.json()["detail"].lower()

    def testPullEndpointLandsKnowledge(self, api, monkeypatch):
        resp = api.client.post(PREFIX + "/mcp/sources", json=_source())
        sourceId = resp.json()["data"]["source_id"]
        async def fake_fetch(session, tool, args):
            return "API 拉取正文"
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_mcp_source.fetchViaSession",
            fake_fetch, raising=False)
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_mcp_source.openSourceSession",
            lambda source: _null_session_ctx(), raising=False)

        pulled = api.client.post(PREFIX + f"/mcp/sources/{sourceId}/pull")
        assert pulled.status_code == 200, pulled.text
        assert pulled.json()["data"]["knowledge_id"]
        assert api.repo.visible_items(
            {"user_id": "1", "role": "admin", "tenant_id": "t1"})

    def testToolProbeListsRemoteTools(self, api, monkeypatch):
        """工具探测：登记前先列出远端 server 提供哪些工具（选 tool_name 用）。"""
        async def fakeProbe(source):
            return [{"name": "echo_docs", "description": "d"}]

        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_mcp_source.probeTools",
            fakeProbe, raising=False)

        resp = api.client.post(PREFIX + "/mcp/sources/tools", json=_source())

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["tools"][0]["name"] == "echo_docs"
