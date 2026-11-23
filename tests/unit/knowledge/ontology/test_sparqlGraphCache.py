# -*- coding: utf-8 -*-
"""C 维增强批 P1-1：SPARQL 投影图缓存与增量投影。

判据全部走 `runSparqlQuery` 公开入口（真库、真投影、真 rdflib，不打桩）；
`serializeAll` 只挂**捕获钩子**（包真函数，记录每次调用的 subjectKeys 形参），
用于区分「全量重投影」与「按脏主体增量投影」。正确性锚点：任何变异序列
（新增/改写/撤回/新主体）之后，增量路径的查询结果必须与全新库的全量重建
**逐字节一致**。
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

#: 图缓存容量环境变量名（契约钉死：0=禁用回退全量重投影）
GRAPH_CACHE_ENV = "NEUROVA_ONTOLOGY_GRAPH_CACHE"

QUERY = ("PREFIX kbg: <https://neurova.local/knowledge/>"
         " SELECT ?s ?o WHERE { ?s kbg:linked ?o } LIMIT 50")
# 等价对拍的第二查询：**不带 LIMIT**——LIMIT 截断在匹配行多于上限时取哪几行
# 由求值器迭代序决定（未排序的行序本就未定义），跨图历史比较无意义
QUERY_OBJ = ("PREFIX kbg: <https://neurova.local/knowledge/>"
             " SELECT ?o WHERE { ?s kbg:linked ?o }")


def _admit(gate, subject, predicate, obj, agentId="default"):
    content = "%s %s %s" % (subject, predicate, obj)
    gate.admit(AdmissionRequest(
        agentId=agentId, subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))


def _subjectKeysOf(store, label):
    rows = store.queryReadOnly(
        "SELECT subject_key FROM knowledge_subjects WHERE canonical_label = ?",
        (label,))
    return {str(r["subject_key"]) for r in rows}


def _factIdOf(store, label):
    rows = store.queryReadOnly(
        "SELECT fact_id FROM knowledge_facts WHERE subject_key IN"
        " (SELECT subject_key FROM knowledge_subjects WHERE canonical_label = ?)",
        (label,))
    return str(rows[0]["fact_id"])


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("linked", "relation")
    gate = productionAdmissionGate(s)
    _admit(gate, "设备A", "linked", "设备B")
    yield s, gate, registry
    s.close()


@pytest.fixture
def projectionCapture(monkeypatch):
    """serializeAll 捕获钩子：包真函数，记录每次调用的 subjectKeys 形参。"""
    import neurova.knowledge.ontology.turtle as turtle_mod

    calls: list = []
    real = turtle_mod.serializeAll

    def capturing(store, *args, **kwargs):
        calls.append({"subjectKeys": kwargs.get("subjectKeys")})
        return real(store, *args, **kwargs)

    monkeypatch.setattr(turtle_mod, "serializeAll", capturing)
    return calls


class TestIncrementalProjection:
    def test_mutationReprojectsOnlyDirtySubject(self, kb, projectionCapture):
        """既有主体追加事实后，重查只增量投影该脏主体，不全文重投影。"""
        s, gate, _registry = kb
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        assert projectionCapture[-1]["subjectKeys"] is None, "首查全量建图"
        _admit(gate, "设备A", "linked", "设备X")
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        assert len(projectionCapture) == 2, "水印变化只触发一次投影"
        assert set(projectionCapture[-1]["subjectKeys"] or []) == \
            _subjectKeysOf(s, "设备A"), "增量投影必须只圈脏主体"

    def test_newSubjectEntersGraphIncrementally(self, kb, projectionCapture):
        """新主体同样走增量：圈定的是新主体的 subject_key。"""
        s, gate, _registry = kb
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        _admit(gate, "设备C", "linked", "设备D")
        after = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert set(projectionCapture[-1]["subjectKeys"] or []) == \
            _subjectKeysOf(s, "设备C")
        assert {row["o"] for row in after["rows"]} >= {"设备D"}, "新主体立即可查"

    def test_retractedFactLeavesGraph(self, kb, projectionCapture):
        """撤回主体唯一事实后，该主体从投影图里摘除——纯摘除无需重投影。"""
        s, gate, _registry = kb
        _admit(gate, "设备C", "linked", "设备D")
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        s.retract(_factIdOf(s, "设备C"), "单测撤回")
        after = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert [row["o"] for row in after["rows"]] == ["设备B"], \
            "撤回主体的行必须从结果里消失"
        assert len({row["s"] for row in after["rows"]}) == 1, "只剩设备A一个主体"
        assert len(projectionCapture) == 1, \
            "纯摘除在图内完成（无脏主体要重投影），不触发 serializeAll"

    def test_inPlaceUpdateVisibleImmediately(self, kb, projectionCapture):
        """就地 UPDATE（主体合并/回滚形态）：主体指纹校验和必须抓到并增量重投影。"""
        s, _gate, _registry = kb
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        key = next(iter(_subjectKeysOf(s, "设备A")))
        with s._lock, s._conn:
            s._conn.execute(
                "UPDATE knowledge_facts SET object_term = '设备Z'"
                " WHERE subject_key = ?", (key,))
        after = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        assert {row["o"] for row in after["rows"]} == {"设备Z"}, \
            "就地改写必须立刻反映到查询结果"
        assert set(projectionCapture[-1]["subjectKeys"] or []) == {key}

    def test_termChangeRebuildsWholeProjection(self, kb, projectionCapture):
        """术语/规则指纹变化（本体结构变更）→ 整图重建，不做增量拼接。"""
        s, _gate, registry = kb
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        registry.register("linked", "relation", version="v2")
        sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                    tenantId="default")
        assert projectionCapture[-1]["subjectKeys"] is None, \
            "本体结构变更走全量重建"

    def test_incrementalMatchesFullRebuild(self, tmp_path, projectionCapture):
        """核心等价判据：任意变异序列后，增量路径与全新库全量重建逐字节一致。"""
        def build(name):
            s = KnowledgeFactStore(str(tmp_path / name))
            registry = OntologyTermRegistry(s)
            registry.register("linked", "relation")
            gate = productionAdmissionGate(s)
            return s, gate

        sInc, gateInc = build("incremental.db")
        try:
            for subject, obj in (("甲", "乙"), ("乙", "丙"), ("丙", "丁"),
                                 ("丁", "甲")):
                _admit(gateInc, subject, "linked", obj)
            sparql_query.runSparqlQuery(sInc, QUERY, agentId="default",
                                        tenantId="default")
            # 变异序列：改既有 / 撤回 / 新增 / 就地改写
            _admit(gateInc, "甲", "linked", "戊")
            sInc.retract(_factIdOf(sInc, "丙"), "等价判据撤回")
            _admit(gateInc, "己", "linked", "庚")
            key = next(iter(_subjectKeysOf(sInc, "乙")))
            with sInc._lock, sInc._conn:
                sInc._conn.execute(
                    "UPDATE knowledge_facts SET object_term = '辛'"
                    " WHERE subject_key = ?", (key,))
            incQ1 = sparql_query.runSparqlQuery(sInc, QUERY, agentId="default",
                                                tenantId="default")
            incQ2 = sparql_query.runSparqlQuery(sInc, QUERY_OBJ,
                                                agentId="default",
                                                tenantId="default")

            sFull, _gateFull = build("full.db")
            try:
                # 终态 = 增量库变异后的活跃事实：甲→乙被甲→戊冲突取代、
                # 丙→丁被撤回、乙→丙就地改写为乙→辛、新增己→庚
                for subject, obj in (("乙", "辛"), ("丁", "甲"),
                                     ("甲", "戊"), ("己", "庚")):
                    _admit(_gateFull, subject, "linked", obj)
                fullQ1 = sparql_query.runSparqlQuery(
                    sFull, QUERY, agentId="default", tenantId="default")
                fullQ2 = sparql_query.runSparqlQuery(
                    sFull, QUERY_OBJ, agentId="default", tenantId="default")
            finally:
                sFull.close()
            assert incQ1 == fullQ1, "增量路径与全量重建逐字节一致（SELECT）"
            assert incQ2 == fullQ2, "增量路径与全量重建逐字节一致（无 LIMIT 第二查询）"
        finally:
            sInc.close()

    def test_graphCacheDisabledFallsBackToFull(self, kb, monkeypatch,
                                               projectionCapture):
        """图缓存 0=禁用：两次查询都走全量重投影，结果仍正确。"""
        s, gate, _registry = kb
        monkeypatch.setenv(GRAPH_CACHE_ENV, "0")
        first = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                            tenantId="default")
        _admit(gate, "设备A", "linked", "设备X")
        second = sparql_query.runSparqlQuery(s, QUERY, agentId="default",
                                             tenantId="default")
        assert len(projectionCapture) == 2, "禁用态：两次查询都全量重投影"
        assert all(call["subjectKeys"] is None for call in projectionCapture), \
            "禁用态：无增量拼接，全部整库投影"
        assert {row["o"] for row in first["rows"]} == {"设备B"}
        # 同主体同谓词的新断言按冲突消解取代旧值（conflict auto_resolved）
        assert {row["o"] for row in second["rows"]} == {"设备X"}
