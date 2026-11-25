# -*- coding: utf-8 -*-
"""KNOW-03：企业适配器进程注册表按 (tenant, source) 隔离＋按配置指纹重建。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-03）：配置按 (tenant_id, source_id)
隔离，进程注册表只按 source_id——后注册租户可能复用前一租户的连接/数据源。
判据咬合真实链路：同一 source_id 在两个租户各配一个文件源（不同 CSV），
initialBulkLoad 各自装载，acme 必须吃到自己的文件，而不是 default 的适配器。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    EnterpriseSourceRegistry,
    getSourceRegistry,
)
from neurova.knowledge.enterprise.fake_adapter import FakeEnterpriseAdapter
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _cleanSourceRegistry():
    """本文件向全局源注册表挂过适配器——用完摘净，不污染后续测试。"""
    yield
    registry = getSourceRegistry()
    for sourceId in ("orders_csv", "s1", "shared_src"):
        for tenant in ("default", "acme", "other"):
            registry.unregister(sourceId, tenantId=tenant)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


@pytest.fixture
def ingestor(store):
    registry = OntologyTermRegistry(store)
    for tenant in ("default", "acme"):
        registry.registerMany([
            {"termId": "Customer", "kind": "concept"},
            {"termId": "has_status", "kind": "relation"},
        ], tenantId=tenant)
    return EnterpriseIngestor(store, registry=registry)


def _fileDescriptor(csvPath, tenantId, sourceId="orders_csv"):
    return {"sourceId": sourceId, "tenantId": tenantId, "sourceType": "file",
            "format": "csv", "path": str(csvPath),
            "columns": ["order_id", "status"],
            "subject": {"template": "order:{order_id}"},
            "predicate": {"termId": "has_status"},
            "object": {"column": "status", "kind": "column"},
            "qualifiers": {}, "enabled": True, "agentId": "default"}


def _tenantFactSubjects(store, tenantId):
    rows = store._conn.execute(
        "SELECT s.canonical_label AS label FROM knowledge_facts f"
        " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
        " WHERE f.tenant_id = ? AND f.status = 'active'",
        (tenantId,)).fetchall()
    return {str(r["label"]) for r in rows}


class TestRegistryTenantKey:
    def test_registryKeyIncludesTenant(self):
        """同 source_id 不同租户：各取各的适配器，不得互相覆盖。"""
        reg = EnterpriseSourceRegistry()
        adapterDefault = FakeEnterpriseAdapter("s1", [{"order_id": "1"}])
        adapterAcme = FakeEnterpriseAdapter("s1", [{"order_id": "2"}])
        reg.register("s1", "sql", adapterDefault, tenantId="default")
        reg.register("s1", "sql", adapterAcme, tenantId="acme")
        assert reg.get("s1", tenantId="default") is adapterDefault
        assert reg.get("s1", tenantId="acme") is adapterAcme
        assert reg.get("s1", tenantId="other") is None

    def test_getReturnsNoneWhenFingerprintChanges(self):
        """配置指纹变了：旧适配器不得冒充新配置（调用方须按指纹重建）。"""
        reg = EnterpriseSourceRegistry()
        adapter = FakeEnterpriseAdapter("s1", [])
        reg.register("s1", "sql", adapter, tenantId="default",
                     fingerprint="fp-config-v1")
        assert reg.get("s1", tenantId="default", fingerprint="fp-config-v1") \
            is adapter
        assert reg.get("s1", tenantId="default", fingerprint="fp-config-v2") \
            is None, "指纹不一致必须返回 None 触发重建"

    def test_unregisterIsTenantScoped(self):
        """摘除只摘本租户：他租户同名源不受影响。"""
        reg = EnterpriseSourceRegistry()
        adapterDefault = FakeEnterpriseAdapter("s1", [])
        adapterAcme = FakeEnterpriseAdapter("s1", [])
        reg.register("s1", "sql", adapterDefault, tenantId="default")
        reg.register("s1", "sql", adapterAcme, tenantId="acme")
        reg.unregister("s1", tenantId="default")
        assert reg.get("s1", tenantId="default") is None
        assert reg.get("s1", tenantId="acme") is adapterAcme


class TestSyncBuildsAdapterPerTenant:
    def test_sameSourceIdTwoTenantsEachIngestOwnFile(self, store, ingestor, tmp_path):
        """真实链路：同 source_id 两租户各自装载自己的文件，不串源。"""
        fileDefault = tmp_path / "default_orders.csv"
        fileDefault.write_text("order_id,status\n42,open\n43,closed\n",
                               encoding="utf-8")
        fileAcme = tmp_path / "acme_orders.csv"
        fileAcme.write_text("order_id,status\n900,open\n901,closed\n",
                            encoding="utf-8")
        ingestor.saveConfig("default", "orders_csv",
                            _fileDescriptor(fileDefault, "default"), enabled=True)
        ingestor.saveConfig("acme", "orders_csv",
                            _fileDescriptor(fileAcme, "acme"), enabled=True)

        _run(ingestor.initialBulkLoad("default", "orders_csv", dryRun=False))
        _run(ingestor.initialBulkLoad("acme", "orders_csv", dryRun=False))

        acmeSubjects = _tenantFactSubjects(store, "acme")
        defaultSubjects = _tenantFactSubjects(store, "default")
        assert "order:900" in acmeSubjects, "acme 必须吃到自己的文件（order:900）"
        assert "order:42" not in acmeSubjects, "acme 不得吃到 default 租户的文件"
        assert "order:42" in defaultSubjects, "default 仍正常吃自己的文件"
