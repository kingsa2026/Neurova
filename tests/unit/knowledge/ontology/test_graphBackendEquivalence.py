# -*- coding: utf-8 -*-
"""C 维增强批 P1-2：SQLite↔oxigraph 图后端**同操作序列等价对拍**。

test_graphBackend.py 的契约对拍是"两实现各自对照期望"；本文件把**同一份
操作序列**（多术语/多租户/多 agent 三元组＋同内容重写）分别灌进两个实现，
读面快照必须逐行一致——第二实现由此从"能力证明"转正为"可信实现"。

pyoxigraph 缺席时 importorskip（CI 清单已常装，见 requirements-ci.txt）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.graph_backend import OxigraphBackend, SQLiteBackend

#: 同一份操作序列：(种类, 租户, agent, 术语/主语, 谓词/kind, 客体/标签)
OPS = [
    ("concept", "default", "", "customer", "concept", "客户"),
    ("concept", "default", "", "order", "concept", "订单"),
    ("concept", "default", "", "linked", "relation", "关联"),
    ("triple", "default", "agent-1", "客户A", "linked", "订单1"),
    ("triple", "default", "agent-2", "订单1", "linked", "客户A"),
    ("triple", "default", "agent-1", "客户A", "linked", "订单2"),
    ("triple", "tenant-b", "agent-1", "客户A", "linked", "订单1"),
]

TRIPLE_OPS = [op for op in OPS if op[0] == "triple"]


def _apply(backend, ops):
    for kind, tenant, agent, term, pred, obj in ops:
        if kind == "concept":
            backend.writeConceptTerm(tenantId=tenant, termId=term,
                                     label=obj, kind=pred)
        else:
            backend.writeTriple(tenantId=tenant, agentId=agent,
                                subjectLabel=term, predicateTermId=pred,
                                objectTerm=obj)


def _snapshot(backend) -> dict:
    """读面快照：概念（default 租户）＋四个过滤域的 active triple。"""
    return {
        "concepts_default": backend.conceptTerms("default"),
        "triples_default": backend.activeTriples("default"),
        "triples_agent1": backend.activeTriples("default", "agent-1"),
        "triples_agent2": backend.activeTriples("default", "agent-2"),
        "triples_tenant_b": backend.activeTriples("tenant-b"),
    }


def _delta(before: dict, after: dict) -> dict:
    """状态增量：after 相对 before 新增的行（按域）。

    sqlite 侧的 ontology_terms 在库初始化时播种了上层本体（upper_lite 七类），
    ox 侧从空白开始——等价判据比的是**同一操作序列造成的状态增量**，不是
    各自的绝对基线（基线差异是实现形态的既定事实，不是契约分歧）。
    """
    out: dict = {}
    for key in after:
        beforeRows = [tuple(sorted(r.items())) for r in before[key]]
        out[key] = [r for r in after[key]
                    if tuple(sorted(r.items())) not in beforeRows]
    return out


def _sqliteBackend(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "equiv.db"))
    try:
        yield SQLiteBackend(store)
    finally:
        store.close()


def _oxigraphBackend():
    pytest.importorskip(
        "pyoxigraph",
        reason="pyoxigraph 未安装——可选依赖（CI 清单常装），缺席时本判据 skip")
    yield OxigraphBackend()


@pytest.fixture
def sqliteBackend(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "equiv.db"))
    try:
        yield SQLiteBackend(store)
    finally:
        store.close()


@pytest.fixture
def oxiBackend():
    yield from _oxigraphBackend()


class TestBackendEquivalence:
    def test_sameOpsProduceIdenticalReads(self, sqliteBackend, oxiBackend,
                                          tmp_path):
        """同一操作序列灌进两实现，五个读域的**状态增量**逐行一致。"""
        # 预热：sqlite 侧术语注册表首用时播种上层本体/内置术语——先触发
        # 播种再取基线，增量里就只剩操作本身造成的行
        warmup = ("concept", "default", "", "__warmup__", "concept", "预热")
        _apply(sqliteBackend, [warmup])
        _apply(oxiBackend, [warmup])
        beforeSql = _snapshot(sqliteBackend)
        beforeOxi = _snapshot(oxiBackend)
        _apply(sqliteBackend, OPS)
        _apply(oxiBackend, OPS)
        assert _delta(beforeSql, _snapshot(sqliteBackend)) == \
            _delta(beforeOxi, _snapshot(oxiBackend))

    def test_rewriteSameTripleIsIdempotent(self, sqliteBackend, oxiBackend):
        """同内容三元组重写：两实现读面都只有一行（内容键幂等）。"""
        for backend in (sqliteBackend, oxiBackend):
            backend.writeTriple(tenantId="default", agentId="agent-1",
                                subjectLabel="客户A", predicateTermId="linked",
                                objectTerm="订单1")
            backend.writeTriple(tenantId="default", agentId="agent-1",
                                subjectLabel="客户A", predicateTermId="linked",
                                objectTerm="订单1")
            rows = backend.activeTriples("default", "agent-1")
            assert rows == [{"subject_label": "客户A",
                             "predicate_term_id": "linked",
                             "object_term": "订单1"}], \
                "重写同内容不得产生第二行（%s）" % backend.backendName()

    def test_tenantIsolationSymmetric(self, sqliteBackend, oxiBackend):
        """租户隔离对称：tenant-b 的写入不进 default 读面，反之亦然。"""
        _apply(sqliteBackend, OPS)
        _apply(oxiBackend, OPS)
        for backend in (sqliteBackend, oxiBackend):
            defaultLabels = {row["subject_label"]
                             for row in backend.activeTriples("default")}
            tenantBLabels = {row["subject_label"]
                             for row in backend.activeTriples("tenant-b")}
            assert defaultLabels == {"客户A", "订单1"}
            assert tenantBLabels == {"客户A"}
            assert backend.conceptTerms("tenant-b") == [], \
                "概念只注册在 default 租户"
