"""回填与读面（工单 011）。

核心判据是"关闸态逐位等于旧行为"——新链路一旦能在关闭时改变旧结果，
它就再也不是一根可选的开关，而是一次无法回退的替换。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.evaluation import RetrievalBenchmark
from neurova.knowledge.foundation.backfill import LegacyFactBackfill
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.read_surface import (
    FactSurface,
    FactSurfaceConfig,
    mergeIntoLegacy,
    recordHitsAsInjection,
)
from neurova.knowledge.foundation.reconcile import FoundationReconciler
from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture
def legacy(tmp_path) -> KnowledgeRepository:
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge("default", "蜂群并发成本护栏", "SwarmManager.spawn 做限流与成本记账",
                          owner_user_id="u1", source="import:note.txt")
    repo.create_knowledge("default", "同一篇笔记", "完全一样的正文内容", owner_user_id="u1")
    repo.create_knowledge("kai", "同一篇笔记", "完全一样的正文内容", owner_user_id="u1")
    return repo


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


class TestBackfill:
    def test_backfill_matches_reconcilePrediction(self, legacy, store):
        predicted = FoundationReconciler.plan(legacy)

        report = LegacyFactBackfill.run(legacy, store)

        assert report["mode"] == "apply"
        assert report["facts_after"] == predicted["predicted_facts"], "回填结果必须等于对账预测"
        assert report["subjects"] == predicted["predicted_subjects"]
        assert report["folded_rows"] == predicted["redundant_rows"]
        assert report["failures"] == []

    def test_backfillIsIdempotent(self, legacy, store):
        first = LegacyFactBackfill.run(legacy, store)

        second = LegacyFactBackfill.run(legacy, store)

        assert second["facts_after"] == first["facts_after"], "重跑回填不得翻倍"

    def test_everyBackfilledFactCarriesProvenance(self, legacy, store):
        LegacyFactBackfill.run(legacy, store)

        for fact in store.searchableFacts():
            assertions = store.assertions(fact["fact_id"])
            assert assertions, "回填行也必须可溯源，不许匿名入库"
            assert assertions[0]["medium_ref"]

    def test_backfillNeverInventsConfidenceFromNothing(self, legacy, store):
        LegacyFactBackfill.run(legacy, store)

        for fact in store.searchableFacts():
            assert fact["confidence"] is not None, "有断言即应有聚合出的置信度"
            assert fact["confidence"] <= 0.95, "回填不得给出满分置信"

    def test_dryRunWritesNothing(self, legacy, store):
        report = LegacyFactBackfill.run(legacy, store, dryRun=True)

        assert report["mode"] == "dry_run"
        assert store.factCount() == 0


class TestReadSurfaceGate:
    def test_gateOffKeepsLegacyResultsByteIdentical(self, legacy, store):
        LegacyFactBackfill.run(legacy, store)
        surface = FactSurface(store, FactSurfaceConfig(enabled=False))

        assert surface.enabled is False
        assert surface.search("蜂群 限流", limit=5) == [], "关闸必须自己就不产出候选，而不是指望调用方忘记调用"
        assert mergeIntoLegacy([{"knowledge_id": "a"}], [], limit=3) == [{"knowledge_id": "a", "record_kind": "narrative"}]

    def test_gateOnReturnsFactHitsWithLineageHandle(self, legacy, store):
        LegacyFactBackfill.run(legacy, store)
        surface = FactSurface(store, FactSurfaceConfig(enabled=True))

        hits = surface.search("SwarmManager 成本记账", limit=5)

        assert hits and hits[0]["record_kind"] == "fact"
        assert hits[0]["lineage_id"]

    def test_zeroWeightsReproducePureBm25Order(self, store, legacy):
        LegacyFactBackfill.run(legacy, store)
        tuned = FactSurface(store, FactSurfaceConfig(enabled=True, freshnessWeight=0.3,
                                                     confidenceWeight=0.4))
        plain = FactSurface(store, FactSurfaceConfig(enabled=True, freshnessWeight=0.0,
                                                     confidenceWeight=0.0))
        hits = tuned.search("笔记", limit=5)

        assert [h["knowledge_id"] for h in plain.rankHits(hits)] == \
               [h["knowledge_id"] for h in sorted(hits, key=lambda h: (-h["fact_score"],
                                                                      h["knowledge_id"]))]

    def test_mergeInterleavesBothPoolsWithoutLosingEither(self, legacy, store):
        LegacyFactBackfill.run(legacy, store)
        facts = FactSurface(store, FactSurfaceConfig(enabled=True)).search("笔记", limit=3)
        narrative = [{"knowledge_id": "kn_legacy_1"}, {"knowledge_id": "kn_legacy_2"}]

        merged = mergeIntoLegacy(narrative, facts, limit=5)

        assert {m["knowledge_id"] for m in merged} >= {"kn_legacy_1", "kn_legacy_2"}
        assert any(m.get("record_kind") == "fact" for m in merged)
        assert len(merged) == len({m["knowledge_id"] for m in merged}), "合并不得产生重复 id"

    def test_injectionCountingOnlyAppliesToFactHits(self, legacy, store):
        LegacyFactBackfill.run(legacy, store)
        factId = store.searchableFacts()[0]["fact_id"]

        changed = recordHitsAsInjection(store, [{"knowledge_id": factId, "record_kind": "fact"},
                                                 {"knowledge_id": "kn_x", "record_kind": "narrative"}])

        assert changed == 1
        assert store.fact(factId)["injected_count"] == 1

    def test_missingFactDoesNotBreakRetrieval(self, store):
        assert recordHitsAsInjection(store, [{"knowledge_id": "ghost", "record_kind": "fact"}]) == 0


class TestEndToEndAgainstRealPath:
    def test_benchmarkAgainstFactSurfaceRunsAndIsComparable(self, legacy, tmp_path):
        """读面切过去之后，同一把尺子必须还能跑出数（而不是因为空库报 0）。"""
        replayStore = KnowledgeFactStore(str(tmp_path / "replay.db"))
        LegacyFactBackfill.run(legacy, replayStore)
        bench = RetrievalBenchmark(str(tmp_path / "eval.db"))
        bench.addCase("蜂群并发成本护栏", [f["fact_id"] for f in replayStore.searchableFacts()
                                        if "蜂群" in f["canonical_label"] or "SwarmManager" in f["content"]])
        surface = FactSurface(replayStore, FactSurfaceConfig(enabled=True))

        hits = surface.search("蜂群并发成本护栏", limit=5)
        report = bench.run(legacy, user={"user_id": "u1"}, topK=5)

        assert hits, "切读面后仍无命中说明回填没进到可读态"
        assert report["measure_state"] == "measured"
        bench.close()
        replayStore.close()
