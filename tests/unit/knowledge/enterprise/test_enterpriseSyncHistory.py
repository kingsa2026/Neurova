# -*- coding: utf-8 -*-
"""企业源持续同步可靠性（方案 D1–D3，2026-11-19）红灯。

- D1 同步历史落账：每轮拉取（手动/interval，成功/失败/跳过）在
  `enterprise_sync_history` 落一行；异常如实落 error 后再冒泡；读面 admin 限定；
- D2 全租户调度：registerIntervalSyncs 缺省遍历全部租户的启用源，
  jobId 带租户段；运行时单源跟随（设置间隔/启停即时注册或摘除）；
- D3 单源单飞：同源并发第二轮 `already_running` 如实跳过，不并发双拉。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge_enterprise as ke
from neurova.knowledge.enterprise.protocols import ChangeBatch
from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    getSourceRegistry,
    registerIntervalSyncs,
    _syncLockFor,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
PREFIX = "/api/v1/knowledge"


class StubAdapter:
    """零行成功适配器：历史落账不依赖任何真实源型。"""

    def __init__(self, boom: bool = False):
        self._boom = boom

    async def fetchBatch(self, cursor, limit):
        if self._boom:
            raise RuntimeError("source exploded")
        return ChangeBatch(rows=[], nextCursor=None, hasMore=False)

    async def health(self):
        from neurova.knowledge.enterprise.protocols import SourceHealth

        return SourceHealth(status="ok", reason="")


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _saveEnabled(store, sourceId, tenant="default", enabled=True):
    ingestor = EnterpriseIngestor(store)
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    OntologyTermRegistry(store).register("row", "relation")
    descriptor = {"sourceType": "sql", "sourceId": sourceId, "dialect": "sqlite",
                  "database": "legacy.db", "cursorColumn": "id", "columns": ["id"],
                  "subject": {"column": "id"}, "predicate": {"termId": "row"},
                  "object": {"column": "id", "kind": "column"}}
    ingestor.saveConfig(tenant, sourceId, descriptor, enabled=enabled)
    return ingestor


def _historyRows(store, tenant="default", sourceId="src_hist"):
    with store._lock:
        rows = store._conn.execute(
            "SELECT * FROM enterprise_sync_history WHERE tenant_id = ? AND source_id = ?"
            " ORDER BY started_at", (tenant, sourceId)).fetchall()
    return [dict(r) for r in rows]


class TestSyncHistory:
    def test_manualRunWritesHistoryRow(self, kb):
        _saveEnabled(kb, "src_hist")
        getSourceRegistry().register("src_hist", "sql", StubAdapter())
        ingestor = EnterpriseIngestor(kb)
        out = asyncio.new_event_loop().run_until_complete(
            ingestor.runOnceAsync("default", "src_hist"))
        assert out["skipped"] is False if "skipped" in out else True
        rows = _historyRows(kb)
        assert len(rows) == 1
        row = rows[0]
        assert row["trigger_kind"] == "manual"
        assert row["status"] == "ok"
        assert row["batches"] >= 1
        assert row["cursor_before"] == "" and row["cursor_after"] == ""

    def test_intervalTriggerMarked(self, kb):
        _saveEnabled(kb, "src_hist")
        getSourceRegistry().register("src_hist", "sql", StubAdapter())
        ingestor = EnterpriseIngestor(kb)
        asyncio.new_event_loop().run_until_complete(
            ingestor.runOnceAsync("default", "src_hist", triggerKind="interval"))
        assert _historyRows(kb)[0]["trigger_kind"] == "interval"

    def test_skippedRunWritesRow(self, kb):
        _saveEnabled(kb, "src_hist", enabled=False)
        ingestor = EnterpriseIngestor(kb)
        out = asyncio.new_event_loop().run_until_complete(
            ingestor.runOnceAsync("default", "src_hist"))
        assert out["skipped"] is True
        row = _historyRows(kb)[0]
        assert row["status"] == "skipped" and "未启用" in row["reason"]

    def test_errorWritesRowAndReraises(self, kb):
        _saveEnabled(kb, "src_hist")
        getSourceRegistry().register("src_hist", "sql", StubAdapter(boom=True))
        ingestor = EnterpriseIngestor(kb)
        with pytest.raises(RuntimeError, match="exploded"):
            asyncio.new_event_loop().run_until_complete(
                ingestor.runOnceAsync("default", "src_hist"))
        row = _historyRows(kb)[0]
        assert row["status"] == "error" and "exploded" in row["reason"]

    def test_singleFlightSkipsConcurrent(self, kb):
        _saveEnabled(kb, "src_hist")
        getSourceRegistry().register("src_hist", "sql", StubAdapter())
        lock = _syncLockFor("default", "src_hist")
        with lock:
            out = asyncio.new_event_loop().run_until_complete(
                EnterpriseIngestor(kb).runOnceAsync("default", "src_hist"))
        assert out["skipped"] is True and out["reason"] == "already_running"
        row = _historyRows(kb)[0]
        assert row["status"] == "skipped" and "already_running" in row["reason"]


class TestSyncHistoryEndpoint:
    @pytest.fixture
    def client(self, kb, monkeypatch):
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: kb)
        app = FastAPI()
        app.include_router(ke.router, prefix=PREFIX)
        app.dependency_overrides[ke.get_current_user_or_service] = lambda: dict(ADMIN)
        return TestClient(app)

    def test_historyEndpointAdminOnly(self, client, kb):
        _saveEnabled(kb, "src_hist")
        getSourceRegistry().register("src_hist", "sql", StubAdapter())
        asyncio.new_event_loop().run_until_complete(
            EnterpriseIngestor(kb).runOnceAsync("default", "src_hist"))
        resp = client.get(PREFIX + "/enterprise/sources/src_hist/sync-history")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1 and items[0]["trigger_kind"] == "manual"

        client.app.dependency_overrides[ke.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        assert client.get(
            PREFIX + "/enterprise/sources/src_hist/sync-history").status_code == 403

    def test_historyEndpointLimit(self, client, kb):
        _saveEnabled(kb, "src_hist")
        getSourceRegistry().register("src_hist", "sql", StubAdapter())
        ingestor = EnterpriseIngestor(kb)
        loop = asyncio.new_event_loop()
        for _ in range(3):
            loop.run_until_complete(ingestor.runOnceAsync("default", "src_hist"))
        loop.close()
        resp = client.get(PREFIX + "/enterprise/sources/src_hist/sync-history",
                          params={"limit": 2})
        assert len(resp.json()["data"]["items"]) == 2


class TestSyncIntervalEndpoints:
    @pytest.fixture
    def client(self, kb, monkeypatch):
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: kb)
        app = FastAPI()
        app.include_router(ke.router, prefix=PREFIX)
        app.dependency_overrides[ke.get_current_user_or_service] = lambda: dict(ADMIN)
        return TestClient(app)

    def test_getAndPutSyncInterval(self, client, kb):
        _saveEnabled(kb, "src_iv")
        resp = client.get(PREFIX + "/enterprise/sources/src_iv/sync-interval")
        assert resp.status_code == 200
        assert resp.json()["data"]["seconds"] == 0

        put = client.put(PREFIX + "/enterprise/sources/src_iv/sync-interval",
                         json={"seconds": 300})
        assert put.status_code == 200
        assert put.json()["data"]["seconds"] == 300
        assert EnterpriseIngestor(kb).loadConfig("default", "src_iv")[
            "sync_interval_seconds"] == 300

    def test_putZeroDisables(self, client, kb):
        _saveEnabled(kb, "src_iv")
        client.put(PREFIX + "/enterprise/sources/src_iv/sync-interval",
                   json={"seconds": 120})
        put = client.put(PREFIX + "/enterprise/sources/src_iv/sync-interval",
                         json={"seconds": 0})
        assert put.status_code == 200
        assert put.json()["data"]["seconds"] == 0

    def test_putNegativeRejected(self, client, kb):
        _saveEnabled(kb, "src_iv")
        resp = client.put(PREFIX + "/enterprise/sources/src_iv/sync-interval",
                          json={"seconds": -5})
        assert resp.status_code == 422 or resp.status_code == 400

    def test_viewerForbidden(self, client, kb):
        _saveEnabled(kb, "src_iv")
        client.app.dependency_overrides[ke.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        assert client.get(
            PREFIX + "/enterprise/sources/src_iv/sync-interval").status_code == 403
        assert client.put(
            PREFIX + "/enterprise/sources/src_iv/sync-interval",
            json={"seconds": 30}).status_code == 403


class TestAllTenantScheduling:
    def test_registerCoversAllTenants(self, kb):
        _saveEnabled(kb, "src_a", tenant="default", enabled=True)
        EnterpriseIngestor(kb).setSyncInterval("default", "src_a", 300)
        ingestor = EnterpriseIngestor(kb)
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        OntologyTermRegistry(kb).register("row", "relation")
        descriptor = {"sourceType": "sql", "sourceId": "src_t2", "dialect": "sqlite",
                      "database": "legacy.db", "cursorColumn": "id", "columns": ["id"],
                      "subject": {"column": "id"}, "predicate": {"termId": "row"},
                      "object": {"column": "id", "kind": "column"}}
        ingestor.saveConfig("t2", "src_t2", descriptor, enabled=True)
        ingestor.setSyncInterval("t2", "src_t2", 120)

        class FakeScheduler:
            def __init__(self):
                self.jobs = []

            def addSystemJob(self, func, jobId, seconds):
                self.jobs.append({"jobId": str(jobId), "seconds": int(seconds)})

        fake = FakeScheduler()
        registerIntervalSyncs(fake, store=kb)  # 缺省=全租户
        jobIds = [j["jobId"] for j in fake.jobs]
        assert "kb_enterprise_sync_default_src_a" in jobIds
        assert "kb_enterprise_sync_t2_src_t2" in jobIds

    def test_runtimeFollowUpRegistersAndRemoves(self, kb):
        _saveEnabled(kb, "src_rt", enabled=True)
        EnterpriseIngestor(kb).setSyncInterval("default", "src_rt", 60)

        class FakeScheduler:
            def __init__(self):
                self.jobs = {}

            def addSystemJob(self, func, jobId, seconds):
                self.jobs[str(jobId)] = int(seconds)

            def removeSystemJob(self, jobId):
                self.jobs.pop(str(jobId), None)

        fake = FakeScheduler()
        registerIntervalSyncs(fake, store=kb)
        assert list(fake.jobs) == ["kb_enterprise_sync_default_src_rt"]

        ingestor = EnterpriseIngestor(kb)
        ingestor.setSyncInterval("default", "src_rt", 0)
        assert fake.jobs == {}, "间隔清零 → 运行时摘除 job"

        ingestor.setSyncInterval("default", "src_rt", 45)
        assert fake.jobs.get("kb_enterprise_sync_default_src_rt") == 45
