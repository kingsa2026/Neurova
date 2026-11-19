# -*- coding: utf-8 -*-
"""企业源租户级共享 P2（方案 §8.3-P2，2026-11-19 拍板全量实施）红灯。

- 源级策略：enterprise_source_configs.share_tenants（v57 列）——
  setShareTenants 落库/校验、loadConfig/listConfigs 回显；
- 投影式复制（设计决策：连接器凭据属源租户，目标租户不独立拉取——
  源租户每轮拉取成功后，同一批断言投影到目标租户分区）：
  qualifier.shared_from 注记血缘、mediumRef/sourceSpan 与源轮一致、
  内容键按租户分区各自幂等；投影数据参与目标租户冲突判定。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge_enterprise as ke
from neurova.knowledge.enterprise.protocols import ChangeBatch
from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    getSourceRegistry,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
PREFIX = "/api/v1/knowledge"
TARGET = "tenant-b"


class RowsAdapter:
    """恒返回同一批行（hasMore=False）：第二轮靠内容键幂等零准入。"""

    def __init__(self, rows):
        self._rows = rows

    async def fetchBatch(self, cursor, limit):
        if cursor is not None and not cursor.isEmpty():
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        return ChangeBatch(rows=list(self._rows), nextCursor=None, hasMore=False)

    async def health(self):
        from neurova.knowledge.enterprise.protocols import SourceHealth

        return SourceHealth(status="ok", reason="")


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _mkSource(kb, sourceId="src_share", rows=None, shareTenants=None):
    ingestor = EnterpriseIngestor(kb)
    OntologyTermRegistry(kb).register("row", "relation")
    descriptor = {
        "sourceType": "sql",
        "sourceId": sourceId,
        "dialect": "sqlite",
        "database": "legacy.db",
        "cursorColumn": "id",
        "columns": ["id"],
        "subject": {"column": "id"},
        "predicate": {"termId": "row"},
        "object": {"column": "id", "kind": "column"},
    }
    ingestor.saveConfig("default", sourceId, descriptor, enabled=True)
    if shareTenants is not None:
        ingestor.setShareTenants("default", sourceId, shareTenants)
    if rows is not None:
        getSourceRegistry().register(sourceId, "sql", RowsAdapter(rows))
    return ingestor


def _targetFacts(kb, subjectLabel="A"):
    """目标租户分区的事实（生产同款读法：candidateFactsForConflict）。"""
    return kb.candidateFactsForConflict(subjectLabel, "row", TARGET)


def _targetAssertions(kb):
    """目标租户分区的断言行（assertions 挂 fact_id，租户在 facts 上；
    v55 的 source_span_json 落在 assertions 表）。"""
    return kb._conn.execute(
        "SELECT a.medium_ref, a.source_span_json FROM knowledge_assertions a"
        " JOIN knowledge_facts f ON f.fact_id = a.fact_id"
        " WHERE f.tenant_id = ?", (TARGET,)).fetchall()


class TestShareTenantsPolicy:
    def test_setShareTenantsRoundtrips(self, kb):
        ingestor = _mkSource(kb)
        ingestor.setShareTenants("default", "src_share", [TARGET])
        assert ingestor.loadConfig("default", "src_share")["share_tenants"] == [TARGET]
        assert [c["share_tenants"] for c in ingestor.listConfigs("default")] == [[TARGET]]

    def test_setShareTenantsRejectsSelfTenant(self, kb):
        ingestor = _mkSource(kb)
        with pytest.raises(ValueError, match="自身"):
            ingestor.setShareTenants("default", "src_share", ["default"])

    def test_setShareTenantsEmptyClears(self, kb):
        ingestor = _mkSource(kb, shareTenants=[TARGET])
        ingestor.setShareTenants("default", "src_share", [])
        assert ingestor.loadConfig("default", "src_share")["share_tenants"] == []


class TestProjection:
    def test_ingestProjectsToShareTenants(self, kb):
        ingestor = _mkSource(kb, rows=[{"id": "A"}, {"id": "B"}],
                             shareTenants=[TARGET])
        result = asyncio_run(ingestor.runOnceAsync("default", "src_share"))

        assert result["admitted"] == 2
        assert result["projected"] == {TARGET: 2}
        rows = kb._conn.execute(
            "SELECT object_term FROM knowledge_facts WHERE tenant_id = ?"
            " ORDER BY object_term", (TARGET,)).fetchall()
        assert [r["object_term"] for r in rows] == ["A", "B"]
        for r in kb.candidateFactsForConflict("A", "row", TARGET):
            qualifier = r.get("qualifier") or {}
            assert qualifier.get("shared_from") == "default", "投影必须带血缘注记"

    def test_projectionIsIdempotentPerTenant(self, kb):
        ingestor = _mkSource(kb, rows=[{"id": "A"}], shareTenants=[TARGET])
        asyncio_run(ingestor.runOnceAsync("default", "src_share"))
        asyncio_run(ingestor.runOnceAsync("default", "src_share"))

        # 重放同一批：admission 的 admitted 计数是流水口径（折回已存在行也计入），
        # 幂等的硬判据是**事实行数不增**——源租户与目标租户分区各自一批
        assert len(_targetFacts(kb)) == 1

    def test_projectionKeepsLineage(self, kb):
        ingestor = _mkSource(kb, rows=[{"id": "A"}], shareTenants=[TARGET])
        asyncio_run(ingestor.runOnceAsync("default", "src_share"))

        rows = _targetAssertions(kb)
        assert rows, "目标租户分区必须有投影断言"
        for r in rows:
            assert str(r["medium_ref"] or "").startswith("source:src_share:"), (
                "投影断言的 medium_ref 必须与源轮同源")
            assert '"row": 0' in (r["source_span_json"] or ""), "投影必须保留行级血缘"

    def test_projectionFeedsTargetConflictJudge(self, kb):
        """投影数据参与目标租户冲突判定：同 (主体,谓词) 异客体开账。"""
        key = kb.upsertSubject("agent-1", "A", tenantId=TARGET)
        kb.upsertFact("agent-1", key, "row", "X", "目标租户既有说法", tenantId=TARGET)
        ingestor = _mkSource(kb, rows=[{"id": "A"}], shareTenants=[TARGET])
        asyncio_run(ingestor.runOnceAsync("default", "src_share"))

        from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge

        conflicts = KnowledgeConflictJudge(kb).detect(subjectLabel="A",
                                                      predicateTermId="row",
                                                      tenantId=TARGET)
        assert len(conflicts) == 1 and conflicts[0]["kind"] == "value"

    def test_noShareTenantsSkipsProjection(self, kb):
        ingestor = _mkSource(kb, rows=[{"id": "A"}])
        result = asyncio_run(ingestor.runOnceAsync("default", "src_share"))
        assert result.get("projected", {}) == {}
        assert _targetFacts(kb) == []


class TestShareTenantsEndpoints:
    @pytest.fixture
    def api(self, tmp_path, monkeypatch):
        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_enterprise._parts",
            lambda: (EnterpriseIngestor(s), getSourceRegistry(), s))
        app = FastAPI()
        app.include_router(ke.router, prefix=PREFIX)
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
        yield TestClient(app), s
        s.close()

    def test_putAndGetShareTenants(self, api, monkeypatch):
        client, store = api
        monkeypatch.setattr("neurova.api.endpoints.knowledge_enterprise.ensureTenantExists",
                            lambda tid: None)
        _mkSource(store)
        resp = client.put(f"{PREFIX}/enterprise/sources/src_share/share-tenants",
                          json={"tenant_ids": [TARGET]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["share_tenants"] == [TARGET]
        got = client.get(f"{PREFIX}/enterprise/sources/src_share/share-tenants")
        assert got.json()["data"]["share_tenants"] == [TARGET]

    def test_putRejectsSelfTenant(self, api, monkeypatch):
        client, store = api
        monkeypatch.setattr("neurova.api.endpoints.knowledge_enterprise.ensureTenantExists",
                            lambda tid: None)
        _mkSource(store)
        resp = client.put(f"{PREFIX}/enterprise/sources/src_share/share-tenants",
                          json={"tenant_ids": ["default"]})
        assert resp.status_code == 400

    def test_putRequiresAdmin(self, api, monkeypatch):
        client, store = api
        monkeypatch.setattr("neurova.api.endpoints.knowledge_enterprise.ensureTenantExists",
                            lambda tid: None)
        _mkSource(store)
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
            lambda: dict(VIEWER))
        resp = client.put(f"{PREFIX}/enterprise/sources/src_share/share-tenants",
                          json={"tenant_ids": [TARGET]})
        assert resp.status_code == 403


def asyncio_run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)
