#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/006 v2 迁移 live-verify：真 v1 库、真生产构造面、真并发写下迁移。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_ledger_fts_rebuild_90.py

验四件事（判据 A7 + A6 + A3 索引面）：
- 真 v1 库（`unicode61`）经**真生产构造面**（真 `Agent` → `EvictionLedgerDB`）
  打开即迁到 v2，FTS 分词器变 trigram，行数不丢；
- 迁移窗口内**并发写不停**：另起写线程持续归档，记录停等 p50/p95/max；
- 迁移后中文查询命中集合 == LIKE 真值（004 的查询侧判据在真库上复核）；
- 幂等：重跑 `migrate()` 返回空；半成品影子表可重入补齐。
"""
import json
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

random.seed(90)
CJK = "上下文 压缩 池 归档 检索 注入 记忆 经验 反思 工具 结果 窗口 预算".split()
SEED_ROWS = 20000


def buildV1Db(dbPath, rows=SEED_ROWS):
    """真 v1 库：002 的 v1 结构 + `unicode61` 的 FTS（改前状态）。"""
    conn = sqlite3.connect(dbPath, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
CREATE TABLE IF NOT EXISTS evicted_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
    session_id TEXT, turn_id TEXT, source TEXT, content TEXT NOT NULL, metadata TEXT,
    evicted_at TEXT NOT NULL, content_digest TEXT, created_at TEXT, chat_scope TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content, tokenize='unicode61 remove_diacritics 2');
CREATE UNIQUE INDEX IF NOT EXISTS uniq_digest
    ON evicted_chunks(user_id, agent_id, content_digest);
CREATE INDEX IF NOT EXISTS idx_scope_id ON evicted_chunks(user_id, agent_id, id);
"""
    )
    conn.execute("BEGIN")
    for index in range(rows):
        text = "".join(random.choice(CJK) for _ in range(60))
        cur = conn.execute(
            "INSERT INTO evicted_chunks"
            " (user_id, agent_id, session_id, turn_id, source, content, evicted_at,"
            "  content_digest, created_at, chat_scope)"
            " VALUES ('u1','a1','s1',?,'conversation',?, '2026-09-01T00:00:00', ?,"
            " '2026-09-01T00:00:00','direct')",
            (f"t{index}", text, f"d{index}"),
        )
        conn.execute(
            "INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)", (cur.lastrowid, text)
        )
        if (index + 1) % 2000 == 0:
            conn.execute("COMMIT")
            conn.execute("BEGIN")
    conn.execute("COMMIT")
    conn.execute("PRAGMA user_version = 1")
    conn.close()


def ftsSql(dbPath):
    conn = sqlite3.connect(dbPath)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'evicted_fts'"
        ).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def scalar(dbPath, sql):
    conn = sqlite3.connect(dbPath)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def main():
    tmp = tempfile.mkdtemp(prefix="ctxLedgerFts90_")
    dbPath = os.path.join(tmp, "v1.db")
    print(f"[setup] 临时目录: {tmp}")

    buildV1Db(dbPath)
    print("[0 v1 前像] " + json.dumps(
        {"rows": scalar(dbPath, "SELECT COUNT(*) FROM evicted_chunks"),
         "user_version": scalar(dbPath, "PRAGMA user_version"),
         "tokenize": "trigram" if "trigram" in ftsSql(dbPath) else "unicode61"},
        ensure_ascii=False,
    ))

    # ── 1. 迁移窗口内并发写（真写线程 + 停等分布）
    stalls = []
    stop = threading.Event()

    def writer():
        # 并发写按**生产写入契约**落两侧：内容表 + FTS 影子表（与
        # `EvictionLedgerDB._insert` 同形）。不用 `record()` 是因为它的构造期会
        # 自己跑一次 v2 迁移，与主迁移互相抢锁——那测的是"两个迁移互斥"，
        # 不是"迁移窗口内生产写是否被阻塞"。
        conn = sqlite3.connect(dbPath, timeout=30, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        counter = 0
        while not stop.is_set():
            started = time.perf_counter()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "INSERT INTO evicted_chunks"
                    " (user_id, agent_id, session_id, turn_id, source, content, evicted_at)"
                    " VALUES ('w','a','s1',?,'conversation',?, '2026-09-02T00:00:00')",
                    (f"tw{counter}", f"并发写入的上下文压缩内容 第{counter}条"),
                )
                conn.execute(
                    "INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)",
                    (cur.lastrowid, f"并发写入的上下文压缩内容 第{counter}条"),
                )
                conn.execute("COMMIT")
                stalls.append((time.perf_counter() - started) * 1000)
            except Exception:
                stalls.append(-1)
            counter += 1
            time.sleep(0.002)
        conn.close()

    thread = threading.Thread(target=writer)
    thread.start()
    time.sleep(0.1)

    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    started = time.perf_counter()
    ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
    migrateMs = (time.perf_counter() - started) * 1000
    stop.set()
    thread.join()
    stalls = sorted(s for s in stalls if s >= 0)
    ledger.close()

    print("[1 迁移窗口并发写] " + json.dumps(
        {"migrate_ms": round(migrateMs, 1), "concurrent_writes": len(stalls),
         "p50_ms": round(stalls[len(stalls) // 2], 1) if stalls else None,
         "p95_ms": round(stalls[int(len(stalls) * 0.95)], 1) if stalls else None,
         "max_ms": round(stalls[-1], 1) if stalls else None},
        ensure_ascii=False,
    ))
    assert stalls, "迁移窗口内并发写一次都没成功（服务被整段阻塞）"

    # ── 2. 迁移结果读数
    tokenize = "trigram" if "trigram" in ftsSql(dbPath) else "unicode61"
    contentRows = scalar(dbPath, "SELECT COUNT(*) FROM evicted_chunks")
    ftsRows = scalar(dbPath, "SELECT COUNT(*) FROM evicted_fts")
    print("[2 v2 结果] " + json.dumps(
        {"user_version": scalar(dbPath, "PRAGMA user_version"), "tokenize": tokenize,
         "content_rows": contentRows, "fts_rows": ftsRows,
         "shadow_table_left": bool(scalar(
             dbPath, "SELECT COUNT(*) FROM sqlite_master WHERE name='evicted_fts_v2'"))},
        ensure_ascii=False,
    ))
    assert tokenize == "trigram", "迁移后 FTS 仍是 unicode61"
    assert ftsRows == contentRows, f"两表行数脱节：FTS {ftsRows} / 内容 {contentRows}"

    # ── 3. 迁移后中文查询命中对拍（004 的查询侧判据在真库上复核）
    ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
    # 造少量**可辨识**的中文行：随机 CJK 语料里"上下文压缩"命中上千条，
    # 会被候选集上限接管——那样比的是截断口径，不是预筛正确性（判据 A3 要求集合相等）。
    ledger.beginBatch()
    for index in range(3):
        ledger.record(
            content=f"可辨识标记 ZEPHYR{index}：上下文压缩判据与窗口预算的实测记录",
            turn_id=f"mark{index}", session_id="s1",
        )
    ledger.commitBatch()
    checks = {}
    for query in ("ZEPHYR1", "可辨识标记 ZEPHYR2"):
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # 两侧都按**同一序**取同一批（`id DESC`）：召回序就是它，
        # 而"命中集合相等"必须在同一条截断口径下比——否则比的是截断方式，
        # 不是预筛的正确性（改前实测正是拿 `LIMIT` 无序的 LIKE 结果当对照）。
        truth = sorted(
            row["content"]
            for row in ledger._requireConn().execute(
                "SELECT content FROM evicted_chunks"
                " WHERE user_id='u1' AND agent_id='a1' AND content LIKE ? ESCAPE '\\'"
                " ORDER BY id DESC LIMIT 200",
                (f"%{escaped}%",),
            ).fetchall()
        )
        hits = sorted(row["content"] for row in ledger.search(query, limit=200))
        if len(hits) >= 200 or len(truth) >= 200:
            raise AssertionError(
                f"查询 {query!r} 命中超过 200 条：对拍口径被候选集上限接管，"
                "本步无法比较集合（请改用命中稀疏的查询）"
            )
        checks[query] = {"hits": len(hits), "truth": len(truth), "equal": hits == truth}
        assert hits, f"迁移后中文查询 {query!r} 命中为零（trigram 未生效）"
        assert hits == truth, f"查询 {query!r} 命中集合 != LIKE 真值"
    print("[3 中文命中对拍] " + json.dumps(checks, ensure_ascii=False))

    # ── 4. 幂等 + 重入
    conn = sqlite3.connect(dbPath)
    from neurova.core.db_migration import migrate

    applied = migrate(conn, "context_ledger")
    conn.close()
    print("[4 幂等] " + json.dumps({"reapplied": applied}, ensure_ascii=False))
    assert applied == [], "重跑迁移仍有待应用版本"
    ledger.close()
    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    main()
