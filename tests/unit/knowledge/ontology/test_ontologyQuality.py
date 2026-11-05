# -*- coding: utf-8 -*-
"""B13 L9 质量层（升级计划 §12.10）：OOPS! 结构子集／OQuaRE 风格指标／golden。

- OOPS! 结构子集：孤儿类/缺 label/父链成环/逆关系单边——按 severity 报告；
- OQuaRE 风格：consistency（零 violation）/conciseness（无重复 label）等可计算指标；
- golden：五格式导出固定小库快照，字符级比对，变更需显式更新。
不做完整 OOPS!/OntoClean/OQuaRE 认证（§6）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _seedStore(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    registry = OntologyTermRegistry(s)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单", "module": "core"},
        {"termId": "HighRiskOrder", "kind": "concept", "parentTermId": "Order",
         "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"],
         "cardinality": 1},
    ])
    gate = productionAdmissionGate(s)
    content = "订单D01 is_a HighRiskOrder"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单D01", predicateTermId=IS_A_PREDICATE,
        objectTerm="HighRiskOrder", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}]))
    return s, registry


class TestOopsStructuralSubset:
    def test_orphanClassDetected(self, tmp_path):
        store, registry = _seedStore(tmp_path)
        """孤儿类：无父类、无事实引用、非种子——severity=warning。"""
        from neurova.knowledge.ontology.quality import ontologyQualityReport

        registry.register("lonely_class", "concept")
        report = ontologyQualityReport(store, tenantId="default")
        orphan = [f for f in report["findings"] if f["kind"] == "orphanClass"]
        assert any("lonely_class" in f["target"] for f in orphan)

    def test_missingLabelDetected(self, tmp_path):
        store, registry = _seedStore(tmp_path)
        from neurova.knowledge.ontology.quality import ontologyQualityReport

        registry.register("no_label_term", "concept")
        report = ontologyQualityReport(store, tenantId="default")
        assert any(f["kind"] == "missingLabel" and "no_label_term" in f["target"]
                   for f in report["findings"])

    def test_inverseOneSidedDetected(self, tmp_path):
        store, registry = _seedStore(tmp_path)
        """逆关系单边（绕过登记补齐的手工改库路径）——结构告警。"""
        registry.register("rel_b", "relation")
        registry.register("rel_a", "relation", inverseOf="rel_b")
        # 手工把 rel_b 的 inverse_of 清掉（模拟绕过登记面的改库）
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_terms SET inverse_of = '' WHERE term_id = 'rel_b'")
        from neurova.knowledge.ontology.quality import ontologyQualityReport

        report = ontologyQualityReport(store, tenantId="default")
        assert any(f["kind"] == "inverseOneSided" for f in report["findings"])


class TestOquareStyleMetrics:
    def test_consistencyMetric(self, tmp_path):
        store, registry = _seedStore(tmp_path)
        from neurova.knowledge.ontology.quality import ontologyQualityReport

        report = ontologyQualityReport(store, tenantId="default")
        assert report["metrics"]["consistency"] == 1.0, "零 violation ⇒ 一致性满分"

    def test_concisenessMetric(self, tmp_path):
        store, registry = _seedStore(tmp_path)
        from neurova.knowledge.ontology.quality import ontologyQualityReport

        report = ontologyQualityReport(store, tenantId="default")
        assert 0.0 <= report["metrics"]["conciseness"] <= 1.0

    def test_qualityReportDeterministic(self, tmp_path):
        store, registry = _seedStore(tmp_path)
        from neurova.knowledge.ontology.quality import ontologyQualityReport

        assert (json.dumps(ontologyQualityReport(store, tenantId="default"), sort_keys=True)
                == json.dumps(ontologyQualityReport(store, tenantId="default"),
                              sort_keys=True))


class TestGoldenSnapshots:
    def test_turtleGolden(self, tmp_path):
        """Turtle golden：固定小库快照字符级比对；漂移需显式更新。"""
        from neurova.knowledge.ontology.turtle import serializeAll

        store, _registry = _seedStore(tmp_path)
        actual = serializeAll(store, tenantId="default")
        golden = GOLDEN_DIR / "turtle_golden.ttl"
        if not golden.exists():
            golden.write_text(actual, encoding="utf-8")
        assert actual == golden.read_text(encoding="utf-8"), \
            "Turtle golden 漂移——若为有意变更，请显式更新 golden 文件"

    def test_jsonldGolden(self, tmp_path):
        from neurova.knowledge.ontology.export.jsonld import exportJsonLd

        store, _registry = _seedStore(tmp_path)
        actual = exportJsonLd(store, tenantId="default")
        golden = GOLDEN_DIR / "jsonld_golden.json"
        if not golden.exists():
            golden.write_text(actual, encoding="utf-8")
        assert actual == golden.read_text(encoding="utf-8")
