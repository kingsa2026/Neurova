# -*- coding: utf-8 -*-
"""C1 转正红灯（SAG 对比候选 C1，2026-11-05）。

转正判据（specs/2026-10-30 §4.3「recall 不降、NDCG 提升才切 on」）已在
真管线实测达标：34 条目/4 链/12 用例，graph on vs off —— recallΔ=+0.0000、
NDCG@3Δ=+0.0615（compareVariants verdict=improved、gateNoRegression PASS）。
本文件钉住转正后的默认态：不设 env 时图路权重必须生效。

成本注记：shadow 态本就执行 walkFromQuery（只差权重生效），默认 on 不新增
走查成本；种子锚点（N3）仍受 NEUROVA_KB_FACT_SURFACE 闸默认关。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger

AGENT = "route-on-test"


@pytest.fixture()
def kb(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    ledger = KnowledgeLineageLedger(store, toolVersion="route-on-test")
    subjAlpha = store.upsertSubject(AGENT, "阿尔法指标")
    subjBeta = store.upsertSubject(AGENT, "贝塔维度")
    subjGamma = store.upsertSubject(AGENT, "伽马口径")
    store.upsertFact(AGENT, subjAlpha, "relates_to", "贝塔维度", "阿尔法关联贝塔")
    factB = store.upsertFact(AGENT, subjBeta, "belongs_to", "伽马口径", "贝塔归属伽马")
    ledger.attach(factB, [{
        "actorType": "pipeline", "actorId": "route-on-test",
        "mediumRef": "entry:k1", "statementText": "伽马口径细则见 k1",
    }])
    yield store
    store.close()


def test_graphRoute_defaultOn_withoutEnv(kb, monkeypatch):
    """无 env（生产默认）时图路权重必须生效——shadow 只是历史读数态。"""
    monkeypatch.delenv("NEUROVA_KB_GRAPH_ROUTE", raising=False)
    adapter = KnowledgeRetrieverAdapter(
        repo=None, graphWalker=GraphFactWalker(kb, agentId=AGENT)
    )
    context = SimpleNamespace(query="阿尔法指标 的执行口径", metadata={})
    ranks, support, weight = adapter._graphRoute(context, AGENT, 5)
    assert ranks, "强判据锚点的走查必须有秩返回"
    assert support, "秩必须带 fact→entry 证据"
    assert weight > 0.0, "转正后默认态 on：权重必须生效（C1 实测 NDCGΔ=+0.0615）"


def test_graphRoute_explicitOff_stillHonored(kb, monkeypatch):
    """显式 off 逃生门保持：运维可随时关闸回到零开销。"""
    monkeypatch.setenv("NEUROVA_KB_GRAPH_ROUTE", "off")
    adapter = KnowledgeRetrieverAdapter(
        repo=None, graphWalker=GraphFactWalker(kb, agentId=AGENT)
    )
    context = SimpleNamespace(query="阿尔法指标 的执行口径", metadata={})
    ranks, support, weight = adapter._graphRoute(context, AGENT, 5)
    assert ranks == [] and support == {} and weight == 0.0
