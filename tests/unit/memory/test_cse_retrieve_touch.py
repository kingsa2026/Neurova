"""006 · 结晶经验被检索 ⇒ `access_count` 必须真的涨（红绿灯 TDD）。

检索词用 ASCII token：CSE 的 FTS5 分词对 CJK 整句不切词（与 EKB 的 P2-B4 同源），
用中文查询会走进"命中与否取决于分词器"的噪声里，本票要钉的是 touch 记账不是分词。

根因：`UnifiedMemoryNode.access_count`（`:68`）与 `touch()`（`:71-75`）都在，
`store()` 也已持久化该列，唯独 `CognitiveStorageEngine.retrieve()`（`:442`）从不调
`touch()` —— 全仓 `touch()` 的调用方都在记忆侧 `manager.py`。于是结晶条目的
"被用过几次"永远停在写入值 0，007 想按使用度排序、017 想按冷热度淘汰都无据可依。

落定契约：
1. `retrieve()` 命中即 `touch()`（access_count +1、温度按 touch 语义强化、
   updated_at 刷新），且**落盘**——内存改了库里没改等于没改；
2. 反向锁：本轮没被返回的节点不得被记账；
3. L0 未 flush 的节点同样计数（对象引用稳定，flush 时按当前值落盘）。
"""

from __future__ import annotations

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
    UnifiedMemoryNode,
)


@pytest.fixture()
def engine(tmp_path):
    eng = CognitiveStorageEngine(agent_id="cse-06", data_dir=str(tmp_path / "cse"))
    yield eng
    eng._db.close()


def _db_access_count(engine: CognitiveStorageEngine, node_id: str):
    row = engine._db.execute(
        "SELECT access_count FROM memories WHERE id = ?", (node_id,)
    ).fetchone()
    return row[0] if row else None


def _store_hot(engine, content: str) -> str:
    nid = engine.store(UnifiedMemoryNode(content=content))
    engine._flush_l0_to_l1()
    return nid


class TestRetrieveTouches:
    def test_hit_bumps_access_count_in_memory_and_db(self, engine):
        nid = _store_hot(engine, "chain fetch_page then parse_html step")
        assert _db_access_count(engine, nid) == 0, "写入时计数应为 0（起点可判别）"

        hits = engine.retrieve("fetch_page", limit=5)
        assert [n.id for n in hits] == [nid], "对照：检索确实命中（否则本断言无意义）"
        assert hits[0].access_count == 1
        assert _db_access_count(engine, nid) == 1, "touch 必须落盘，内存改了库里没改等于没改"

    def test_repeated_queries_accumulate(self, engine):
        nid = _store_hot(engine, "chain fetch_page then parse_html step")
        for _ in range(3):
            engine.retrieve("fetch_page", limit=5)
        assert _db_access_count(engine, nid) == 3

    def test_unmatched_node_is_not_credited(self, engine):
        wanted = _store_hot(engine, "chain fetch_page then parse_html step")
        other = _store_hot(engine, "backup database to object store")
        hits = engine.retrieve("fetch_page", limit=5)
        assert {n.id for n in hits} == {wanted}
        assert _db_access_count(engine, other) == 0, "没被返回的节点不得记账"

    def test_l0_only_node_is_credited_and_survives_flush(self, engine):
        nid = engine.store(UnifiedMemoryNode(content="pending_flush_pattern"))
        hits = engine.retrieve("pending_flush_pattern", limit=5)
        assert [n.id for n in hits] == [nid]
        assert hits[0].access_count == 1
        engine._flush_l0_to_l1()
        assert _db_access_count(engine, nid) == 1, "L0 期间的计数不得在 flush 时被覆盖回 0"
