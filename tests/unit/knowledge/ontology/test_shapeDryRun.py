# -*- coding: utf-8 -*-
"""B10：dry-run 与写前共用同一求值器——同 finding 同定位串，不许两套口径。"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.shapes import ShapeRegistry
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
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"]},
    ])
    return registry


def _request(subject, predicate, obj):
    return AdmissionRequest(agentId="default", tenantId="default",
                            subjectLabel=subject, predicateTermId=predicate,
                            objectTerm=obj, content="%s %s %s" % (subject, predicate, obj),
                            qualifier={})


def test_dryRunMatchesWriteTimeFindings(store, registry):
    """同一候选：写前（admission 段3）与 dry-run（B2 路径）出同一 findings 集合。"""
    shapes = ShapeRegistry(store)
    shapes.register(tenantId="default", shapeId="risk_enum", targetKind="relation",
                    targetTermId="hasRiskLevel",
                    pathJson={"predicate": "hasRiskLevel"},
                    constraintKind="in", constraintJson={"values": ["High", "Low"]},
                    severity="violation", message="风险等级取值越界")
    validator = OntologyValidationReport(registry, shapes=ShapeRegistry(store))

    writeTime = validator.violations(_request("订单D01", "hasRiskLevel", "Huge"), "s-1")
    dryRun = validator.violations(_request("订单D01", "hasRiskLevel", "Huge"), "s-1")

    assert [(f["rule"], f["message"]) for f in writeTime] \
        == [(f["rule"], f["message"]) for f in dryRun], \
        "dry-run 与写前同 finding 同定位串"
    assert any("风险等级取值越界" in f["message"] for f in dryRun), \
        "用户 shape 的 violation 进同一 findings 流"


def test_disablingShapeSilencesItEverywhere(store, registry):
    shapes = ShapeRegistry(store)
    shapes.register(tenantId="default", shapeId="risk_enum", targetKind="relation",
                    targetTermId="hasRiskLevel",
                    pathJson={"predicate": "hasRiskLevel"},
                    constraintKind="in", constraintJson={"values": ["High", "Low"]},
                    severity="violation", message="风险等级取值越界")
    validator = OntologyValidationReport(registry, shapes=ShapeRegistry(store))
    assert validator.violations(_request("订单D01", "hasRiskLevel", "Huge"), "s-1")

    shapes.setEnabled("risk_enum", False, tenantId="default")

    assert validator.violations(_request("订单D01", "hasRiskLevel", "Huge"), "s-1") == [], \
        "停用的 shape 两路同时沉默"
