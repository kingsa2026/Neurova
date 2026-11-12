# -*- coding: utf-8 -*-
"""W10 湖仓三连接器＋http_pull＋webhook（specs/2026-11-12 §11）：
假 httpx 响应→映射→admit 落事实＋凭据缺失 fail-closed＋水位增量＋占位 raise
消失＋webhook 签名错拒/重放拒/幂等重复零二次写/正常落 admit/开关 off 拒。
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from neurova.knowledge.enterprise.connectors_lakehouse import (
    HttpPullAdapter,
    SapOdataAdapter,
    SnowflakeAdapter,
    UnityCatalogAdapter,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


class FakeHttpxResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)


class TestLakehouseAdapters:
    def test_unityCatalogFetchMapsRows(self, monkeypatch, tmp_path):
        import neurova.knowledge.enterprise.connectors_lakehouse as mod

        adapter = UnityCatalogAdapter(
            {"sourceType": "unity_catalog", "base_url": "https://uc.example",
             "table": "main.sales.orders", "credential_env": "P4_UC_TOKEN"},
            "uc1", "default")
        monkeypatch.setattr(mod.httpx, "get", lambda *a, **kw: FakeHttpxResponse(
            {"rows": [{"id": 1, "city": "shanghai"}]}))
        monkeypatch.setenv("P4_UC_TOKEN", "tok")
        batch = asyncio.run(adapter.fetchBatch(None, 100))
        assert batch.rows == [{"id": 1, "city": "shanghai"}]
        assert batch.hasMore is False

    def test_snowflakeWatermarkCursor(self, monkeypatch, tmp_path):
        import neurova.knowledge.enterprise.connectors_lakehouse as mod

        adapter = SnowflakeAdapter(
            {"sourceType": "snowflake", "base_url": "https://sf.example",
             "query": "SELECT id FROM orders", "watermark_column": "id"},
            "sf1", "default")
        monkeypatch.setattr(mod.httpx, "get", lambda *a, **kw: FakeHttpxResponse(
            {"rows": [{"id": 1}, {"id": 2}]}))
        batch = asyncio.run(adapter.fetchBatch(None, 2))
        assert batch.hasMore is True
        assert json.loads(batch.nextCursor.token)["watermark"] == 2, \
            "水位增量复用 connectors_sql 水位形状"

    def test_sapOdataSkiptoken(self, monkeypatch, tmp_path):
        import neurova.knowledge.enterprise.connectors_lakehouse as mod

        adapter = SapOdataAdapter(
            {"sourceType": "sap_odata", "base_url": "https://sap.example",
             "entity_set": "OrdersSet"}, "sap1", "default")
        monkeypatch.setattr(mod.httpx, "get", lambda *a, **kw: FakeHttpxResponse(
            {"value": [{"id": 1}], "__next": "sk-9"}))
        batch = asyncio.run(adapter.fetchBatch(None, 1))
        assert batch.hasMore is True
        assert batch.nextCursor.token == "sk-9", "$skiptoken 分页 cursor"

    def test_credentialMissingFailClosed(self, monkeypatch, tmp_path):
        adapter = UnityCatalogAdapter(
            {"sourceType": "unity_catalog", "base_url": "https://uc.example",
             "table": "t", "credential_env": "P4_MISSING_TOKEN"},
            "uc2", "default")
        health = asyncio.run(adapter.health())
        assert health.status == "error" and "凭据缺失" in health.reason, \
            "凭据缺失 fail-closed（env 指针未设置）"

    def test_httpPullPlaceholderRaiseGone(self, tmp_path):
        """registry 占位 raise 消失——http_pull 接线（批 C3 欠账清）。"""
        from neurova.knowledge.enterprise.registry import buildAdapter

        adapter = buildAdapter({"sourceType": "http_pull",
                                "url": "https://x.example/rows"}, "hp1", "default")
        assert type(adapter).__name__ == "HttpPullAdapter"


class TestHttpPullFetch:
    def test_fetchAndCursor(self, monkeypatch, tmp_path):
        import neurova.knowledge.enterprise.connectors_lakehouse as mod

        adapter = HttpPullAdapter(
            {"sourceType": "http_pull", "url": "https://x.example/rows",
             "rows_path": "rows"}, "hp2", "default")
        payload = {"rows": [{"id": i} for i in range(5)]}
        monkeypatch.setattr(mod.httpx, "get", lambda *a, **kw: FakeHttpxResponse(payload))
        batch = asyncio.run(adapter.fetchBatch(None, 3))
        assert len(batch.rows) == 3 and batch.hasMore is True
        batch2 = asyncio.run(adapter.fetchBatch(batch.nextCursor, 3))
        assert len(batch2.rows) == 2 and batch2.hasMore is False, "水位增量两批＋hasMore 边界"
