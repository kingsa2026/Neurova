# -*- coding: utf-8 -*-
"""B14 映射描述符判据（升级计划 §14.2）：合法/缺列/未登记/注入/租户隔离/默认禁用。"""

from __future__ import annotations

import pytest

from neurova.knowledge.enterprise.schema_mapping import (
    MappingError,
    applyMapping,
    validateDescriptor,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept"},
        {"termId": "has_status", "kind": "relation", "domain": ["Order"]},
    ])
    return registry


def _descriptor(**overrides):
    base = {
        "sourceId": "erp_prod", "tenantId": "default", "sourceType": "sql",
        "columns": ["order_id", "status", "channel_code", "updated_at"],
        "logicalTable": "orders",
        "subject": {"template": "order:{order_id}", "typeTerm": "Order"},
        "predicate": {"termId": "has_status"},
        "object": {"column": "status", "kind": "column"},
        "qualifiers": {"channel": "channel_code"},
        "cursorColumn": "updated_at",
        "idempotencyKey": ["order_id", "updated_at"],
        "enabled": False,
    }
    base.update(overrides)
    return base


class TestDescriptorValidation:
    def test_validDescriptorPasses(self, registry):
        validateDescriptor(_descriptor(), registry)

    def test_unknownSourceTypeRejected(self, registry):
        with pytest.raises(MappingError, match="白名单"):
            validateDescriptor(_descriptor(sourceType="telepathy"), registry)

    def test_missingColumnsRejected(self, registry):
        with pytest.raises(MappingError, match="columns"):
            validateDescriptor(_descriptor(columns=[]), registry)

    def test_templateSlotMustBeDeclaredColumn(self, registry):
        bad = _descriptor()
        bad["subject"]["template"] = "order:{ghost_col}"
        with pytest.raises(MappingError, match="ghost_col"):
            validateDescriptor(bad, registry)

    def test_unregisteredPredicateRejected(self, registry):
        with pytest.raises(MappingError, match="未登记"):
            validateDescriptor(_descriptor(predicate={"termId": "no_such_rel"}), registry)

    def test_unknownObjectKindRejected(self, registry):
        with pytest.raises(MappingError, match="object.kind"):
            validateDescriptor(_descriptor(object={"kind": "quantum"}), registry)

    def test_objectColumnMustBeDeclared(self, registry):
        with pytest.raises(MappingError, match="已声明列"):
            validateDescriptor(_descriptor(object={"column": "ghost", "kind": "column"}),
                               registry)

    def test_sqlShapesRejected(self, registry):
        with pytest.raises(MappingError, match="SQL"):
            validateDescriptor(
                _descriptor(logicalTable="orders; DROP TABLE users"), registry)


class TestApplyMapping:
    def test_rowMapsToAdmissionShape(self, registry):
        mapped = applyMapping(_descriptor(), {"order_id": "42", "status": "open",
                                              "channel_code": "web"},
                              registry)
        assert mapped["subjectLabel"] == "order:42"
        assert mapped["predicateTermId"] == "has_status"
        assert mapped["objectTerm"] == "open"
        assert mapped["qualifier"] == {"channel": "web"}

    def test_termObjectUsesConstantTerm(self, registry):
        d = _descriptor(object={"kind": "term", "termId": "Order"})
        assert applyMapping(d, {"order_id": "42"}, registry)["objectTerm"] == "Order"


class TestConfigDefaultsDisabled:
    def test_saveLoadRoundTripAndDefaultDisabled(self, store, registry):
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor

        ingestor = EnterpriseIngestor(store, registry=registry)
        ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=False)

        config = ingestor.loadConfig("default", "erp_prod")
        assert config["enabled"] is False, "默认关闸（enabled=False）"
        assert config["descriptor"]["sourceId"] == "erp_prod"

    def test_ingestSkippedWhenDisabled(self, store, registry):
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor

        ingestor = EnterpriseIngestor(store, registry=registry)
        ingestor.saveConfig("default", "erp_prod", _descriptor(), enabled=False)

        result = ingestor.ingestIfEnabled("default", "erp_prod",
                                          rows=[{"order_id": "42", "status": "open"}])
        assert result.get("skipped") is True, "默认关闸零调用"

    def test_sourceIdUniquePerTenant(self, store, registry):
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor

        ingestor = EnterpriseIngestor(store, registry=registry)
        ingestor.saveConfig("default", "erp_prod", _descriptor())
        registry.register("has_status", "relation", tenantId="tenant-b")
        ingestor.saveConfig("tenant-b", "erp_prod", _descriptor())

        assert ingestor.loadConfig("tenant-b", "erp_prod") is not None
        assert ingestor.loadConfig("tenant-c", "erp_prod") is None, "租户隔离"
