"""M-21 回归测试：时序知识图加载容错与 LIMIT 口径。

根因：temporal_knowledge_graph.py
- `SELECT * FROM temporal_facts LIMIT 50000` 截断后第 5 万条外的事实
  永远读不到（query_current 只遍历 _facts_cache）；
- `_load_facts_into_cache` 对每行直接 `RelationType(row[...])` /
  `FactStatus(row[...])` 枚举构造，单条坏行令 __init__ 直接崩。

修复后契约：
- 枚举/解析失败行逐行 try/except，warning 跳过，好行保留，__init__ 不崩；
- LIMIT 提为类级常量 FACTS_LOAD_LIMIT（默认 200000），截断 warning 保留。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.temporal_knowledge_graph import (
    TemporalKnowledgeGraph,
)

_TS = "2026-01-01T00:00:00+00:00"


def _seed_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.executescript(TemporalKnowledgeGraph._CREATE_SQL)
    for rid, relation, status in rows:
        conn.execute(
            """INSERT INTO temporal_facts
            (id,subject,predicate,object,relation_type,confidence,status,
             valid_from,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rid, "Alice", "likes", "Bob", relation, 1.0, status, _TS, _TS, _TS),
        )
    conn.commit()
    conn.close()


class TestM21BadRowTolerance:
    def test_bad_enum_rows_skipped_init_survives(self, tmp_path):
        db = tmp_path / "tkg1.db"
        _seed_db(
            db,
            [
                ("f-good-1", "related_to", "active"),
                ("f-bad-relation", "bogus_relation", "active"),
                ("f-bad-status", "is_a", "bogus_status"),
            ],
        )
        tkg = TemporalKnowledgeGraph(db_path=str(db))
        assert "f-good-1" in tkg._facts_cache, "好行丢失"
        assert "f-bad-relation" not in tkg._facts_cache
        assert "f-bad-status" not in tkg._facts_cache

    def test_query_current_works_after_skips(self, tmp_path):
        db = tmp_path / "tkg2.db"
        _seed_db(
            db,
            [
                ("f-good-1", "related_to", "active"),
                ("f-bad-1", "bogus_relation", "active"),
            ],
        )
        tkg = TemporalKnowledgeGraph(db_path=str(db))
        facts = tkg.query_current(subject="Alice")
        assert [f.id for f in facts] == ["f-good-1"]


class TestM21LoadLimitConstant:
    def test_limit_constant_exists_and_enlarged(self):
        assert hasattr(TemporalKnowledgeGraph, "FACTS_LOAD_LIMIT")
        assert TemporalKnowledgeGraph.FACTS_LOAD_LIMIT >= 200000

    def test_limit_is_enforced(self, tmp_path, monkeypatch):
        db = tmp_path / "tkg3.db"
        _seed_db(
            db,
            [(f"f-{i}", "related_to", "active") for i in range(5)],
        )
        monkeypatch.setattr(TemporalKnowledgeGraph, "FACTS_LOAD_LIMIT", 3)
        tkg = TemporalKnowledgeGraph(db_path=str(db))
        assert len(tkg._facts_cache) == 3, "LIMIT 常量未生效"
