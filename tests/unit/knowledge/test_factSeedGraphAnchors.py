# -*- coding: utf-8 -*-
"""N3 断点接线红灯（SAG 对比 C1/N3，2026-11-05）。

断点：FactSurface.search（事实池 BM25 召回面，read_surface.py:73）全仓零调用
——011 否证「事实交织进主召回池」后遗留的排序面。本文件钉住其接线出路：
**多跳事实种子锚点**——查询零子串锚点（换说法/未登记别名）时，事实池 BM25
召回的事实行主体兜底成为 GraphFactWalker 走查锚点。

默认态纪律：NEUROVA_KB_FACT_SURFACE 闸关（默认）时 walkFromQuery 行为逐位
等于旧行为；闸开也不改变 subjectsMentionedIn 强判据的优先地位。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.foundation.graph_walk import SEED_ANCHOR_CAP, GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger
from neurova.knowledge.foundation.read_surface import ENV_FLAG

AGENT = "seed-test"


@pytest.fixture()
def kb(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    ledger = KnowledgeLineageLedger(store, toolVersion="seed-test")

    # 链：青海湖景区 --located_in--> 青海省 --capital_of--> 西宁市（entry 挂在省会事实）
    subjLake = store.upsertSubject(AGENT, "青海湖景区")
    subjProv = store.upsertSubject(AGENT, "青海省")
    subjCity = store.upsertSubject(AGENT, "西宁市")
    store.upsertFact(AGENT, subjLake, "located_in", "青海省", "青海湖景区是高原湖泊")
    factB = store.upsertFact(AGENT, subjProv, "capital_of", "西宁市", "青海省的省会城市")
    ledger.attach(factB, [{
        "actorType": "pipeline", "actorId": "seed-test",
        "mediumRef": "entry:k1", "statementText": "西宁市资料见 k1",
    }])
    yield store
    store.close()


SEED_QUERY = "高原湖泊 所属省份 省会城市 资料"  # 不含任何主体名的连续子串


def test_zeroAnchorQuery_misses_withoutSeed(kb):
    """旧行为基线：闸关（默认）时零子串锚点查询整路空转——逐位等于旧行为。"""
    walker = GraphFactWalker(kb, agentId=AGENT)
    assert walker.walkFromQuery(
        SEED_QUERY, maxHops=2, limit=6, tenantId="default"
    ) == []


def test_factSurfaceSeeds_graphWalkHits(kb, monkeypatch):
    """绿灯期望：开事实池闸后，BM25 种子主体兜底锚点，两跳走查命中 k1。"""
    monkeypatch.setenv(ENV_FLAG, "on")
    walker = GraphFactWalker(kb, agentId=AGENT)
    hops = walker.walkFromQuery(SEED_QUERY, maxHops=2, limit=6, tenantId="default")
    assert hops, "种子锚点必须让零子串查询的多跳走查活过来（N3 红灯）"
    entryIds = {str(h.get("entry_id") or "") for h in hops}
    assert "k1" in entryIds, "走查终点必须经 fact→entry 映射回条目"
    assert all(int(h.get("hop") or 0) >= 2 for h in hops), "走查口径 hop≥2 不破"


def test_seedAnchors_capped(kb, monkeypatch):
    """种子锚点上限：兜底召回不放开到全图（防 BM25 模糊召回放大走查）。"""
    monkeypatch.setenv(ENV_FLAG, "on")
    walker = GraphFactWalker(kb, agentId=AGENT)
    keys = walker._seedAnchors("高原湖泊 省会城市", "default")
    assert len(keys) <= SEED_ANCHOR_CAP
    assert all(isinstance(k, str) and k for k in keys)


def test_strongPredicate_stillWins_overSeeds(kb, monkeypatch):
    """强判据优先：子串命中的锚点与种子锚点共存时，走查口径不变（golden 同构）。"""
    monkeypatch.setenv(ENV_FLAG, "on")
    walker = GraphFactWalker(kb, agentId=AGENT)
    # 「青海湖景区」整串出现在查询里：强判据直接命中，种子只是并存补充
    hops = walker.walkFromQuery(
        "青海湖景区 所在省份的省会城市", maxHops=2, limit=6, tenantId="default"
    )
    assert hops, "强判据锚点的走查不得被种子逻辑干扰"
    assert "k1" in {str(h.get("entry_id") or "") for h in hops}
