"""
P1-1③ 驱逐台账持久化 — SQLite WAL + FTS5 红测

语义：
- record：驱逐即落库（含三元组隔离列）
- search：FTS5 全文检索（多用户强制 WHERE 分区，沿 _PersistDbStore 模式）
- 重启后可召回（验收口径：新实例同库可查）
- GC：keep_count / keep_days
"""

import time

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB


@pytest.fixture
def ledger(tmp_path):
    return EvictionLedgerDB(
        db_path=tmp_path / "ledger.db",
        user_id="u1",
        agent_id="a1",
    )


class TestRecordAndSearch:
    def test_record_then_fts_search_hits(self, ledger):
        ledger.record(content="用户询问了北京天气预报", turn_id="turn_1", session_id="s1")
        ledger.record(content="讨论了 PostgreSQL 索引优化", turn_id="turn_2", session_id="s1")

        hits = ledger.search("北京天气", session_id="s1")
        assert len(hits) == 1
        assert "北京天气预报" in hits[0]["content"]
        assert hits[0]["turn_id"] == "turn_1"

    def test_search_without_query_returns_recent_first(self, ledger):
        ledger.record(content="第一条", session_id="s1")
        ledger.record(content="第二条", session_id="s1")
        hits = ledger.search(session_id="s1")
        assert [h["content"] for h in hits] == ["第二条", "第一条"]

    def test_session_isolation(self, ledger):
        ledger.record(content="秘密内容", session_id="s1")
        assert ledger.search("秘密", session_id="s2") == []

    def test_user_isolation_across_instances(self, tmp_path):
        """同一库文件，另一用户实例不可见（强制 WHERE 分区）"""
        db_path = tmp_path / "shared.db"
        ledger_a = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
        ledger_a.record(content="用户甲的记忆", session_id="s1")

        ledger_b = EvictionLedgerDB(db_path=db_path, user_id="u2", agent_id="a1")
        assert ledger_b.search("用户甲", session_id="s1") == []

    def test_persistence_across_instances(self, tmp_path):
        """验收口径：重启（新实例）后 FTS 仍可召回"""
        db_path = tmp_path / "persist.db"
        first = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
        first.record(content="重启前归档的上海天气讨论", session_id="s1")

        second = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
        hits = second.search("上海天气", session_id="s1")
        assert len(hits) == 1


class TestGC:
    def test_gc_by_count(self, ledger):
        for i in range(10):
            ledger.record(content=f"chunk {i}", session_id="s1")
        removed = ledger.gc(keep_count=5)
        assert removed == 5
        assert ledger.count() == 5
        # 保留最新的
        hits = ledger.search(session_id="s1")
        assert "chunk 9" in [h["content"] for h in hits]
        assert "chunk 0" not in [h["content"] for h in hits]

    def test_gc_by_days(self, ledger):
        ledger.record(content="很久之前的", session_id="s1")
        # 手动把 evicted_at 改老
        import sqlite3

        conn = sqlite3.connect(ledger.db_path)
        conn.execute("UPDATE evicted_chunks SET evicted_at = '2020-01-01T00:00:00'")
        conn.commit()
        conn.close()
        removed = ledger.gc(keep_days=30)
        assert removed == 1 and ledger.count() == 0

    def test_gc_never_removes_other_users(self, tmp_path):
        db_path = tmp_path / "shared.db"
        a = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
        a.record(content="甲的", session_id="s1")
        b = EvictionLedgerDB(db_path=db_path, user_id="u2", agent_id="a1")
        b.record(content="乙的", session_id="s1")
        b.gc(keep_count=1)
        assert a.count() == 1  # 甲的记录不受乙的 GC 影响


class TestRobustness:
    def test_fts_syntax_error_safe(self, ledger):
        """FTS5 MATCH 语法字符不崩溃（安全降级为子串匹配）"""
        ledger.record(content="包含 (括号) 与 OR 的内容", session_id="s1")
        hits = ledger.search('"OR" (括号', session_id="s1")
        assert isinstance(hits, list)

    def test_wal_mode_active(self, ledger):
        import sqlite3

        conn = sqlite3.connect(ledger.db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
