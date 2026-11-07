# -*- coding: utf-8 -*-
"""批 C5：ERP REST 连接器（2026-11-07 裁定 §2.4-2：先金蝶与用友，httpx 不引 SDK）。

判据（立项方案 §3-C5）：两 vendor 各「登录→分页拉两批→游标推进→hasMore 收束」
全链；会话过期自动重登一次再失败才 error；429 具名退避；凭据不落日志与描述符；
空批显式 hasMore=False；describeSchema 列集来自 fieldKeys。
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock

import httpx
import pytest

from neurova.knowledge.enterprise.connectors_erp import ErpRestAdapter
from neurova.knowledge.enterprise.schema_mapping import MappingError


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _erpCredentials(monkeypatch):
    """认证流测试统一注入凭据 env（值不进描述符——正是被测纪律）。"""
    monkeypatch.setenv("ERP_USER", "kuai")
    monkeypatch.setenv("ERP_PASS", "s3cret-pw")


def _descriptor(vendor="kingdee", **overrides):
    descriptor = {
        "sourceId": "erp_orders", "tenantId": "default", "sourceType": "erp_api",
        "vendor": vendor,
        "baseUrl": "https://erp.example.local",
        "loginPath": "/login", "queryPath": "/query",
        "tokenPath": "/token", "listPath": "/list",
        "columns": ["order_id", "status"],
        "formId": "SAL_OUTSTOCK",
        "credentialEnv": {"username": "ERP_USER", "password": "ERP_PASS"},
        "subject": {"template": "erp:{order_id}"},
        "predicate": {"termId": "has_status"},
        "object": {"column": "status", "kind": "column"},
        "qualifiers": {}, "enabled": True, "agentId": "default",
    }
    descriptor.update(overrides)
    return descriptor


def _kingdeeTransport(state):
    """金蝶形状的 MockTransport：/login 换会话；/query 按 StartRow 分页。"""

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"] += 1
        if request.url.path.endswith("/login"):
            state["logins"] += 1
            if state.get("login_should_fail"):
                return httpx.Response(200, json={"ErrorCode": 500, "errors": "bad creds"})
            return httpx.Response(200, json={"Context": {"SessionId": "s1"}},
                                  headers={"Set-Cookie": "kdsvc-sessionid=abc"})
        if request.url.path.endswith("/query"):
            if state.get("expire_next") and state["requests"] > state["expire_at"]:
                state["expire_next"] = False
                return httpx.Response(401, json={"ErrorCode": 500, "errors": "session expired"})
            body = json.loads(request.content.decode("utf-8"))
            start = int(body.get("StartRow") or 0)
            limit = int(body.get("Limit") or 2)
            all_rows = state["rows"]
            window = all_rows[start:start + limit]
            return httpx.Response(200, json=window)
        return httpx.Response(404, json={"errors": "no route"})

    return httpx.MockTransport(handler)


class TestKingdee:
    def test_loginThenPaginateTwoBatches(self):
        state = {"rows": [{"order_id": "42", "status": "open"},
                          {"order_id": "43", "status": "closed"},
                          {"order_id": "44", "status": "open"}],
                 "logins": 0, "requests": 0}
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_kingdeeTransport(state))
        try:
            first = _run(adapter.fetchBatch(None, 2))
            assert [r["order_id"] for r in first.rows] == ["42", "43"]
            assert first.hasMore is True and state["logins"] == 1
            second = _run(adapter.fetchBatch(first.nextCursor, 2))
            assert [r["order_id"] for r in second.rows] == ["44"]
            assert second.hasMore is False
        finally:
            _run(adapter.close())

    def test_sessionExpiredRelogsOnce(self):
        state = {"rows": [{"order_id": "42", "status": "open"}],
                 "logins": 0, "requests": 0,
                 "expire_next": True, "expire_at": 1}
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_kingdeeTransport(state))
        try:
            batch = _run(adapter.fetchBatch(None, 2))
            assert len(batch.rows) == 1
            assert state["logins"] == 2, "过期后重登一次"
        finally:
            _run(adapter.close())

    def test_loginFailureIsExplicitError(self):
        state = {"rows": [], "logins": 0, "requests": 0, "login_should_fail": True}
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_kingdeeTransport(state))
        try:
            health = _run(adapter.health())
            assert health.status == "error"
        finally:
            _run(adapter.close())

    def test_emptyBatchHasMoreFalse(self):
        state = {"rows": [], "logins": 0, "requests": 0}
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_kingdeeTransport(state))
        try:
            batch = _run(adapter.fetchBatch(None, 2))
            assert batch.rows == [] and batch.hasMore is False
        finally:
            _run(adapter.close())


    def test_rateLimitedBacksOffOnceThenSucceeds(self, monkeypatch):
        import neurova.knowledge.enterprise.connectors_erp as erp_module

        monkeypatch.setattr(erp_module, "_RATE_LIMIT_BACKOFF_SECONDS", 0.0)
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/login"):
                return httpx.Response(200, json={"Context": {"SessionId": "s1"}})
            if request.url.path.endswith("/query"):
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(429, json={"errors": "slow down"})
                return httpx.Response(200, json=[{"order_id": "42", "status": "open"}])
            return httpx.Response(404)

        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            batch = _run(adapter.fetchBatch(None, 2))
            assert len(batch.rows) == 1 and calls["n"] == 2, "429 退避一次后成功（query 计 2 次）"
        finally:
            _run(adapter.close())


def _yongyouTransport(state):
    """用友形状的 MockTransport：/token 换 token；/list 按页码分页。"""

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"] += 1
        if request.url.path.endswith("/token"):
            state["logins"] += 1
            return httpx.Response(200, json={"token": "tok-1"})
        if request.url.path.endswith("/list"):
            if request.headers.get("Authorization") != "Bearer tok-1":
                return httpx.Response(401, json={"message": "token invalid"})
            page = int(request.url.params.get("pageIndex") or "1")
            size = int(request.url.params.get("pageSize") or "2")
            all_rows = state["rows"]
            window = all_rows[(page - 1) * size: page * size]
            return httpx.Response(200, json={"data": {"recordCount": len(all_rows),
                                                      "list": window}})
        return httpx.Response(404, json={"message": "no route"})

    return httpx.MockTransport(handler)


class TestYongyou:
    def test_tokenThenPaginate(self):
        state = {"rows": [{"order_id": "42", "status": "open"},
                          {"order_id": "43", "status": "closed"},
                          {"order_id": "44", "status": "open"},
                          {"order_id": "45", "status": "closed"}],
                 "logins": 0, "requests": 0}
        adapter = ErpRestAdapter(_descriptor(vendor="yongyou"), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_yongyouTransport(state))
        try:
            first = _run(adapter.fetchBatch(None, 2))
            assert [r["order_id"] for r in first.rows] == ["42", "43"]
            assert first.hasMore is True
            second = _run(adapter.fetchBatch(first.nextCursor, 2))
            third = _run(adapter.fetchBatch(second.nextCursor, 2))
            assert [r["order_id"] for r in third.rows] == []
            assert third.hasMore is False
        finally:
            _run(adapter.close())

    def test_tokenInvalidRelogsOnce(self):
        state = {"rows": [{"order_id": "42", "status": "open"}],
                 "logins": 0, "requests": 0}
        adapter = ErpRestAdapter(_descriptor(vendor="yongyou"), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_yongyouTransport(state))
        try:
            batch = _run(adapter.fetchBatch(None, 2))
            assert len(batch.rows) == 1
        finally:
            _run(adapter.close())


class TestCredentialHygiene:
    def test_credentialsNeverInLogs(self, caplog):
        import logging

        state = {"rows": [{"order_id": "42", "status": "open"}],
                 "logins": 0, "requests": 0}
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        adapter._client = httpx.Client(transport=_kingdeeTransport(state))
        try:
            with caplog.at_level(logging.DEBUG, logger="neurova.knowledge.enterprise.connectors_erp"):
                _run(adapter.fetchBatch(None, 2))
            joined = caplog.text
            assert "ERP_PASS" not in joined and "s3cret" not in joined
        finally:
            _run(adapter.close())

    def test_credentialsResolvedFromEnvNotDescriptor(self, monkeypatch):
        monkeypatch.setenv("ERP_USER", "kuai")
        monkeypatch.setenv("ERP_PASS", "s3cret-pw")
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        creds = adapter._resolveCredentials()
        assert creds == {"username": "kuai", "password": "s3cret-pw"}
        assert "s3cret-pw" not in json.dumps(adapter._descriptor)

    def test_missingCredentialEnvIsExplicit(self, monkeypatch):
        monkeypatch.delenv("ERP_USER", raising=False)
        monkeypatch.delenv("ERP_PASS", raising=False)
        monkeypatch.delenv("ERP_PASS", raising=False)
        adapter = ErpRestAdapter(_descriptor(), "erp_orders", "default")
        health = _run(adapter.health())
        assert health.status == "error"
        assert "ERP_PASS" in health.reason or "ERP_USER" in health.reason

    def test_badVendorRejectedAtFactory(self):
        from neurova.knowledge.enterprise.registry import buildAdapter

        with pytest.raises(MappingError, match="vendor"):
            buildAdapter(_descriptor(vendor="sap"), "erp_orders", "default")
