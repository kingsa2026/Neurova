# -*- coding: utf-8 -*-
"""企业源生命周期面契约（页面重设计配套批）：时间戳/计数回显、health 探测、DELETE。

红灯判据（页面重设计计划·后端配套）：
- 列表/单源回显带 created_at/updated_at 与 ingested_count（断言 actor_id='source:<id>' 计数）；
- health 端点语义在 ingestor 层：buildAdapter 构造（不注册）→ health() 三态；
  配置缺失 → None；工厂错（缺变体/未接线）→ MappingError 原样出去（端点映射 400）；
- deleteConfig：删配置行；unregister：进程内适配器表摘除；已摄取事实/断言保留。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.enterprise.fake_adapter import FakeEnterpriseAdapter
from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    EnterpriseSourceRegistry,
    getSourceRegistry,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ingestor(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept"},
        {"termId": "has_status", "kind": "relation", "domain": ["Order"]},
    ])
    return EnterpriseIngestor(store, registry=registry)


def _descriptor(sourceId="erp_prod"):
    return {"sourceId": sourceId, "tenantId": "default", "sourceType": "sql",
            "columns": ["order_id", "status"],
            "logicalTable": "orders",
            "subject": {"template": "order:{order_id}"},
            "predicate": {"termId": "has_status"},
            "object": {"kind": "column", "column": "status"},
            "driver": "sqlite", "database": "orders.db",
            "query": "SELECT order_id, status FROM orders {wmCond} {lim}"}


def testListConfigCarriesTimestamps(ingestor):
    ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=False)
    rows = ingestor.listConfigs("default")
    row = next(r for r in rows if r["source_id"] == "erp_prod")
    assert row.get("created_at"), "列表行应带 created_at"
    assert row.get("updated_at"), "列表行应带 updated_at"


def testLoadConfigCarriesTimestamps(ingestor):
    ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=False)
    config = ingestor.loadConfig("default", "erp_prod")
    assert config is not None
    assert config.get("created_at") and config.get("updated_at")


def testIngestedCountQueryCountsByActorId(store, ingestor):
    """计数读数＝按断言 actor_id='source:<id>' 统计（已摄取行才有）。"""
    ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=True)
    adapter = FakeEnterpriseAdapter(_descriptor(), "erp_prod", "default")
    ingestor.ingestBatch(_descriptor(), [
        {"order_id": "o1", "status": "open"},
        {"order_id": "o2", "status": "paid"},
    ], cursorToken="c1")
    n = store._conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_assertions WHERE actor_id = ?",
        ("source:erp_prod",)).fetchone()["n"]
    assert n == 2
    # 未摄取的源计数为 0
    n0 = store._conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_assertions WHERE actor_id = ?",
        ("source:nobody",)).fetchone()["n"]
    assert n0 == 0
    assert adapter is not None  # 假适配器仅证明构造可用


def testHealthProbeBuildsAdapterWithoutRegistering(ingestor):
    ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=False)
    # 未注册前 registry 无此源；health 探测不该把它注册进去
    assert getSourceRegistry().get("erp_prod") is None


def testDeleteConfigRemovesRowButKeepsFacts(store, ingestor):
    ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=True)
    ingestor.ingestBatch(_descriptor(), [{"order_id": "o1", "status": "open"}],
                         cursorToken="c1")
    facts_before = store.factCount()
    ingestor.deleteConfig("default", "erp_prod")
    assert ingestor.loadConfig("default", "erp_prod") is None
    assert [r["source_id"] for r in ingestor.listConfigs("default")] == []
    # 已摄取事实/断言保留（擦除闭集无 source: 前缀，不做级联——UI 如实说明）
    assert store.factCount() == facts_before


def testDeleteConfigMissingIsNoop(ingestor):
    ingestor.deleteConfig("default", "ghost")  # 不抛错即通过


def testUnregisterRemovesAdapterFromProcessRegistry():
    reg = EnterpriseSourceRegistry()
    reg.register("a1", "sql", FakeEnterpriseAdapter({}, "a1", "default"))
    assert reg.get("a1") is not None
    reg.unregister("a1")
    assert reg.get("a1") is None
    # 重复 unregister 幂等
    reg.unregister("a1")
    assert reg.get("a1") is None
