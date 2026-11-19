# -*- coding: utf-8 -*-
"""P2-1 映射增强（transform 链 + missing 缺省策略）与 P2-2 版本 impact 预标注。

对照研究 P2-1/P2-2（reference_y 报告 §5）红灯：
- P2-1：`applyMapping` 支持 object 值变换链（upper/lower/trim/collapse_ws 闭集）
  与 missing 缺省策略（keep 缺省=现行为 / skip=整行跳过 / report=带 objectMissing
  标记）；摄取链对 skip 行如实记 finding，不拖累同批其他行。
- P2-2：`impactOfDiff` 把 pipeline diff 翻译成对方四态影响预标注
  （breaking / needs_remap / needs_reextraction / needs_rule_build），
  纯展示+审批辅助，不改任何判定链。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.enterprise.schema_mapping import (
    MappingError,
    applyMapping,
    validateDescriptor,
)
from neurova.knowledge.ontology.semver import impactOfDiff


def _map(descriptor, row):
    """applyMapping 的测试桥：registry 参数本域用例不需要（None=跳过术语存在性校验）。"""
    return applyMapping(descriptor, row, None)


# ── P2-1：transform 闭集与校验 ───────────────────────────

def _descriptor(**overrides):
    base = {
        "sourceType": "sql",
        "columns": ["id", "name", "city"],
        "subject": {"template": "客户:{name}"},
        "predicate": {"termId": "located_in"},
        "object": {"kind": "column", "column": "city"},
    }
    base.update(overrides)
    return base


class TestValidateTransform:

    def test_unknownTransformRejected(self):
        with pytest.raises(MappingError, match="transform"):
            validateDescriptor(_descriptor(object={
                "kind": "column", "column": "city", "transform": ["shell"]}), None)

    def test_knownTransformsAccepted(self):
        validateDescriptor(_descriptor(object={
            "kind": "column", "column": "city",
            "transform": ["trim", "upper", "collapse_ws"]}), None)

    def test_transformOnConstantObjectRejected(self):
        # term/literal 是常量语义，变换会破坏术语身份——编译期就拒
        with pytest.raises(MappingError, match="transform"):
            validateDescriptor(_descriptor(object={
                "kind": "term", "termId": "shanghai", "transform": ["upper"]}), None)

    def test_unknownMissingRejected(self):
        with pytest.raises(MappingError, match="missing"):
            validateDescriptor(_descriptor(missing="delete"), None)


# ── P2-1：applyMapping 行为 ──────────────────────────────

class TestApplyTransform:

    def test_transformChainApplied(self):
        out = _map(_descriptor(object={"kind": "column", "column": "city",
                                "transform": ["trim", "upper"]}),
            {"id": 1, "name": "kowloon", "city": " shanghai "})
        assert out["objectTerm"] == "SHANGHAI"

    def test_collapseWhitespace(self):
        out = _map(_descriptor(object={"kind": "column", "column": "city",
                                "transform": ["collapse_ws"]}),
            {"id": 1, "name": "a", "city": "new\t york  city"})
        assert out["objectTerm"] == "new york city"

    def test_templateObjectTransformed(self):
        out = _map(_descriptor(object={"kind": "template", "template": "{name}-{city}",
                                "transform": ["upper"]}),
            {"id": 1, "name": "acme", "city": "sh"})
        assert out["objectTerm"] == "ACME-SH"

    def test_constantObjectNotTransformed(self):
        out = _map(_descriptor(object={"kind": "literal", "value": "keep me"}),
            {"id": 1, "name": "a", "city": "b"})
        assert out["objectTerm"] == "keep me"

    def test_missingKeepIsDefaultBehavior(self):
        out = _map(_descriptor(), {"id": 1, "name": "a", "city": ""})
        assert out["objectTerm"] == ""

    def test_missingSkipReturnsNone(self):
        out = _map(_descriptor(missing="skip"),
                           {"id": 1, "name": "a", "city": "  "})
        assert out is None

    def test_missingSkipKeepsPresentValues(self):
        out = _map(_descriptor(missing="skip"),
                           {"id": 1, "name": "a", "city": "sh"})
        assert out is not None and out["objectTerm"] == "sh"

    def test_missingReportFlagsRow(self):
        out = _map(_descriptor(missing="report"),
                           {"id": 1, "name": "a", "city": ""})
        assert out["objectMissing"] is True
        assert out["objectTerm"] == ""


# ── P2-1：摄取链对 skip 行的隔离 ─────────────────────────

class TestIngestSkipsMissingRows:

    def test_skippedRowDoesNotBlockBatch(self, tmp_path, monkeypatch):
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            registry = OntologyTermRegistry(store)
            registry.register("located_in", "relation", label="位于")
            ingestor = EnterpriseIngestor(store)
            descriptor = {"sourceId": "s1", "tenantId": "default",
                          "agentId": "default", "sourceType": "sql",
                          "columns": ["id", "name", "city"],
                          "subject": {"template": "客户:{name}"},
                          "predicate": {"termId": "located_in"},
                          "object": {"kind": "column", "column": "city"},
                          "missing": "skip"}
            outcome = ingestor.ingestBatch(
                descriptor,
                [{"id": 1, "name": "a", "city": "sh"},
                 {"id": 2, "name": "b", "city": ""}])
            assert outcome["admitted"] == 1
            assert outcome["skipped"] == [{"index": 1, "reason": "missing_object"}]
        finally:
            store.close()


# ── P2-2：impactOfDiff 四态预标注 ────────────────────────

class TestImpactOfDiff:

    def test_removedTermIsBreaking(self):
        out = impactOfDiff({"terms": {"added": [], "removed": ["t1"], "changed": []},
                            "rules": {"added": [], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == ["breaking"]

    def test_parentChangeIsBreaking(self):
        out = impactOfDiff({"terms": {"added": [], "removed": [], "changed": [
            {"id": "t1", "from": {"parent_term_id": "a"},
             "to": {"parent_term_id": "b"}}]},
            "rules": {"added": [], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == ["breaking"]

    def test_datatypeChangeNeedsRemap(self):
        out = impactOfDiff({"terms": {"added": [], "removed": [], "changed": [
            {"id": "t1", "from": {"datatype": "text"},
             "to": {"datatype": "number"}}]},
            "rules": {"added": [], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == ["needs_remap"]

    def test_labelChangeNeedsReextraction(self):
        out = impactOfDiff({"terms": {"added": [], "removed": [], "changed": [
            {"id": "t1", "from": {"label": "旧名"},
             "to": {"label": "新名"}}]},
            "rules": {"added": [], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == ["needs_reextraction"]

    def test_ruleChangeNeedsRuleBuild(self):
        out = impactOfDiff({"terms": {"added": [], "removed": [], "changed": []},
                            "rules": {"added": ["r1"], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == ["needs_rule_build"]

    def test_addedTermHasNoImpact(self):
        out = impactOfDiff({"terms": {"added": ["t9"], "removed": [], "changed": []},
                            "rules": {"added": [], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == []

    def test_summaryCounts(self):
        out = impactOfDiff({
            "terms": {"added": [], "removed": ["t1"], "changed": [
                {"id": "t2", "from": {"datatype": "text"},
                 "to": {"datatype": "number"}}]},
            "rules": {"added": ["r1"], "removed": [], "changed": []}})
        assert out["summary"] == {"breaking": 1, "needs_remap": 1,
                                  "needs_reextraction": 0, "needs_rule_build": 1}

    def test_definitionOnlyChangeIsNoImpact(self):
        out = impactOfDiff({"terms": {"added": [], "removed": [], "changed": [
            {"id": "t1", "from": {"definition": "旧"}, "to": {"definition": "新"}}]},
            "rules": {"added": [], "removed": [], "changed": []}})
        assert out["items"][0]["impact"] == []
        assert out["summary"]["breaking"] == 0
