# -*- coding: utf-8 -*-
"""批 C1：文件行源连接器＋生产触发面（2026-11-07 裁定 §2.3-1A/2A）。

判据（立项方案 §3-C1）：白名单扩 file；describeSchema 从文件头推 columns；
fetchBatch 游标＝文件指纹＋行偏移；全量重入幂等；enabled=False 零读取；
runOnce 全链（loadConfig→适配器→fetchBatch→ingestBatch→游标持久化）。
变体闭集（file.format 等）在 validateDescriptor 收口、工厂强制要求。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    EnterpriseSourceRegistry,
    buildAdapter,
)
from neurova.knowledge.enterprise.schema_mapping import MappingError, validateDescriptor
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ingestor(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Customer", "kind": "concept"},
        {"termId": "has_status", "kind": "relation"},
    ])
    return EnterpriseIngestor(store, registry=registry)


def _descriptor(tmp_path, filename="orders.csv", **overrides):
    csv_path = tmp_path / filename
    csv_path.write_text(
        "order_id,status\n42,open\n43,closed\n44,open\n",
        encoding="utf-8",
    )
    descriptor = {
        "sourceId": "orders_csv",
        "tenantId": "default",
        "sourceType": "file",
        "format": "csv",
        "path": str(csv_path),
        "columns": ["order_id", "status"],
        "subject": {"template": "order:{order_id}"},
        "predicate": {"termId": "has_status"},
        "object": {"column": "status", "kind": "column"},
        "qualifiers": {}, "enabled": True, "agentId": "default",
    }
    descriptor.update(overrides)
    return descriptor


class TestWhitelistAndVariants:
    def test_fileTypeRegistersWithoutValueError(self):
        """红灯判据：白名单扩 file 后注册不再被拒。"""
        registry = EnterpriseSourceRegistry()
        registry.register("s1", "file", object())
        assert registry.get("s1") is not None

    def test_variantClosedSets(self, tmp_path):
        store = KnowledgeFactStore(":memory:")
        try:
            registry = OntologyTermRegistry(store)
            registry.registerMany([{"termId": "has_status", "kind": "relation"}])
            with pytest.raises(MappingError, match="format"):
                validateDescriptor(_descriptor(tmp_path, format="parquet"), registry)
            with pytest.raises(MappingError, match="driver"):
                validateDescriptor(
                    _descriptor(tmp_path, sourceType="sql", driver="mongodb"), registry)
        finally:
            store.close()

    def test_factoryRequiresVariant(self, tmp_path):
        descriptor = _descriptor(tmp_path)
        descriptor.pop("format")
        with pytest.raises(MappingError, match="format"):
            buildAdapter(descriptor, "orders_csv", "default")


class TestFileRowAdapter:
    def test_describeSchemaFromHeader(self, tmp_path):
        adapter = buildAdapter(_descriptor(tmp_path), "orders_csv", "default")
        schema = _run(adapter.describeSchema())
        assert schema.sourceType == "file"
        assert schema.tables[0]["columns"] == ["order_id", "status"]

    def test_fetchBatchPaginatesByOffset(self, tmp_path):
        adapter = buildAdapter(_descriptor(tmp_path), "orders_csv", "default")
        first = _run(adapter.fetchBatch(None, 2))
        assert [r["order_id"] for r in first.rows] == ["42", "43"]
        assert first.hasMore is True
        second = _run(adapter.fetchBatch(first.nextCursor, 2))
        assert [r["order_id"] for r in second.rows] == ["44"]
        assert second.hasMore is False

    def test_fileChangeResetsCursor(self, tmp_path):
        adapter = buildAdapter(_descriptor(tmp_path), "orders_csv", "default")
        first = _run(adapter.fetchBatch(None, 2))
        (tmp_path / "orders.csv").write_text(
            "order_id,status\n42,open\n", encoding="utf-8")
        after = _run(adapter.fetchBatch(first.nextCursor, 10))
        assert [r["order_id"] for r in after.rows] == ["42"], \
            "文件指纹变了：游标从 0 重读（幂等由咽喉内容键兜底）"

    def test_badPathHealthErrors(self, tmp_path):
        descriptor = _descriptor(tmp_path)
        descriptor["path"] = str(tmp_path / "missing.csv")
        adapter = buildAdapter(descriptor, "ghost", "default")
        health = _run(adapter.health())
        assert health.status == "error"
        assert "path" in health.reason or "missing" in health.reason


class TestRunOnceEndToEnd:
    def test_runOnceAdmitsRowsAndPersistsCursor(self, store, ingestor, tmp_path):
        ingestor.saveConfig("default", "orders_csv", _descriptor(tmp_path), enabled=True)
        result = ingestor.runOnce("default", "orders_csv")
        assert result.get("skipped") is None
        assert result["admitted"] == 3, "三行 CSV 全量入账"
        facts = store.searchableFacts(agentId="default")
        assert any(f["canonical_label"] == "order:42" and f["object_term"] == "open"
                   for f in facts)
        config = ingestor.loadConfig("default", "orders_csv")
        assert config["cursor"], "游标已持久化（非空 token）"

    def test_replayIsIdempotent(self, store, ingestor, tmp_path):
        ingestor.saveConfig("default", "orders_csv", _descriptor(tmp_path), enabled=True)
        first = ingestor.runOnce("default", "orders_csv")
        second = ingestor.runOnce("default", "orders_csv")
        assert second["admitted"] == 0, \
            "同一文件重放：内容键去重，facts 行数不增（first=%s）" % first["admitted"]

    def test_disabledSourceSkipsWithoutReading(self, store, ingestor, tmp_path):
        ingestor.saveConfig("default", "orders_csv", _descriptor(tmp_path), enabled=False)
        result = ingestor.runOnce("default", "orders_csv")
        assert result["skipped"] is True
        assert not store.searchableFacts(agentId="default"), "零落库"

    def test_unknownSourceSkips(self, ingestor):
        result = ingestor.runOnce("default", "no_such_source")
        assert result["skipped"] is True

    def test_jsonRowsAdmitThroughSameChain(self, store, ingestor, tmp_path):
        json_path = tmp_path / "orders.json"
        json_path.write_text(json.dumps([
            {"order_id": "42", "status": "open"},
            {"order_id": "43", "status": "closed"},
        ]), encoding="utf-8")
        ingestor.saveConfig("default", "orders_json", {
            "sourceId": "orders_json", "tenantId": "default", "sourceType": "file",
            "format": "json", "path": str(json_path),
            "columns": ["order_id", "status"],
            "subject": {"template": "order:{order_id}"},
            "predicate": {"termId": "has_status"},
            "object": {"column": "status", "kind": "column"},
            "qualifiers": {}, "enabled": True, "agentId": "default",
        }, enabled=True)
        result = ingestor.runOnce("default", "orders_json")
        assert result["admitted"] == 2, "JSON 数组行源同构入账"
