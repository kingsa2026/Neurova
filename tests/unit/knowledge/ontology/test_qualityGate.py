# -*- coding: utf-8 -*-
"""U6 质量门阈值化：metrics 全量可计算 + qualityGateCheck 阈值判定。

判据（走真实 store 装配，不打桩）：
- metrics 由 quality.py 同一趟 findings 扫描派生：孤儿类率/缺 label 率/逆关系单边数/
  父链环数/引用完整率/consistency（violation 级 findings 按术语数比例折减），
  不再存在静态 1.0；
- qualityGateCheck 按 thresholds 出 {passed, threshold_failures}，thresholds 全缺省即过，
  未知阈值键显式拒绝；
- 既有键（tenant_id/term_count/findings/metrics）语义不变，gate 键仅在给阈值时出现。
环/悬空引用等登记面本会拒绝的结构，用例以手工改库模拟"绕过登记面的脏库"，
与既有 test_ontologyQuality 的 inverseOneSided 用例同一手法。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    return OntologyTermRegistry(store)


def _report(store, **kw):
    from neurova.knowledge.ontology.quality import ontologyQualityReport

    return ontologyQualityReport(store, **kw)


def _curateCleanStore(registry):
    """把种子库收拾成真正零 findings：枚举种子 label=id 补可读名，
    无父类的上层根（Entity）补 module=core。全部走 declarePartial 生产写路径。"""
    for term in registry.terms(tenantId="default"):
        declared = {}
        if str(term.get("label") or "") == str(term["term_id"]):
            declared["label"] = "可读名-%s" % term["term_id"]
        if not term.get("parent_term_id") and not str(term.get("module") or ""):
            declared["module"] = "core"
        if declared:
            registry.declarePartial(str(term["term_id"]), term["kind"], declared)


def _gate(report, thresholds=None):
    from neurova.knowledge.ontology.quality import qualityGateCheck

    return qualityGateCheck(report, thresholds)


def _violations(report):
    return [f for f in report["findings"] if f.get("severity") != "info"]


class TestComputableMetrics:
    def test_consistencyFullScoreWhenNoViolations(self, store, registry):
        """零 violation ⇒ consistency=1.0（与既有语义衔接，不再是恒 1.0 的静态值）。

        种子库自带结构债（枚举术语 label=id、Entity 无 module），先收拾干净再验满分。"""
        _curateCleanStore(registry)
        report = _report(store, tenantId="default")
        assert _violations(report) == []
        assert report["metrics"]["consistency"] == 1.0
        assert report["metrics"]["coverage"] == 1.0

    def test_consistencyDerivesFromViolationCount(self, store, registry):
        """有违规按比例折减：consistency = max(0, 1 - violation数/术语数)。"""
        registry.register("lonely_class", "concept")  # 孤儿 + 缺 label → 2 条 warning 级
        report = _report(store, tenantId="default")
        total = report["term_count"]
        expected = round(max(0.0, 1.0 - len(_violations(report)) / max(total, 1)), 4)
        assert len(_violations(report)) >= 2
        assert report["metrics"]["consistency"] == expected
        assert report["metrics"]["consistency"] < 1.0

    def test_orphanRateAndMissingLabelRate(self, store, registry):
        registry.register("lonely_class", "concept")
        report = _report(store, tenantId="default")
        total = max(report["term_count"], 1)
        orphans = [f for f in report["findings"] if f["kind"] == "orphanClass"]
        noLabel = [f for f in report["findings"] if f["kind"] == "missingLabel"]
        assert len(orphans) >= 1 and len(noLabel) >= 1
        assert report["metrics"]["orphanRate"] == round(len(orphans) / total, 4)
        assert report["metrics"]["missingLabelRate"] == round(len(noLabel) / total, 4)

    def test_inverseOneSidedCount(self, store, registry):
        registry.register("rel_b", "relation", label="关系B")
        registry.register("rel_a", "relation", label="关系A", inverseOf="rel_b")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_terms SET inverse_of = '' WHERE term_id = 'rel_b'")
        report = _report(store, tenantId="default")
        onesided = [f for f in report["findings"] if f["kind"] == "inverseOneSided"]
        assert len(onesided) == 1
        assert report["metrics"]["inverseOneSidedCount"] == 1

    def test_parentCycleCount(self, store, registry):
        """登记面拒环；这里抓绕过登记面的脏库：a→b→c→a 记 1 个环。"""
        registry.register("cyc_a", "concept", label="环A")
        registry.register("cyc_b", "concept", label="环B", parentTermId="cyc_a")
        registry.register("cyc_c", "concept", label="环C", parentTermId="cyc_b")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_terms SET parent_term_id = 'cyc_c' WHERE term_id = 'cyc_a'")
        report = _report(store, tenantId="default")
        assert report["metrics"]["parentCycleCount"] == 1
        cycles = [f for f in report["findings"] if f["kind"] == "parentCycle"]
        assert len(cycles) == 1 and "cyc_a" in cycles[0]["message"]

    def test_referenceIntegrityDetectsDangling(self, store, registry):
        """引用完整率 = 1 - 悬空引用/总引用；父链指向未登记术语即悬空。"""
        registry.register("ref_parent", "concept", label="父")
        registry.register("ref_child", "concept", label="子", parentTermId="ref_parent")
        clean = _report(store, tenantId="default")
        assert clean["metrics"]["referenceIntegrity"] == 1.0
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_terms SET parent_term_id = 'ghost_term'"
                " WHERE term_id = 'ref_child'")
        report = _report(store, tenantId="default")
        assert report["metrics"]["referenceIntegrity"] < 1.0
        assert any(f["kind"] == "danglingReference" and f["target"] == "ref_child"
                   for f in report["findings"])


class TestReportShape:
    def test_existingKeysUnchangedAndGateOptional(self, store):
        """既有键语义不变；gate 键只在显式给 thresholds 时出现（只增不改）。"""
        report = _report(store, tenantId="default")
        assert {"tenant_id", "term_count", "findings", "metrics"} <= set(report)
        assert {"consistency", "conciseness"} <= set(report["metrics"])
        assert "gate" not in report
        gated = _report(store, tenantId="default", thresholds={})
        assert gated["gate"] == {"passed": True, "threshold_failures": []}

    def test_reportDeterministic(self, store, registry):
        registry.register("lonely_class", "concept")
        import json

        assert (json.dumps(_report(store, tenantId="default"), sort_keys=True)
                == json.dumps(_report(store, tenantId="default"), sort_keys=True))


class TestQualityGateCheck:
    def test_noThresholdsPasses(self, store):
        assert _gate(_report(store, tenantId="default")) == {
            "passed": True, "threshold_failures": []}

    def test_maxFindingsThreshold(self, store, registry):
        registry.register("lonely_class", "concept")
        report = _report(store, tenantId="default")
        failed = _gate(report, {"max_findings": 0})
        assert failed["passed"] is False
        assert len(failed["threshold_failures"]) == 1
        assert "max_findings" in failed["threshold_failures"][0]
        assert _gate(report, {"max_findings": len(report["findings"])})["passed"] is True

    def test_minCoverageThreshold(self, store, registry):
        """覆盖率 = 未被任何 findings 点名的术语占比：点名一个术语即 < 1。"""
        registry.register("lonely_class", "concept")
        report = _report(store, tenantId="default")
        assert report["metrics"]["coverage"] < 1.0
        assert _gate(report, {"min_coverage": 1.0})["passed"] is False
        assert _gate(report, {"min_coverage": 0.0})["passed"] is True

    def test_maxOrphanRateThreshold(self, store, registry):
        registry.register("lonely_class", "concept")
        report = _report(store, tenantId="default")
        assert report["metrics"]["orphanRate"] > 0.0
        assert _gate(report, {"max_orphan_rate": 0.0})["passed"] is False
        assert _gate(report, {"max_orphan_rate": 1.0})["passed"] is True

    def test_failuresInCanonicalOrder(self, store, registry):
        """threshold_failures 按固定判据顺序（min_coverage → max_findings → max_orphan_rate）。"""
        registry.register("lonely_class", "concept")
        report = _report(store, tenantId="default")
        result = _gate(report, {"max_orphan_rate": 0.0, "max_findings": 0,
                                "min_coverage": 1.0})
        assert result["passed"] is False
        names = [f.split(" ")[0] for f in result["threshold_failures"]]
        assert names == ["min_coverage", "max_findings", "max_orphan_rate"]

    def test_unknownThresholdRejected(self, store):
        with pytest.raises(ValueError, match="未知阈值"):
            _gate(_report(store, tenantId="default"), {"no_such_threshold": 1})
