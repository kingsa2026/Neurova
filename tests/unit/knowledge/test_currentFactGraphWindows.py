# -*- coding: utf-8 -*-
"""P2-05 独立图谱分组：当前事实窗口、缓存水印与推导灰度同口径。"""

from __future__ import annotations

import datetime

import pytest

from neurova.knowledge.community_graph import (
    CommunityGraphBuilder,
    communityDriftSearch,
)
from neurova.knowledge.foundation import knowledge_facts
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.graph_analytics import (
    detectOntologyCommunities,
    graphOverview,
    kHopNeighbors,
    shortestPath,
)
from neurova.knowledge.ontology.graph_backend import SQLiteBackend
from neurova.knowledge.ontology.graph_projection_cache import _subjectFingerprints
from neurova.knowledge.ontology.query_cache import SparqlProjectionCache
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.sparql_query import projectionCacheFor, runSparqlQuery
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

UTC = datetime.timezone.utc
NOW = datetime.datetime(2030, 1, 1, 12, tzinfo=UTC)
PAST = NOW - datetime.timedelta(days=1)
FUTURE = NOW + datetime.timedelta(days=1)
EXPIRY = NOW + datetime.timedelta(hours=1)
ACTIVATION = NOW + datetime.timedelta(hours=2)
RECORDED_ACTIVATION = NOW + datetime.timedelta(hours=3)


@pytest.fixture
def factStore(tmp_path, monkeypatch):
    clock = {"now": NOW.isoformat()}
    monkeypatch.setattr(knowledge_facts, "_now", lambda: clock["now"])
    monkeypatch.delenv("NEUROVA_CONDITION_CLASSES_ROUTE", raising=False)
    store = KnowledgeFactStore(str(tmp_path / "current_fact_graph.db"))
    yield store, clock
    store.close()


def _fact(store, subject, predicate, obj, *, validFrom=None, validUntil=None,
          recordedAt=NOW.isoformat()):
    subjectKey = store.upsertSubject("default", subject)
    return store.upsertFact(
        "default", subjectKey, predicate, obj,
        "%s %s %s" % (subject, predicate, obj),
        recordedAt=recordedAt, validFrom=validFrom, validUntil=validUntil,
    )


def _seedWindowGraph(store):
    _fact(store, "窗口起点", "current", "当前桥",
          validFrom=NOW.isoformat(), validUntil=FUTURE.isoformat())
    _fact(store, "当前桥", "open", "开放终", validUntil="")
    _fact(store, "窗口起点", "at_start", "生效边界终", validFrom=NOW.isoformat())
    _fact(store, "窗口起点", "at_end", "到期边界终", validUntil=NOW.isoformat())
    _fact(store, "窗口起点", "expired", "过期桥", validUntil=PAST.isoformat())
    _fact(store, "窗口起点", "future", "未来桥", validFrom=FUTURE.isoformat())
    _fact(store, "窗口起点", "recorded_now", "入库边界终")
    _fact(store, "窗口起点", "recorded_future", "未来入库终",
          recordedAt=FUTURE.isoformat())
    inactive = _fact(store, "窗口起点", "inactive", "停用终")
    store.retract(inactive, "窗口测试停用")
    _fact(store, "当前桥", "head_future", "未来头终", validFrom=FUTURE.isoformat())
    _fact(store, "当前桥", "head_expired", "过期头终", validUntil=PAST.isoformat())
    _fact(store, "当前桥", "head_end", "边界头终", validUntil=NOW.isoformat())
    _fact(store, "未来桥", "future_leaf", "未来锚终")
    _fact(store, "过期桥", "expired_leaf", "过期锚终")


CURRENT_EDGES = {
    ("窗口起点", "current", "当前桥"),
    ("当前桥", "open", "开放终"),
    ("窗口起点", "at_start", "生效边界终"),
    ("窗口起点", "recorded_now", "入库边界终"),
    ("未来桥", "future_leaf", "未来锚终"),
    ("过期桥", "expired_leaf", "过期锚终"),
}


class TestCurrentFactWhere:
    def test_alias_and_boundaries_use_the_single_predicate(self, factStore):
        store, _clock = factStore
        _seedWindowGraph(store)
        clause, params = KnowledgeFactStore.currentFactWhere("f", NOW)

        assert params == [NOW.isoformat(), NOW.isoformat()]
        assert "COALESCE(NULLIF(f.valid_from, ''), f.recorded_at) <= ?" in clause
        assert "f.valid_until > ?" in clause
        rows = store.queryReadOnly(
            "SELECT s.canonical_label AS src, f.predicate_term_id AS pred,"
            " f.object_term AS dst FROM knowledge_facts f"
            " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
            " WHERE f.record_kind = 'triple' AND " + clause,
            tuple(params))
        assert {(row["src"], row["pred"], row["dst"]) for row in rows} == CURRENT_EDGES


class TestGraphReadSurfaces:
    def test_sqlite_backend_only_returns_current_triples(self, factStore):
        store, _clock = factStore
        _seedWindowGraph(store)

        rows = SQLiteBackend(store).activeTriples("default", "default")

        assert {(row["subject_label"], row["predicate_term_id"], row["object_term"])
                for row in rows} == CURRENT_EDGES

    def test_analytics_edges_and_reachability_use_current_window(self, factStore):
        store, _clock = factStore
        _seedWindowGraph(store)

        overview = graphOverview(store, agentId="default", tenantId="default")
        neighbors = kHopNeighbors(store, agentId="default", tenantId="default",
                                  startLabel="窗口起点", maxHops=1)
        path = shortestPath(store, agentId="default", tenantId="default",
                            fromLabel="窗口起点", toLabel="未来锚终")
        communities = detectOntologyCommunities(
            store, agentId="default", tenantId="default")

        assert overview["edges"] == len(CURRENT_EDGES)
        assert {node["label"] for node in neighbors["nodes"]} == {
            "窗口起点", "当前桥", "生效边界终", "入库边界终"}
        assert path["found"] is False
        assert communities["edges"] == len(CURRENT_EDGES)

    def test_community_detection_and_drift_ignore_non_current_neighbors(self, factStore):
        store, _clock = factStore
        _seedWindowGraph(store)
        builder = CommunityGraphBuilder(store, agentId="default", tenantId="default")

        _nodes, edges = builder._readGraph()
        builder.detect()
        hits = communityDriftSearch(store, "窗口起点", agentId="default",
                                    tenantId="default")

        assert set(edges) == {(src, dst) for src, _pred, dst in CURRENT_EDGES}
        assert hits
        assert all("未来桥" not in hit["labels"] and "过期桥" not in hit["labels"]
                   for hit in hits)


class TestGraphWalk:
    def test_relation_anchor_expansion_uses_current_facts(self, factStore):
        store, _clock = factStore
        OntologyTermRegistry(store).register(
            "window_relation", "relation", label="窗口关系")
        currentKey = store.upsertSubject("default", "当前扩展起点")
        futureKey = store.upsertSubject("default", "未来扩展起点")
        expiredKey = store.upsertSubject("default", "过期扩展起点")
        _fact(store, "当前扩展起点", "window_relation", "当前扩展对象",
              validFrom=NOW.isoformat())
        _fact(store, "未来扩展起点", "window_relation", "未来扩展对象",
              validFrom=FUTURE.isoformat())
        _fact(store, "过期扩展起点", "window_relation", "过期扩展对象",
              validUntil=PAST.isoformat())

        expanded = GraphFactWalker(store, agentId="default")._expandedAnchors(
            "窗口关系", "default", now=NOW)

        assert set(expanded) == {currentKey}
        assert futureKey not in expanded and expiredKey not in expanded

    def test_anchor_and_recursive_segments_share_current_window(self, factStore):
        store, _clock = factStore
        _seedWindowGraph(store)

        hops = GraphFactWalker(store, agentId="default").walkFromQuery(
            "窗口起点", maxHops=2, now=NOW)

        assert [hop["object"] for hop in hops] == ["开放终"]

    def test_observe_enforce_and_route_flag_survive_window_filter(self, factStore,
                                                                  monkeypatch):
        store, _clock = factStore
        engine = ForwardChainingEngine(store)
        observeRule = engine.registerRule(
            "rule_window_observe", "derived",
            [{"atom": "seed", "subject": "X", "object": "Y"}],
            materialization="observe")
        enforceRule = engine.registerRule(
            "rule_window_enforce", "derived",
            [{"atom": "seed", "subject": "X", "object": "Y"}],
            materialization="enforce")
        premise = _fact(store, "灰度起点", "seed", "seed")

        def derivedBridge(label, leaf, rule, **window):
            bridge = _fact(store, "灰度起点", "derived", label, **window)
            _fact(store, label, "leaf", leaf)
            store._derivationLedger.recordDerivation(bridge, [premise], rule)
            return bridge

        derivedBridge("观察桥", "观察叶", observeRule, validFrom=NOW.isoformat())
        derivedBridge("执行桥", "执行叶", enforceRule, validFrom=NOW.isoformat())
        derivedBridge("未来推导桥", "未来推导叶", enforceRule,
                      validFrom=FUTURE.isoformat())
        derivedBridge("过期推导桥", "过期推导叶", enforceRule,
                      validUntil=PAST.isoformat())
        _fact(store, "灰度起点", "explicit", "显式桥")
        _fact(store, "显式桥", "leaf", "显式叶")
        walker = GraphFactWalker(store, agentId="default")

        observed = {hop["object"]: hop for hop in walker.walkFromQuery(
            "灰度起点", maxHops=2, now=NOW)}
        assert set(observed) == {"执行叶", "显式叶"}
        assert observed["执行叶"]["via_derived"] is True
        assert observed["显式叶"]["via_derived"] is False

        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        enforced = {hop["object"]: hop for hop in walker.walkFromQuery(
            "灰度起点", maxHops=2, now=NOW)}
        assert set(enforced) == {"观察叶", "执行叶", "显式叶"}
        assert enforced["观察叶"]["via_derived"] is True


class TestGraphCaches:
    def test_projection_fingerprints_follow_visibility_boundaries(self, factStore):
        store, clock = factStore
        _fact(store, "到期主体", "linked", "到期客体", validUntil=EXPIRY.isoformat())
        _fact(store, "未来主体", "linked", "未来客体", validFrom=ACTIVATION.isoformat())
        _fact(store, "未来入库主体", "linked", "未来入库客体",
              recordedAt=RECORDED_ACTIVATION.isoformat())

        expiringKey = store.resolveSubjectKey("default", "到期主体")
        futureKey = store.resolveSubjectKey("default", "未来主体")
        recordedKey = store.resolveSubjectKey("default", "未来入库主体")
        assert set(_subjectFingerprints(store, "default", "default")) == {expiringKey}
        clock["now"] = (NOW + datetime.timedelta(minutes=30)).isoformat()
        assert set(_subjectFingerprints(store, "default", "default")) == {expiringKey}
        clock["now"] = EXPIRY.isoformat()
        assert _subjectFingerprints(store, "default", "default") == {}
        clock["now"] = ACTIVATION.isoformat()
        assert set(_subjectFingerprints(store, "default", "default")) == {futureKey}
        clock["now"] = RECORDED_ACTIVATION.isoformat()
        assert set(_subjectFingerprints(store, "default", "default")) == {
            futureKey, recordedKey}

    def test_query_cache_key_changes_at_validity_boundaries_not_by_ttl(self, factStore):
        store, clock = factStore
        _fact(store, "到期主体", "linked", "到期客体", validUntil=EXPIRY.isoformat())
        _fact(store, "未来主体", "linked", "未来客体", validFrom=ACTIVATION.isoformat())
        _fact(store, "未来入库主体", "linked", "未来入库客体",
              recordedAt=RECORDED_ACTIVATION.isoformat())
        cache = SparqlProjectionCache(capacity=4)
        snapshot = {"variables": ["o"], "rows": [{"o": "到期客体"}],
                    "row_count": 1, "truncated": False}
        key = cache.buildKey(store, "default", "default", "SELECT ?o")
        cache.store(key, snapshot)

        clock["now"] = (NOW + datetime.timedelta(minutes=30)).isoformat()
        assert cache.buildKey(store, "default", "default", "SELECT ?o") == key
        assert cache.lookup(key) == snapshot

        for boundary in (EXPIRY, ACTIVATION, RECORDED_ACTIVATION):
            clock["now"] = boundary.isoformat()
            nextKey = cache.buildKey(store, "default", "default", "SELECT ?o")
            assert nextKey != key, "时间跨过事实窗口后旧查询缓存必须失效"
            assert cache.lookup(nextKey) is None
            key = nextKey

    def test_real_sparql_pipeline_drops_expired_and_adds_future_rows(self, factStore):
        store, clock = factStore
        _fact(store, "缓存到期主体", "linked", "到期客体", validUntil=EXPIRY.isoformat())
        _fact(store, "缓存未来主体", "linked", "未来客体", validFrom=ACTIVATION.isoformat())
        query = ("PREFIX kbg: <https://neurova.local/knowledge/>"
                 " SELECT ?o WHERE { ?s kbg:linked ?o }")

        first = runSparqlQuery(store, query, agentId="default", tenantId="default")
        clock["now"] = (NOW + datetime.timedelta(minutes=30)).isoformat()
        assert runSparqlQuery(store, query, agentId="default",
                             tenantId="default") == first
        assert projectionCacheFor(store).stats()["hits"] == 1

        clock["now"] = EXPIRY.isoformat()
        expired = runSparqlQuery(store, query, agentId="default", tenantId="default")
        assert expired["rows"] == []

        clock["now"] = ACTIVATION.isoformat()
        activated = runSparqlQuery(store, query, agentId="default", tenantId="default")
        assert [row["o"] for row in activated["rows"]] == ["未来客体"]
