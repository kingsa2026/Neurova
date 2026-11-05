# -*- coding: utf-8 -*-
"""B10 L4 约束层（升级计划 §12.5）：形状注册表＋同一求值器＋严重级。

判据：既有 6 项固定校验收编为内置 shape，与用户 shape 同一求值器（不复制第二套
规则）；violation 阻断、warning 记账、info 遥测；dry-run 与写前同 finding 同定位串。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.shapes import ShapeRegistry
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
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"]},
    ])
    return registry


def _gate(store):
    return productionAdmissionGate(store, toolVersion="b10")


def _admit(store, subject, predicate, obj, qualifier=None):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content, qualifier=qualifier or {},
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ))


class TestShapeRegistryCrud:
    def test_registerListAndDelete(self, store):
        shapes = ShapeRegistry(store)
        shapes.register(tenantId="default", shapeId="risk_enum", targetKind="relation",
                        targetTermId="hasRiskLevel",
                        pathJson={"predicate": "hasRiskLevel"},
                        constraintKind="in",
                        constraintJson={"values": ["High", "Low", "Medium"]},
                        severity="violation", message="风险等级取值越界")

        rows = shapes.list(tenantId="default")
        assert len(rows) == 1 and rows[0]["shape_id"] == "risk_enum"

        shapes.delete("risk_enum", tenantId="default")
        assert shapes.list(tenantId="default") == []

    def test_userShapeCollidingWithBuiltinRejected(self, store, registry):
        """同一 target/path/constraint 只保留一个来源：撞内置 shape 登记即拒。"""
        shapes = ShapeRegistry(store)
        with pytest.raises(ValueError, match="内置"):
            shapes.register(tenantId="default", shapeId="fake_domain",
                            targetKind="relation", targetTermId="hasRiskLevel",
                            pathJson={"predicate": "hasRiskLevel"},
                            constraintKind="domain", constraintJson={},
                            severity="violation", message="影子内置")


class TestShapeEvaluation:
    def test_inConstraintViolates(self, store, registry):
        shapes = ShapeRegistry(store)
        shapes.register(tenantId="default", shapeId="risk_enum", targetKind="relation",
                        targetTermId="hasRiskLevel",
                        pathJson={"predicate": "hasRiskLevel"},
                        constraintKind="in",
                        constraintJson={"values": ["High", "Low"]},
                        severity="violation", message="风险等级取值越界")

        with pytest.raises(ValueError, match="风险等级取值越界"):
            _admit(store, "订单D01", "hasRiskLevel", "Huge")

    def test_warningSeverityRecordsButDoesNotBlock(self, store, registry):
        shapes = ShapeRegistry(store)
        shapes.register(tenantId="default", shapeId="risk_hint", targetKind="relation",
                        targetTermId="hasRiskLevel",
                        pathJson={"predicate": "hasRiskLevel"},
                        constraintKind="in",
                        constraintJson={"values": ["High", "Low"]},
                        severity="warning", message="风险等级取值少见")

        receipt = _admit(store, "订单D01", "hasRiskLevel", "Huge")

        assert receipt.factId, "warning 记账不阻断"

    def test_patternConstraintOnObject(self, store, registry):
        shapes = ShapeRegistry(store)
        shapes.register(tenantId="default", shapeId="order_id_shape", targetKind="relation",
                        targetTermId="hasRiskLevel",
                        pathJson={"predicate": "hasRiskLevel"},
                        constraintKind="pattern",
                        constraintJson={"pattern": "^(High|Low|Medium)$"},
                        severity="violation", message="形状不符")
        _admit(store, "订单D01", "hasRiskLevel", "Medium")

        with pytest.raises(ValueError, match="形状不符"):
            _admit(store, "订单D02", "hasRiskLevel", "EXTREME")

    def test_builtinSixStillEnforcedThroughSameEvaluator(self, store, registry):
        """内置 6 项收编：domain 违规依旧在写前阻断（同一求值器出同一 finding）。"""
        registry.register("Ghost", "concept")
        registry.register("weird_rel", "relation", domain=["Order"])
        _admit(store, "游魂X", "is_a", "Ghost")
        key = store.resolveSubjectKey("default", "游魂X")
        registry.assignSubjectType(key, "Ghost")

        with pytest.raises(ValueError, match="定义域"):
            _admit(store, "游魂X", "weird_rel", "Ghost")

    def test_shapesAreTenantScoped(self, store, registry):
        shapes = ShapeRegistry(store)
        shapes.register(tenantId="tenant-a", shapeId="risk_enum", targetKind="relation",
                        targetTermId="hasRiskLevel",
                        pathJson={"predicate": "hasRiskLevel"},
                        constraintKind="in", constraintJson={"values": ["High"]},
                        severity="violation", message="tenant-a 限定")

        assert shapes.list(tenantId="tenant-b") == []
        _admit(store, "订单D01", "hasRiskLevel", "Low")  # tenant-b 的 shape 不影响 default 写入
