# -*- coding: utf-8 -*-
"""种子锚点观测面红灯（SAG 对比 C1 后续观测项，2026-11-05）。

背景：N3 接线（1ff64cfe0）让 FactSurface.search 成为图走查的种子兜底，
C1 转正（0416a9031）实测了收益（recallΔ=+0.3333）但**大库成本未测**——
转正判定悬在「待大库成本读数」。本文件把观测项做成机制：

1. `seed_anchors` 快照段（仿 queryNorm/graphShadow 先例）：触发数、延迟
   avg/max、池规模 total/max、锚点数、种子驱动的走查命中数；
2. 观测跟闸走：NEUROVA_KB_FACT_SURFACE 关闸（默认）零记录——
   观测面不制造无信息量的噪声；
3. 转正判定据此读数：延迟达标＋anchors/walk_hits 非零 → 种子闸默认开；
   超限 → 池上限或保持关闸（规则落对比文档观测小节）。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger
from neurova.knowledge.foundation.read_surface import ENV_FLAG
from neurova.knowledge.retrieval_metrics import (
    RetrievalMetrics,
    get_retrieval_metrics,
    reset_retrieval_metrics,
)

AGENT = "seed-tele-test"


# ── 指标契约 ─────────────────────────────────────────────────────

def test_metricsSeedScanAndWalkHits_recordAndSnapshot():
    m = RetrievalMetrics()
    m.recordSeedScan(latencyMs=3.2, poolSize=1234, anchors=2)
    m.recordSeedScan(latencyMs=1.0, poolSize=2000, anchors=0)
    m.recordSeedWalkHits(walkHits=5)
    seg = m.snapshot()["seed_anchors"]
    assert seg["triggers"] == 2
    assert seg["latency_ms"]["avg"] == pytest.approx(2.1)
    assert seg["latency_ms"]["max"] == pytest.approx(3.2)
    assert seg["pool_size"] == {"total": 3234, "max": 2000}
    assert seg["anchors_total"] == 2
    assert seg["walk_hits_total"] == 5


def test_snapshotOmitsSeedSegment_whenUninstrumented():
    """零触发的快照不出现 seed_anchors 段（缺的读数不伪造 0——文件头纪律）。"""
    m = RetrievalMetrics()
    m.record(hits=1, elapsedMs=1.0)
    assert "seed_anchors" not in m.snapshot()


def test_resetClearsSeedSegment():
    m = RetrievalMetrics()
    m.recordSeedScan(latencyMs=1.0, poolSize=10, anchors=1)
    m.recordSeedWalkHits(walkHits=3)
    m.reset()
    assert "seed_anchors" not in m.snapshot()


def test_singletonSharesSeedReadings():
    """走查器写的是进程单例——观测面必须跨实例可见（adapter/端点读同一份）。"""
    reset_retrieval_metrics()
    try:
        get_retrieval_metrics().recordSeedScan(latencyMs=0.5, poolSize=8, anchors=1)
        assert get_retrieval_metrics().snapshot()["seed_anchors"]["triggers"] == 1
    finally:
        reset_retrieval_metrics()


# ── 走查器埋点咬合 ───────────────────────────────────────────────

@pytest.fixture()
def kb(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    ledger = KnowledgeLineageLedger(store, toolVersion="seed-tele")
    subjLake = store.upsertSubject(AGENT, "青海湖景区")
    subjProv = store.upsertSubject(AGENT, "青海省")
    subjCity = store.upsertSubject(AGENT, "西宁市")
    store.upsertFact(AGENT, subjLake, "located_in", "青海省", "青海湖景区是高原湖泊")
    factB = store.upsertFact(AGENT, subjProv, "capital_of", "西宁市", "青海省的省会城市")
    ledger.attach(factB, [{
        "actorType": "pipeline", "actorId": "seed-tele",
        "mediumRef": "entry:k1", "statementText": "西宁市资料见 k1",
    }])
    yield store
    store.close()


SEED_QUERY = "高原湖泊 所属省份 省会城市 资料"


def test_walkerEmitsSeedTelemetry_whenGateOn(kb, monkeypatch):
    """闸开：种子扫描与种子驱动的走查命中都进快照。"""
    monkeypatch.setenv(ENV_FLAG, "on")
    reset_retrieval_metrics()
    try:
        walker = GraphFactWalker(kb, agentId=AGENT)
        hops = walker.walkFromQuery(SEED_QUERY, maxHops=2, limit=6, tenantId="default")
        assert hops, "前置：种子锚点路径必须命中（N3 已接线）"
        seg = get_retrieval_metrics().snapshot()["seed_anchors"]
        assert seg["triggers"] == 1
        assert seg["pool_size"]["max"] == 2, "池规模＝可检索事实行数"
        assert seg["anchors_total"] >= 1
        assert seg["walk_hits_total"] == len(hops), "种子驱动的走查行数如实入账"
    finally:
        reset_retrieval_metrics()


def test_walkerEmitsNothing_whenGateOff(kb, monkeypatch):
    """闸关（默认）：观测面零记录——噪声不进快照。"""
    monkeypatch.delenv(ENV_FLAG, raising=False)
    reset_retrieval_metrics()
    try:
        walker = GraphFactWalker(kb, agentId=AGENT)
        assert walker.walkFromQuery(
            SEED_QUERY, maxHops=2, limit=6, tenantId="default"
        ) == []
        assert "seed_anchors" not in get_retrieval_metrics().snapshot()
    finally:
        reset_retrieval_metrics()


def test_walkerEmitsNothing_whenStrongPredicateHits(kb, monkeypatch):
    """强判据命中（子串锚点存在）：种子路径不触发，观测面零记录。"""
    monkeypatch.setenv(ENV_FLAG, "on")
    reset_retrieval_metrics()
    try:
        walker = GraphFactWalker(kb, agentId=AGENT)
        assert walker.walkFromQuery(
            "青海湖景区 所在省份的省会", maxHops=2, limit=6, tenantId="default"
        )
        assert "seed_anchors" not in get_retrieval_metrics().snapshot()
    finally:
        reset_retrieval_metrics()
