# -*- coding: utf-8 -*-
"""B13 L9 负例：非法事实/坏形状按预期拒（升级计划 §12.10 设计 1）。"""

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
    registry = OntologyTermRegistry(s)
    registry.registerMany([
        {"termId": "Order", "kind": "concept"},
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"],
         "qualifierSchema": {"required": ["assessed_by"],
                             "allowed": {"assessed_by": "string"}}},
    ])
    key = s.upsertSubject("default", "订单N1")
    registry.assignSubjectType(key, "Order")
    yield s
    s.close()


def _admit(store, subject, predicate, obj, qualifier=None):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, qualifier=qualifier or {},
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}]))


def test_negative_domainViolationRejected(store):
    registry = OntologyTermRegistry(store)
    registry.register("weird", "relation", domain=["Ghost"])
    with pytest.raises(ValueError, match="本体校验未过"):
        _admit(store, "订单N1", "weird", "x")


def test_negative_missingQualifierRejected(store):
    with pytest.raises(ValueError, match="assessed_by"):
        _admit(store, "订单N1", "hasRiskLevel", "High")


def test_negative_unregisteredPredicateIsFreeFormNotBlocked(store):
    """未登记关系走 unregistered 免检（保守原则）——不拒，但 findings 有读数。"""
    receipt = _admit(store, "订单N1", "no_such_rel", "x")
    assert receipt.factId


def test_negative_punningIsWarningNotBlocked(store):
    validator = OntologyValidationReport(OntologyTermRegistry(store))
    request = AdmissionRequest(agentId="default", subjectLabel="Order",
                               predicateTermId="is_a", objectTerm="Entity",
                               content="", qualifier={})
    kinds = {f["kind"] for f in validator.findings(request, "Order")}
    assert "warning" in kinds and "violation" not in kinds
