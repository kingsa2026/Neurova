# -*- coding: utf-8 -*-
"""B4-006 v2 迁移：FTS 重建为 trigram（零停机，判据 A7 + A3 索引面）。

红灯依据（改前实证，基线脚本 §4/§6/§7）：

- `evicted_fts` 的分词器是 `unicode61`，**对中文等于没有索引**：查询 `上下文压缩` /
  `窗口预算` / `上下文` 命中 **0**（LIKE 真值 4934 / 4921 / 16526）；
- 只改 `tokenize` 参数**不会改已有索引**，必须重建表；
- `delete-all` 对本表非法（普通 FTS5，实测 `OperationalError`）；
- 一次性 `INSERT … SELECT` 长事务会把并发写整段阻塞（实测 0.84 s 全程持写锁）。

契约（修复后）：

- v2 = 影子表（trigram）+ **分批短事务**回填 + 同事务内 `DROP` 旧表 + `RENAME` 影子表；
  版本推进到 2；失败回滚并上抛（沿用 `db_migration` 语义）；
- 迁移**逐批独立事务**（结构性判据：批数 = ⌈行数/批大小⌉ + 1，不是"一条长事务"）；
- 幂等：v2 库重跑 `migrate()` 返回空；中途失败可重入（影子表残留不影响重跑）；
- 迁移后中文查询的 MATCH 命中集合 == LIKE 真值（004 定的查询侧判据不变）。

前像纪律：v1 的 DDL（含 `unicode61`）是**已发布版本**，其 SQL 文本永不改写；
本文件用它的前像构造真实 v1 库。
"""

import sqlite3

import pytest

from neurova.context import eviction_ledger_db as ledgerModule
from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.core.db_migration import migrate

LEDGER_DOMAIN = "context_ledger"
FTS_TABLE = "evicted_fts"

CORPUS = [
    "上下文压缩窗口预算的实测数据：折叠阈值为 36%",
    "上下文池归档与召回路径的隔离闸口讨论",
    "窗口预算与折叠阈值：中文查询在 unicode61 下命中为零",
    "The context window budget decides whether folding triggers.",
    "带下划线 a_b 与百分号 100% 的库内文本",
]


def _ftsSql(path, table=FTS_TABLE):
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _userVersion(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _legacyV1Db(path, contents):
    """构造真实 v1 库：002 的 v1 结构（含 unicode61 的 FTS）。"""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
CREATE TABLE IF NOT EXISTS evicted_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    turn_id TEXT,
    source TEXT,
    content TEXT NOT NULL,
    metadata TEXT,
    evicted_at TEXT NOT NULL,
    content_digest TEXT,
    created_at TEXT,
    chat_scope TEXT
);
CREATE INDEX IF NOT EXISTS idx_evicted_user ON evicted_chunks(user_id, agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_digest
    ON evicted_chunks(user_id, agent_id, content_digest);
CREATE INDEX IF NOT EXISTS idx_scope_id ON evicted_chunks(user_id, agent_id, id);
"""
    )
    import hashlib

    for index, text in enumerate(contents):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cur = conn.execute(
            "INSERT INTO evicted_chunks"
            " (user_id, agent_id, session_id, turn_id, source, content, metadata,"
            "  evicted_at, content_digest, created_at, chat_scope)"
            " VALUES ('u1','a1','s1',?,?,?,NULL,'2026-09-01T00:00:00',?,"
            " '2026-09-01T00:00:00','direct')",
            (f"t{index}", "conversation", text, digest),
        )
        conn.execute(
            "INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)", (cur.lastrowid, text)
        )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def _likeTruth(ledger, query):
    """LIKE 真值（带 ESCAPE），判据的对照面。"""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = ledger._requireConn().execute(
        "SELECT content FROM evicted_chunks"
        " WHERE user_id = ? AND agent_id = ? AND content LIKE ? ESCAPE '\\'",
        (ledger.user_id, ledger.agent_id, f"%{escaped}%"),
    ).fetchall()
    return sorted(row["content"] for row in rows)


class TestV2RebuildsTokenizer:
    """A3 索引面：迁移后中文查询真的查得到（unicode61 → trigram）。"""

    def test_tokenizerIsTrigramAfterMigration(self, tmp_path):
        path = tmp_path / "v2.db"
        _legacyV1Db(path, CORPUS)
        assert "unicode61" in _ftsSql(path), "前像库不是 unicode61（本用例前提）"

        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

        assert _userVersion(path) == 2
        assert "trigram" in _ftsSql(path), "v2 之后 FTS 仍是 unicode61"
        assert _ftsSql(path, "evicted_fts_v2") is None, "影子表未清理（迁移留了半成品）"

    def test_chineseQueriesMatchLikeTruthAfterMigration(self, tmp_path):
        path = tmp_path / "cjk.db"
        _legacyV1Db(path, CORPUS)
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        try:
            for query in ("上下文压缩", "窗口预算", "上下文池"):
                hits = sorted(row["content"] for row in ledger.search(query, limit=50))
                assert hits == _likeTruth(ledger, query), (
                    f"迁移后查询 {query!r} 的 MATCH 命中集合 != LIKE 真值"
                    "（trigram 未生效或回填不全）"
                )
                assert hits, f"中文查询 {query!r} 命中为零（unicode61 的老毛病没被修掉）"
        finally:
            ledger.close()

    def test_englishQueryDoesNotRegress(self, tmp_path):
        path = tmp_path / "en.db"
        _legacyV1Db(path, CORPUS)
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        try:
            hits = sorted(row["content"] for row in ledger.search("context window", limit=50))
            assert hits == _likeTruth(ledger, "context window")
        finally:
            ledger.close()

    def test_allRowsAreIndexed(self, tmp_path):
        """回填不得漏行：FTS 行数 == 内容表行数。"""
        path = tmp_path / "count.db"
        _legacyV1Db(path, CORPUS)
        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        try:
            content_rows = ledger._requireConn().execute(
                "SELECT COUNT(*) AS c FROM evicted_chunks"
            ).fetchone()["c"]
            fts_rows = ledger._requireConn().execute(
                "SELECT COUNT(*) AS c FROM evicted_fts"
            ).fetchone()["c"]
            assert fts_rows == content_rows, f"两表行数脱节：FTS {fts_rows} / 内容 {content_rows}"
        finally:
            ledger.close()


class TestV2IsBatchedNotOneLongTransaction:
    """A7 的结构面：迁移**逐批短事务**，不是一条长事务持锁到底。

    这条判据与机器速度无关：一次迁移要么"1 个事务装完全部行"，要么
    "⌈行数/批大小⌉ 个事务"——步骤集合的性质，不随负载摆动。倍数/停等读数
    （真并发写）另存 live-verify 脚本，两者互为表里。
    """

    def _batchTrace(self, path, rowsPerBatch=3, total=12):
        """跑一次迁移并记录每条语句；返回 (提交次数, 每批插入行数上界)。"""
        contents = [f"第{i}条：上下文压缩与窗口预算的讨论" for i in range(total)]
        _legacyV1Db(path, contents)

        statements = []
        realConnect = ledgerModule.sqlite3.connect

        def countingConnect(*args, **kwargs):
            conn = realConnect(*args, **kwargs)

            def onStatement(sql):
                statements.append(sql)

            conn.set_trace_callback(onStatement)
            return conn

        originalBatch = ledgerModule._FTS_REBUILD_BATCH
        ledgerModule.sqlite3.connect = countingConnect
        ledgerModule._FTS_REBUILD_BATCH = rowsPerBatch
        try:
            EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        finally:
            ledgerModule.sqlite3.connect = realConnect
            ledgerModule._FTS_REBUILD_BATCH = originalBatch

        commits = [s for s in statements if s.strip().upper() == "COMMIT"]
        return commits

    def test_rebuildCommitsPerBatch(self, tmp_path):
        commits = self._batchTrace(tmp_path / "batch.db", rowsPerBatch=3, total=12)
        assert len(commits) >= 4, (
            f"迁移只提交了 {len(commits)} 次——12 行按每批 3 行回填应有 ≥4 次"
            "（一次长事务会把并发写整段阻塞）"
        )

    def test_eachBatchReadIsBounded(self, tmp_path):
        """每一批回填的**读取**都必须带上限（`LIMIT`），不得一次拉全表。"""
        path = tmp_path / "bounded.db"
        statements = []
        realConnect = ledgerModule.sqlite3.connect

        def countingConnect(*args, **kwargs):
            conn = realConnect(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        contents = [f"第{i}条：上下文压缩与窗口预算的讨论" for i in range(12)]
        _legacyV1Db(path, contents)
        originalBatch = ledgerModule._FTS_REBUILD_BATCH
        ledgerModule.sqlite3.connect = countingConnect
        ledgerModule._FTS_REBUILD_BATCH = 3
        try:
            EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        finally:
            ledgerModule.sqlite3.connect = realConnect
            ledgerModule._FTS_REBUILD_BATCH = originalBatch

        reads = [
            stmt for stmt in statements
            if stmt.strip().upper().startswith("SELECT") and "evicted_chunks" in stmt
        ]
        assert reads, "迁移没有分批读取语句（找不到回填来源查询）"
        for stmt in reads:
            assert "LIMIT" in stmt.upper(), f"回填读取没有上限（一次拉全表）：{stmt[:140]}"

    def test_batchSizeIsDeclared(self):
        assert getattr(ledgerModule, "_FTS_REBUILD_BATCH", None) == 5000, (
            "重建批大小没有单一事实源（规格 D12 定值 5000/批）"
        )


class TestV2IdempotenceAndFailure:
    """A6 面：v2 幂等、可重入、失败不谎报。"""

    def test_migrationIsIdempotent(self, tmp_path):
        path = tmp_path / "idem.db"
        _legacyV1Db(path, CORPUS)
        EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")

        conn = sqlite3.connect(path)
        try:
            assert migrate(conn, LEDGER_DOMAIN) == [], "重跑迁移仍有待应用版本（非幂等）"
        finally:
            conn.close()

    def test_halfBuiltShadowTableIsReentrant(self, tmp_path):
        """中途失败（影子表残留、版本未推进）后重跑必须收敛到 v2。"""
        path = tmp_path / "reentrant.db"
        _legacyV1Db(path, CORPUS)
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts_v2 USING fts5(content, tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO evicted_fts_v2(rowid, content)"
            " SELECT id, content FROM evicted_chunks WHERE id <= 2"
        )
        conn.commit()
        conn.close()
        assert _userVersion(path) == 1

        ledger = EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")
        try:
            assert _userVersion(path) == 2
            assert "trigram" in _ftsSql(path)
            fts_rows = ledger._requireConn().execute(
                "SELECT COUNT(*) AS c FROM evicted_fts"
            ).fetchone()["c"]
            assert fts_rows == len(CORPUS), "重入后回填不全（半成品影子表把行数算丢了）"
        finally:
            ledger.close()

    def test_downgradeRejected(self, tmp_path):
        from neurova.core.db_migration import SchemaVersionError

        path = tmp_path / "high.db"
        _legacyV1Db(path, CORPUS)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version = 9")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError):
            EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
