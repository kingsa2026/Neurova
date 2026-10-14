"""006 · 记忆被检索 ⇒ `access_count` 必须真的涨（内存侧与库侧同值）。

根因与原判一致：`retrieve()` 曾经从不记账，结晶条目的"被用过几次"永远停在写入值 0，
007 想按使用度排序、017 想按冷热度淘汰都无据可依。

双根收口后记账分两半，判据一句没松：

- 已并进正文的行 → `MemoryManager._creditRecallHits` 在**同一次检索**里 DB 侧自增
  （不回写内存值，避免读-改-写覆盖并发 increment），并把记账后的值回给调用方；
- 还压在 L0、没 flush 的节点 → 引擎补一次 `touch()`，其计数随 flush 落盘。

检索词仍用 ASCII token：本票要钉的是 touch 记账，不是分词器。
"""

from __future__ import annotations

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
from tests.cognitive_body_store import bodyManager, cognitiveEngine

AGENT = "cse-06"


@pytest.fixture()
def body(tmp_path):
    manager = bodyManager(tmp_path, agentId=AGENT)
    engine = cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)
    return manager, engine


def _dbAccessCount(manager, nodeId: str):
    conn = sqlite3.connect(str(manager.persistenceDbPath()))
    try:
        row = conn.execute(
            "SELECT access_count FROM memories WHERE id = ?", (nodeId,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _storeHot(engine, content: str) -> str:
    nid = engine.store(UnifiedMemoryNode(content=content))
    engine._flushL0ToBody()
    return nid


class TestRetrieveTouches:
    def test_hit_bumps_access_count_in_memory_and_db(self, body):
        manager, engine = body
        nid = _storeHot(engine, "chain fetch_page then parse_html step")
        assert _dbAccessCount(manager, nid) == 0, "写入时计数应为 0（起点可判别）"

        hits = engine.retrieve("fetch_page", limit=5)
        assert [n.id for n in hits] == [nid], "对照：检索确实命中（否则本断言无意义）"
        assert hits[0].access_count == 1
        assert _dbAccessCount(manager, nid) == 1, "touch 必须落盘，内存改了库里没改等于没改"

    def test_repeated_queries_accumulate(self, body):
        manager, engine = body
        nid = _storeHot(engine, "chain fetch_page then parse_html step")
        for _ in range(3):
            engine.retrieve("fetch_page", limit=5)
        assert _dbAccessCount(manager, nid) == 3

    def test_unmatched_node_is_not_credited(self, body):
        manager, engine = body
        wanted = _storeHot(engine, "chain fetch_page then parse_html step")
        other = _storeHot(engine, "backup database to object store")
        hits = engine.retrieve("fetch_page", limit=5)
        assert {n.id for n in hits} == {wanted}
        assert _dbAccessCount(manager, other) == 0, "没被返回的节点不得记账"

    def test_l0_only_node_is_credited_and_survives_flush(self, body):
        manager, engine = body
        nid = engine.store(UnifiedMemoryNode(content="pending_flush_pattern"))
        hits = engine.retrieve("pending_flush_pattern", limit=5)
        assert [n.id for n in hits] == [nid]
        assert hits[0].access_count == 1
        engine._flushL0ToBody()
        assert _dbAccessCount(manager, nid) == 1, "L0 期间的计数不得在 flush 时被覆盖回 0"
