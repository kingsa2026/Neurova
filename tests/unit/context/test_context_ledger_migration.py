# -*- coding: utf-8 -*-
"""B4-002 版本域与 v1 迁移（判据 A6）+ U1 读侧兼容兜底。

红灯依据（改前实证）：

- `eviction_ledger_db.py` 只有 `CREATE TABLE IF NOT EXISTS`，**没有 `user_version`**，
  `context_ledger` 域从未注册 —— `migrate(conn, "context_ledger")` 直接 `ValueError`；
- 表无 `content_digest` / `created_at` / `chat_scope` 列，无 `uniq_digest` /
  `idx_scope_id` 索引 —— 每库无版本纪律，后续每次改 schema 都是裸改；
- 读侧只取 `metadata` 字符串、不解析，`chat_scope` 读不回来 —— 工单 008 的
  作用域闸口即使放行也无据可判。

契约（修复后，规格 D12 + §8 定案）：

- `context_ledger` 版本域注册进既有 `core/db_migration`（不新建平行体系）；
- v1 = 三个新列 + `content_digest` 回填 + `uniq_digest(user, agent, digest)`
  + `idx_scope_id(user, agent, id)`；`created_at` / `chat_scope` 对旧行留 NULL，
  由读侧兼容兜底（U1 甲案的配套）；
- 旧行 `content_digest` 回填后在 `(user, agent)` 域内唯一：历史同内容重复行
  在迁移中合并（`logger` 点名条数，不静默删）；
- 迁移幂等；库版本高于代码已知版本 → `SchemaVersionError`（沿用 `db_migration` 防护）；
- 旧代码打开新库可写可读自己的行（规格 D12「允许回滚」，不做硬拦）。

前像纪律：`_LEGACY_FRONT_IMAGE` 是 002 实施前 `_SCHEMA` 的**冻结前像**，
用来构造真实的 v0 库。schema 演进后**不得**同步修改它（否则迁移测试失去意义）。
"""

import sqlite3

import pytest

from neurova.context import eviction_ledger_db as ledgerModule
from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool
from neurova.core.db_migration import SchemaVersionError, migrate, registered_domains

LEDGER_DOMAIN = "context_ledger"

# v0（002 实施前）的库前像：无 user_version、无新列、无新索引
_LEGACY_FRONT_IMAGE = """
CREATE TABLE IF NOT EXISTS evicted_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    turn_id TEXT,
    source TEXT,
    content TEXT NOT NULL,
    metadata TEXT,
    evicted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evicted_user ON evicted_chunks(user_id, agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'
);
"""


def _legacyDb(path, rows):
    """构造真实 v0 库：旧 DDL + 旧写入形状（无 digest / created_at / chat_scope）。"""
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_FRONT_IMAGE)
    for row in rows:
        cur = conn.execute(
            "INSERT INTO evicted_chunks"
            " (user_id, agent_id, session_id, turn_id, source, content, metadata, evicted_at)"
            " VALUES (:user_id, :agent_id, :session_id, :turn_id, :source, :content, :metadata, :evicted_at)",
            row,
        )
        conn.execute(
            "INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)", (cur.lastrowid, row["content"])
        )
    conn.commit()
    conn.close()


def _columns(path):
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(evicted_chunks)")}
    finally:
        conn.close()


def _indexes(path):
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute("PRAGMA index_list(evicted_chunks)")}
    finally:
        conn.close()


def _userVersion(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _rows(path, sql="SELECT * FROM evicted_chunks ORDER BY id"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class TestVersionDomain:
    """A6 前半：版本域注册 + 迁移幂等 + 防降级。"""

    def test_domain_registered_at_import(self):
        assert LEDGER_DOMAIN in registered_domains(), (
            "context_ledger 域未注册——建库仍走裸 CREATE TABLE IF NOT EXISTS，"
            "与 AGENTS.md §3 的 schema 版本纪律直接冲突"
        )

    def test_fresh_ledger_lands_at_v1(self, tmp_path):
        path = tmp_path / "fresh.db"
        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        assert _userVersion(path) == 1, "新建库没有版本号（无 user_version 纪律）"
        assert {"content_digest", "created_at", "chat_scope"} <= _columns(path)
        assert {"uniq_digest", "idx_scope_id"} <= _indexes(path)

    def test_migration_is_idempotent(self, tmp_path):
        path = tmp_path / "idem.db"
        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        conn = sqlite3.connect(path)
        try:
            assert migrate(conn, LEDGER_DOMAIN) == [], "重跑迁移仍有待应用版本（非幂等）"
        finally:
            conn.close()

    def test_downgrade_rejected(self, tmp_path):
        path = tmp_path / "high.db"
        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version = 9")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError):
            EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

    def test_unknown_domain_raises_not_silent(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "x.db")
        try:
            with pytest.raises(ValueError):
                migrate(conn, "context_ledger_typo")
        finally:
            conn.close()


class TestV1Migration:
    """A6 后半：v0 库迁到 v1，列/索引/回填齐备，旧代码仍可写读。"""

    _LEGACY_ROWS = [
        {
            "user_id": "u1", "agent_id": "a1", "session_id": "project_roomB", "turn_id": "t1",
            "source": "conversation", "content": "群聊归档：下季度发布计划",
            "metadata": '{"chat_scope": "room:project_roomB"}', "evicted_at": "2026-09-01T00:00:00",
        },
        {
            "user_id": "u1", "agent_id": "a1", "session_id": "s_direct", "turn_id": "t2",
            "source": "conversation", "content": "单聊归档：固件升级窗口",
            "metadata": '{"chat_scope": "direct"}', "evicted_at": "2026-09-01T00:00:01",
        },
        {
            "user_id": "u1", "agent_id": "a1", "session_id": "s_direct", "turn_id": "t3",
            "source": "conversation", "content": "无作用域元数据的旧行",
            "metadata": None, "evicted_at": "2026-09-01T00:00:02",
        },
    ]

    def test_legacy_db_migrates_to_v1(self, tmp_path):
        path = tmp_path / "legacy.db"
        _legacyDb(path, self._LEGACY_ROWS)
        assert _userVersion(path) == 0, "前像库不该带版本号（本用例的前提）"

        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

        assert _userVersion(path) == 1
        assert {"content_digest", "created_at", "chat_scope"} <= _columns(path)
        assert {"uniq_digest", "idx_scope_id"} <= _indexes(path)

    def test_legacy_rows_get_content_digest(self, tmp_path):
        path = tmp_path / "backfill.db"
        _legacyDb(path, self._LEGACY_ROWS)
        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

        rows = _rows(path)
        assert len(rows) == len(self._LEGACY_ROWS)
        digests = [r["content_digest"] for r in rows]
        assert all(d for d in digests), "旧行 content_digest 未回填（唯一索引形同虚设）"
        # 同内容同摘要、异内容异摘要（判据不依赖具体算法形状）
        assert len(set(digests)) == len(set(r["content"] for r in rows))

    def test_legacy_duplicate_rows_are_merged(self, tmp_path):
        """历史同内容重复行必须在建唯一索引前合并（否则迁移直接失败）。"""
        path = tmp_path / "dupes.db"
        duplicate = dict(self._LEGACY_ROWS[0])
        _legacyDb(path, [self._LEGACY_ROWS[0], duplicate, self._LEGACY_ROWS[1]])

        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

        contents = [r["content"] for r in _rows(path)]
        assert len(contents) == 2, f"同内容重复行未合并：{contents}"
        assert contents.count(duplicate["content"]) == 1
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM evicted_fts").fetchone()[0] == 2, (
                "合并后 FTS 残留孤儿行（两表行数脱节）"
            )
        finally:
            conn.close()

    def test_old_code_can_still_write_and_read(self, tmp_path):
        """规格 D12：回滚场景不硬拦——旧写入形状（无新列）仍可写可读。"""
        path = tmp_path / "rollback.db"
        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "INSERT INTO evicted_chunks"
                " (user_id, agent_id, session_id, turn_id, source, content, metadata, evicted_at)"
                " VALUES ('u1', 'a1', 's1', 't9', 'conversation', '旧代码写入的行', NULL,"
                " '2026-09-02T00:00:00')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT content, content_digest FROM evicted_chunks WHERE turn_id = 't9'"
            ).fetchone()
            assert row[0] == "旧代码写入的行"
            assert row[1] is None
        finally:
            conn.close()

    def test_legacy_null_digest_row_does_not_duplicate_recall(self, tmp_path):
        """旧代码持续写 NULL digest 的混合态：召回侧仍不得给出两份同内容。

        回滚场景（规格 D12「允许回滚」）下旧代码写的新行不带 digest，唯一索引对
        NULL 不冲突——同内容可能落两行。此时由**读侧按内容指纹去重**兜住
        「同内容只出一条」的对外契约（不阻断旧代码写入，也不谎称已按列去重）。
        """
        db_path = tmp_path / "mixed.db"
        _legacyDb(db_path, [{
            "user_id": "u1", "agent_id": "a1", "session_id": "s1", "turn_id": "t1",
            "source": "conversation", "content": "混合态：旧代码写入的同一份内容",
            "metadata": None, "evicted_at": "2026-09-01T00:00:00",
        }])
        ledger = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
        ledger.record(content="混合态：旧代码写入的同一份内容", session_id="s1")

        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0, ledger_db=ledger
        )
        recalled = pool.recall_evicted(query="混合态", limit=10)
        assert len(recalled) == 1, f"同内容召回出两条：{[c.content for c in recalled]}"

    def test_unique_digest_holds_within_scope(self, tmp_path):
        path = tmp_path / "uniq.db"
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        ledger.record(content="同一份内容", session_id="s1")
        ledger.record(content="同一份内容", session_id="s2")
        assert ledger.count() == 1, "同内容在 (user, agent) 域内出现两行（去重语义失效）"

        other = EvictionLedgerDB(db_path=path, user_id="u2", agent_id="a1")
        other.record(content="同一份内容", session_id="s1")
        assert other.count() == 1, "跨 user 域被错误去重（隔离失效）"


class TestReadSideFallback:
    """U1 甲案配套：列优先，NULL 行回退解析 metadata，两路同源同结果。"""

    def test_scope_column_and_metadata_fallback_agree(self, tmp_path, monkeypatch):
        path = tmp_path / "scope.db"
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        ledger.record(
            content="带列写入的群聊归档", session_id="project_roomB",
            chat_scope="room:project_roomB",
        )
        ledger.record(
            content="只带 metadata 的旧行", session_id="s_direct",
            metadata={"chat_scope": "room:project_roomB"},
        )

        calls = []
        realResolve = ledgerModule.scope_from_metadata

        def spy(md):
            calls.append(md)
            return realResolve(md)

        monkeypatch.setattr(ledgerModule, "scope_from_metadata", spy)
        scopes = [ledgerModule.resolveArchivedScope(r) for r in ledger.search(limit=10)]

        assert scopes == ["room:project_roomB", "room:project_roomB"], (
            f"列路径与 metadata 兜底路径结果不一致：{scopes}"
        )
        assert len(calls) == 2, "两路没有都经 scope_from_metadata（存在第二份作用域规则）"

    def test_fallback_uses_session_prefix_rule(self, tmp_path):
        path = tmp_path / "prefix.db"
        _legacyDb(path, [{
            "user_id": "u1", "agent_id": "a1", "session_id": "project_roomC", "turn_id": "t1",
            "source": "conversation", "content": "旧行无 metadata",
            "metadata": None, "evicted_at": "2026-09-01T00:00:00",
        }])
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

        row = ledger.search(limit=10)[0]
        assert ledgerModule.resolveArchivedScope(row) == "room:project_roomC", (
            "旧行既无列也无 metadata.chat_scope 时没有按 session_id 的 project_ 前缀回溯"
        )

    def test_created_at_falls_back_to_evicted_at(self, tmp_path):
        path = tmp_path / "created.db"
        _legacyDb(path, [{
            "user_id": "u1", "agent_id": "a1", "session_id": "s1", "turn_id": "t1",
            "source": "conversation", "content": "旧行无 created_at",
            "metadata": None, "evicted_at": "2026-09-01T00:00:00",
        }])
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        ledger.record(content="新行带 created_at", session_id="s1", created_at="2026-09-03T10:00:00")

        byContent = {r["content"]: r for r in ledger.search(limit=10)}
        assert (
            ledgerModule.resolveArchivedCreatedAt(byContent["新行带 created_at"]).isoformat()
            == "2026-09-03T10:00:00"
        )
        assert (
            ledgerModule.resolveArchivedCreatedAt(byContent["旧行无 created_at"]).isoformat()
            == "2026-09-01T00:00:00"
        ), "旧行 created_at 为 NULL 时没有回退到 evicted_at"


class TestRecallExposesArchivedFacts:
    """端到端：归档事实读得回来（列 + 兜底），跨重启成立。"""

    def _pool(self, db_path, **kwargs):
        return ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
            ledger_db=EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1"),
            **kwargs,
        )

    def test_recall_returns_scope_and_created_at(self, tmp_path):
        db_path = tmp_path / "recall.db"
        pool = self._pool(db_path)
        pool.turn_scope = "room:project_roomB"
        pool.add_context(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content="群聊归档：代号 ZEPHYR-9",
                metadata={"turn_id": "turn_0"},
            )
        )
        archivedAt = pool.get_contexts()[0].created_at
        del pool

        recalled = self._pool(db_path).recall_evicted(query="ZEPHYR", limit=10)
        assert len(recalled) == 1
        assert recalled[0].metadata.get("chat_scope") == "room:project_roomB", (
            "召回路径丢掉了归档作用域——工单 008 的闸口无据可判"
        )
        assert recalled[0].created_at == archivedAt, (
            "召回条目用的是构造时刻而非归档时刻（freshness 打分拿到的是假新鲜度）"
        )

    def test_metadata_session_is_not_lost_when_argument_absent(self, tmp_path):
        """未传 `session_id` 时不得把 metadata 里的会话归属抹掉。"""
        path = tmp_path / "md_session.db"
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        ledger.record(content="只带 metadata 的群聊归档", metadata={"session_id": "project_roomE"})

        row = ledger.search(limit=10)[0]
        assert row["chat_scope"] == "room:project_roomE", (
            "row 的 session 归属被空参数覆盖（作用域落到 direct）"
        )

    def test_recall_resolves_legacy_rows_without_column(self, tmp_path):
        """旧行无列：召回条目的作用域经 metadata / session 前缀兜底解出。

        本用例不涉及跨会话召回策略（那是工单 008），行与池同 session。
        """
        db_path = tmp_path / "legacy_recall.db"
        _legacyDb(db_path, [{
            "user_id": "u1", "agent_id": "a1", "session_id": "project_roomD", "turn_id": "t1",
            "source": "conversation", "content": "旧库里的房间归档：代号 ATLAS-3",
            "metadata": '{"chat_scope": "room:project_roomD"}', "evicted_at": "2026-09-01T00:00:00",
        }])

        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="project_roomD", ttl_seconds=0,
            ledger_db=EvictionLedgerDB(
                db_path=db_path, user_id="u1", agent_id="a1"
            ),
        )
        recalled = pool.recall_evicted(query="ATLAS", limit=10)
        assert len(recalled) == 1
        assert recalled[0].metadata.get("chat_scope") == "room:project_roomD"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
