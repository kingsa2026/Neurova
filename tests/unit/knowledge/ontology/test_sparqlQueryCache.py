# -*- coding: utf-8 -*-
"""升级卡 U2：SPARQL 查询缓存（带失效）。

判据全部走 `runSparqlQuery` 公开入口（真装配：真库、真投影、真 rdflib，
业务对象一律不打桩）；投影函数只挂**计数钩子**（包住真函数只计数，不改行为）
用于区分"命中缓存"与"直查重投影"。失效判据：库一动（插入事实）同查询必须
立即看到新事实——水印进键，键变即失效，不依赖任何写入口钩子。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology import sparql_query
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

#: 容量环境变量名（契约钉死：0=禁用，正整数=LRU 容量）
CAPACITY_ENV = "NEUROVA_ONTOLOGY_SPARQL_CACHE"

QUERY = ("PREFIX kbg: <https://neurova.local/knowledge/>"
         " SELECT ?s ?o WHERE { ?s kbg:linked ?o } LIMIT 10")
QUERY_LIMIT5 = ("PREFIX kbg: <https://neurova.local/knowledge/>"
                " SELECT ?s ?o WHERE { ?s kbg:linked ?o } LIMIT 5")


def _admit(gate, subject, predicate, obj, agentId="default"):
    """经生产咽喉写入一条事实（真装配，不走旁路）。"""
    content = "%s %s %s" % (subject, predicate, obj)
    gate.admit(AdmissionRequest(
        agentId=agentId, subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("linked", "relation")
    gate = productionAdmissionGate(s)
    _admit(gate, "设备A", "linked", "设备B")
    yield s, gate
    s.close()


@pytest.fixture
def projectionCalls(monkeypatch):
    """serializeAll 计数钩子：包真函数只计数——命中路径不应再重投影。"""
    import neurova.knowledge.ontology.turtle as turtle_mod

    calls = {"count": 0}
    real = turtle_mod.serializeAll

    def counting(store, *args, **kwargs):
        calls["count"] += 1
        return real(store, *args, **kwargs)

    monkeypatch.setattr(turtle_mod, "serializeAll", counting)
    return calls


class TestSparqlQueryCache:
    def test_secondRunHitsCache(self, kb, projectionCalls):
        """同一查询第二次执行命中缓存：不再重投影，结果与首查一致。"""
        s, _gate = kb
        first = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert first["rows"], "首查命中投影事实（真装配冒烟）"
        second = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                             tenantId="default")
        assert projectionCalls["count"] == 1, "第二次执行不得重投影（应命中缓存）"
        assert second == first, "命中结果与未命中路径逐字节一致"

    def test_newFactInvalidates(self, kb, projectionCalls):
        """插入新事实后同查询立即看到新事实——事实水印变化击穿旧键。"""
        s, gate = kb
        before = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                             tenantId="default")
        _admit(gate, "设备B", "linked", "设备C")
        after = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert projectionCalls["count"] == 2, "库变更后必须重投影（失效可靠）"
        assert {row["o"] for row in after["rows"]} == {"设备B", "设备C"}, \
            "新事实必须出现在查询结果里"
        assert len(after["rows"]) == len(before["rows"]) + 1
        again = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert again == after, "新结果重新入缓存，命中一致"
        assert projectionCalls["count"] == 2, "重查命中缓存，不重投影"

    def test_termUpsertInvalidates(self, kb, projectionCalls):
        """术语表变更（版本/updated_at 变化）同样击穿缓存。"""
        s, gate = kb
        registry = OntologyTermRegistry(s)
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        registry.register("linked", "relation", version="v2")
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        assert projectionCalls["count"] == 2, "术语指纹变化后必须重投影"

    def test_agentAndTenantKeysIsolated(self, kb):
        """不同 agentId / tenantId 键隔离：各查各的，结果互不串。"""
        s, gate = kb
        _admit(gate, "设备C", "linked", "设备D", agentId="agent-2")
        mine = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                           tenantId="default")
        other = sparql_query.runSparqlQuery(s, QUERY, agentId="agent-2",
                                            tenantId="default")
        assert {row["o"] for row in mine["rows"]} == {"设备B"}
        assert {row["o"] for row in other["rows"]} == {"设备D"}, \
            "agent 过滤互不串（键隔离且结果正确）"
        cache = getattr(s, "_sparqlProjectionCache")
        assert cache.stats()["size"] == 2, "两个 agent 键各占一条"
        tenantB = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                              tenantId="tenant-b")
        assert tenantB == mine, "租户在键里隔离；现行投影语义下读面不变"
        assert cache.stats()["size"] == 3, "租户键各占一条，不互相覆盖"

    def test_capacityOneEvictsViaEnv(self, kb, monkeypatch, projectionCalls):
        """容量 1：第二查询挤掉第一条，再查第一条必须重算（LRU 淘汰）。

        P1-1 起查询面分两层：行集缓存（本卡）之下还有投影图缓存——行集被
        挤掉重算的是「求值」，投影图仍可复用（不必重新 serializeAll）。
        淘汰语义改用行集缓存的 misses 计数钉住。
        """
        monkeypatch.setenv(CAPACITY_ENV, "1")
        s, _gate = kb
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        sparql_query.runSparqlQuery(s, QUERY_LIMIT5, agentId="default",
                                    tenantId="default")
        assert projectionCalls["count"] == 1, "投影图与行集解耦：两条查询共用一张图"
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        cache = getattr(s, "_sparqlProjectionCache")
        assert cache.stats()["misses"] == 3, "容量 1：三次查找全部未命中（LRU 淘汰）"
        assert projectionCalls["count"] == 1, "图仍有效：重算发生在求值层，不重投影"

    def test_zeroDisablesCache(self, kb, monkeypatch, projectionCalls):
        """环境变量 0=禁用缓存：两层（行集＋投影图）都关，两次执行都直查。"""
        monkeypatch.setenv(CAPACITY_ENV, "0")
        monkeypatch.setenv("NEUROVA_ONTOLOGY_GRAPH_CACHE", "0")
        s, _gate = kb
        first = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        second = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                             tenantId="default")
        assert projectionCalls["count"] == 2, "0=禁用：两次都直查"
        assert second == first
        assert getattr(s, "_sparqlProjectionCache").enabled is False
        assert getattr(s, "_sparqlGraphCache").enabled is False

    def test_invalidEnvFallsBackToDefaultCapacity(self, kb, monkeypatch):
        """非法环境变量值：回退缺省容量 128，不炸查询面。"""
        monkeypatch.setenv(CAPACITY_ENV, "not-a-number")
        s, _gate = kb
        result = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                             tenantId="default")
        assert result["rows"]
        cache = getattr(s, "_sparqlProjectionCache")
        assert cache.enabled is True
        assert cache.capacity == 128

    def test_cachedMatchesUncached(self, tmp_path, monkeypatch):
        """同一份数据：缓存命中 / 未命中 / 禁用三条路径结果逐字节一致。"""
        def build(dbName):
            s = KnowledgeFactStore(str(tmp_path / dbName))
            registry = OntologyTermRegistry(s)
            registry.register("linked", "relation")
            gate = productionAdmissionGate(s)
            _admit(gate, "设备A", "linked", "设备B")
            _admit(gate, "设备B", "linked", "设备C")
            return s

        sCached = build("cached.db")
        sDirect = build("direct.db")
        try:
            viaCacheMiss = sparql_query.runSparqlQuery(
                sCached, QUERY, agentId="default", tenantId="default")
            viaCacheHit = sparql_query.runSparqlQuery(
                sCached, QUERY, agentId="default", tenantId="default")
            monkeypatch.setenv(CAPACITY_ENV, "0")
            viaDirect = sparql_query.runSparqlQuery(
                sDirect, QUERY, agentId="default", tenantId="default")
            assert viaCacheMiss["row_count"] == 2
            assert viaCacheHit == viaCacheMiss, "命中与未命中逐字节一致"
            assert viaDirect == viaCacheMiss, "禁用路径与缓存路径逐字节一致"
        finally:
            sCached.close()
            sDirect.close()

    def test_validationStillFrontOfCache(self, kb, projectionCalls):
        """校验在前、缓存在后：写形/空查照拒，被拒查询不触发投影。"""
        s, _gate = kb
        with pytest.raises(ValueError, match="只读"):
            sparql_query.runSparqlQuery(s, "INSERT DATA { <a> <b> <c> }",
                                        agentId="default", tenantId="default")
        with pytest.raises(ValueError, match="为空"):
            sparql_query.runSparqlQuery(s, "   ", agentId="default",
                                        tenantId="default")
        assert projectionCalls["count"] == 0, "被拒查询不得触发投影"
        good = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                           tenantId="default")
        assert good["rows"]

    def test_rdflibUnavailableChecksBeforeCache(self, kb, monkeypatch,
                                                projectionCalls):
        """rdflib 可用性校验在缓存之前：未装时命中路径也显式 501。"""
        s, _gate = kb
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: False)
        with pytest.raises(sparql_query.SparqlNotSupported):
            sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                        tenantId="default")
        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: True)
        again = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert again["rows"]
        assert projectionCalls["count"] == 1, "501 那次不落缓存、不影响既有命中"

    def test_concurrentRunsConsistent(self, kb):
        """并发同查：结果一致、无异常（缓存与底座读面线程安全）。"""
        from concurrent.futures import ThreadPoolExecutor

        s, _gate = kb
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda _: sparql_query.runSparqlQuery(s, QUERY,
                                                      agentId="default",
                                                      tenantId="default"),
                range(8)))
        assert results[0]["rows"]
        assert all(r == results[0] for r in results), "并发结果一致"


class TestSparqlProjectionCacheUnit:
    """缓存类本身的 LRU 语义（键构造用真库指纹，不打桩）。"""

    def test_lruEvictionOrder(self, kb):
        from neurova.knowledge.ontology.query_cache import SparqlProjectionCache

        s, _gate = kb
        cache = SparqlProjectionCache(capacity=2)
        assert cache.enabled is True
        keyA = cache.buildKey(s, tenantId="default", agentId="default",
                              query="SELECT 1")
        keyB = cache.buildKey(s, tenantId="default", agentId="default",
                              query="SELECT 2")
        keyC = cache.buildKey(s, tenantId="default", agentId="default",
                              query="SELECT 3")
        snapshot = {"variables": ["x"], "rows": [{"x": "1"}],
                    "row_count": 1, "truncated": False}
        cache.store(keyA, snapshot)
        cache.store(keyB, snapshot)
        cache.lookup(keyA)  # A 变最近使用
        cache.store(keyC, snapshot)  # 挤掉最久未用的 B
        assert cache.lookup(keyB) is None, "容量 2：最久未用的 B 被淘汰"
        assert cache.lookup(keyA) is not None
        assert cache.lookup(keyC) is not None
        stats = cache.stats()
        assert stats["evictions"] >= 1 and stats["size"] == 2

    def test_lookupReturnsCopyNotSameObject(self, kb):
        """命中返回拷贝：调用方改写结果不得污染缓存里的快照。"""
        from neurova.knowledge.ontology.query_cache import SparqlProjectionCache

        s, _gate = kb
        cache = SparqlProjectionCache(capacity=4)
        key = cache.buildKey(s, tenantId="default", agentId="default",
                             query=QUERY)
        cache.store(key, {"variables": ["o"], "rows": [{"o": "设备B"}],
                          "row_count": 1, "truncated": False})
        hit = cache.lookup(key)
        hit["rows"][0]["o"] = "被篡改"
        hit["row_count"] = 99
        again = cache.lookup(key)
        assert again["rows"][0]["o"] == "设备B", "缓存快照不被调用方改写"
        assert again["row_count"] == 1

    def test_disabledCacheBypassesStorage(self, kb):
        """0 容量=禁用：lookup 恒未命中、store 不落地。"""
        from neurova.knowledge.ontology.query_cache import SparqlProjectionCache

        s, _gate = kb
        cache = SparqlProjectionCache(capacity=0)
        assert cache.enabled is False
        key = cache.buildKey(s, tenantId="default", agentId="default",
                             query=QUERY)
        cache.store(key, {"variables": [], "rows": [], "row_count": 0,
                          "truncated": False})
        assert cache.lookup(key) is None
        assert cache.stats()["size"] == 0
