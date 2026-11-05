# -*- coding: utf-8 -*-
"""B11 L3（升级计划 §12.4）：限定关系 schema——qualifier 的键/类型/必填三判。

N 元关系继续用限定三元组，不新造 reification 表；未知键记 warning（不阻断），
必填缺失记 violation（写前阻断）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.validation import OntologyValidationReport


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
        {"termId": "shipped_to", "kind": "relation", "domain": ["Order"],
         "qualifierSchema": {
             "required": ["carrier"],
             "allowed": {"carrier": "string", "arrived_at": "string"},
         }},
    ])
    return registry


def _gate(store):
    return productionAdmissionGate(store, toolVersion="b11")


def _admit(store, subject, predicate, obj, qualifier=None):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, qualifier=qualifier or {},
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ))


def test_missingRequiredQualifierIsViolation(store, registry):
    key = store.resolveSubjectKey("default", "订单X") if False else None
    _admit(store, "订单X", "is_a", "Order")
    k = store.resolveSubjectKey("default", "订单X")
    registry.assignSubjectType(k, "Order")

    with pytest.raises(ValueError, match="carrier"):
        _admit(store, "订单X", "shipped_to", "上海仓", qualifier={"note": "缺承运方"})


def test_allowedQualifierPassesAndLandsInRow(store, registry):
    _admit(store, "订单Y", "is_a", "Order")
    k = store.resolveSubjectKey("default", "订单Y")
    registry.assignSubjectType(k, "Order")

    receipt = _admit(store, "订单Y", "shipped_to", "上海仓",
                     qualifier={"carrier": "顺丰", "arrived_at": "2026-11-06"})

    fact = store.fact(receipt.factId)
    assert fact["qualifier"]["carrier"] == "顺丰"


def test_unknownQualifierKeyIsWarningNotBlock(store, registry):
    _admit(store, "订单Z", "is_a", "Order")
    k = store.resolveSubjectKey("default", "订单Z")
    registry.assignSubjectType(k, "Order")

    validator = OntologyValidationReport(registry)
    request = AdmissionRequest(
        agentId="default", subjectLabel="订单Z", predicateTermId="shipped_to",
        objectTerm="上海仓", content="", qualifier={"carrier": "顺丰", "mystery": "x"})

    kinds = {f["rule"]: f["kind"] for f in validator.findings(request, k)}
    assert kinds.get("qualifierSchema") == "warning", "未知键 warning 不阻断"
    assert "qualifierSchema" not in {f["rule"] for f in validator.violations(request, k)} \
        or all(f["kind"] != "violation" or "mystery" not in f["message"]
               for f in validator.violations(request, k))


def test_relationWithoutSchemaStaysFreeForm(store, registry):
    """未声明 schema 的关系：qualifier 自由 JSON（存量零漂移）。"""
    receipt = _admit(store, "订单W", "is_a", "Order", qualifier={"anything": 1})

    assert store.fact(receipt.factId)["qualifier"]["anything"] == 1
