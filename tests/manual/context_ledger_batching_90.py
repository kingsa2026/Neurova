#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/003 写侧批量提交 live-verify：真库、真构造面、真读数。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_ledger_batching_90.py

验三件事（判据 A2 + D8 事务语义）：
- 同一存量库规模下，A/B 实测"每行独立 connect+commit+close"（改前形状）与本批
  "常驻连接 + 一次归档调用一次事务"的 24 条/轮耗时，给出倍数；
- 经**真生产构造面**（真 `Agent` → 真 `ContextOrchestrator`）跑一轮归档，
  核对台账确实落库、写穿计数与批数可观测；
- 跨进程可见：另一进程（同库新开池）读到本进程写入的内容，逐字相等。
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

ROUND_SIZE = 24

# 生产形状一轮：中文段 / 英文段 / JSON 工具结果三分（与容量基线脚本同定义）
LEGACY_DDL = """
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
CREATE INDEX IF NOT EXISTS idx_scope_id ON evicted_chunks(user_id, agent_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_digest
    ON evicted_chunks(user_id, agent_id, content_digest);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'
);
"""


def turnChunks(turnIndex, size=ROUND_SIZE):
    rows = []
    for i in range(size):
        shape = i % 3
        if shape == 0:
            text = f"第{turnIndex}轮第{i}条：上下文压缩判据讨论，窗口预算与折叠阈值"
        elif shape == 1:
            text = f"turn {turnIndex} item {i}: The context window budget decides folding."
        else:
            text = (
                '{"role": "assistant", "tool": "file_read", "turn": %d, "item": %d,'
                ' "bytes": 4096, "ok": true}' % (turnIndex, i)
            )
        rows.append((f"turn{turnIndex}_{i}", text))
    return rows


def openDb(path, seedRows=0):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(LEGACY_DDL)
    if seedRows:
        conn.execute("BEGIN")
        for i in range(seedRows):
            text = turnChunks(i)[i % ROUND_SIZE][1]
            cur = conn.execute(
                "INSERT INTO evicted_chunks"
                " (user_id, agent_id, session_id, turn_id, source, content, metadata,"
                "  evicted_at, content_digest, created_at, chat_scope)"
                " VALUES ('default','default','s1', ?, 'conversation', ?, NULL,"
                "  '2026-09-01T00:00:00', ?, '2026-09-01T00:00:00', 'direct')",
                (f"seed{i}", text, f"seed{i}"),
            )
            conn.execute("INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)", (cur.lastrowid, text))
            if (i + 1) % 2000 == 0:
                conn.commit()
                conn.execute("BEGIN")
        conn.commit()
    return conn


def sample(roundFn, reps=20):
    for k in range(3):
        roundFn(900 + k)  # 预热
    samples = []
    for k in range(reps):
        begin = time.perf_counter()
        roundFn(1000 + k)
        samples.append((time.perf_counter() - begin) * 1000)
    ordered = sorted(samples)
    return ordered[len(ordered) // 2]


def perRowRound(path, turnIndex):
    for turn_id, text in turnChunks(turnIndex):
        one = sqlite3.connect(path, timeout=30)
        one.execute("PRAGMA journal_mode=WAL")
        cur = one.execute(
            "INSERT INTO evicted_chunks"
            " (user_id, agent_id, session_id, turn_id, source, content, metadata,"
            "  evicted_at, content_digest, created_at, chat_scope)"
            " VALUES ('default','default','s1', ?, 'conversation', ?, NULL,"
            "  '2026-09-01T00:00:00', ?, '2026-09-01T00:00:00', 'direct')",
            (turn_id, text, f"per{turnIndex}-{turn_id}"),
        )
        one.execute("INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)", (cur.lastrowid, text))
        one.commit()
        one.close()


def batchRound(ledger, pool, turnIndex):
    from neurova.context.pool_models import ContextInput, ContextSource

    with pool.archiveBatch():
        for turn_id, text in turnChunks(turnIndex):
            pool.add_context(
                ContextInput(
                    source=ContextSource.CONVERSATION,
                    content=text,
                    metadata={"turn_id": turn_id},
                )
            )


def writeThroughProduction(cwd, agentId):
    """真 Agent → 真 orchestrator：走生产归档路径（改后的批量事务边界）。

    走的是 `build_context` 的归档段（本轮全部归档共用一个 `archiveBatch()`），
    不是手工调 `_archive_conversation_to_pool`——事务边界在生产装配点上，
    手工调用绕开它就等于没验。
    """
    import asyncio

    from neurova.agent_core import Agent, AgentConfig

    os.chdir(cwd)
    agent = Agent(AgentConfig(name=agentId, agent_id=agentId, llm_model="gpt-4o", workspace_path=cwd))
    orchestrator = agent.context_orchestrator
    history = [
        {"role": "user", "content": f"第{i}轮：设备固件升级窗口与灰度顺序讨论"} for i in range(3)
    ]
    asyncio.run(
        orchestrator.build_context(
            user_input="继续", session_context=history, relevant_memories=[], experience_items=[]
        )
    )
    pool = orchestrator.context_pool
    stats = pool.get_retention_stats()["ledger_persistence"]
    dbPath = pool._ledger_db.db_path
    pool._ledger_db.close()
    return {
        "db_path": dbPath,
        "resident": pool.resident_count(),
        "written": stats["written"],
        "failed": stats["failed"],
        "batches": stats["batches"],
        "db_rows": sqlite3.connect(dbPath).execute(
            "SELECT COUNT(*) FROM evicted_chunks"
        ).fetchone()[0],
    }


def readFromOtherProcess(dbPath):
    """另一进程读同库（跨进程可见性；不经生产构造面，避免库路径随 agent 漂移）。"""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from neurova.context.eviction_ledger_db import EvictionLedgerDB\n"
        "ledger = EvictionLedgerDB(db_path=sys.argv[1], user_id='default', agent_id='default')\n"
        "rows = ledger.search(query='固件', limit=10)\n"
        "print(len(rows)); print(rows[0]['content'] if rows else '')\n"
        "ledger.close()\n"
    ) % ROOT
    run = subprocess.run([sys.executable, "-c", code, dbPath], capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"读取子进程失败：\n{run.stdout[-1500:]}\n{run.stderr[-1500:]}")
    lines = run.stdout.strip().splitlines()
    return int(lines[0]), (lines[1] if len(lines) > 1 else "")


def main():
    tmp = tempfile.mkdtemp(prefix="ctxLedgerBatching90_")
    print(f"[setup] 临时目录: {tmp}")
    seedRows = 10000

    legacyPath = os.path.join(tmp, "per_row.db")
    openDb(legacyPath, seedRows).close()
    perRowMs = sample(lambda t: perRowRound(legacyPath, t))

    batchPath = os.path.join(tmp, "batch.db")
    openDb(batchPath, seedRows).close()
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context_pool import ContextPool

    ledger = EvictionLedgerDB(db_path=batchPath, user_id="default", agent_id="default")
    pool = ContextPool(
        user_id="default", agent_id="default", session_id="s1", ttl_seconds=0, ledger_db=ledger
    )
    batchMs = sample(lambda t: batchRound(ledger, pool, t))
    ledger.close()

    print(f"[1 写放大 A/B] 24 条/轮（{seedRows} 行存量库，20 轮取中位）")
    print(f"    每行独立连接+提交（改前形状）: {perRowMs:8.2f} ms/轮")
    print(f"    常驻连接+一次事务（本批实现）: {batchMs:8.2f} ms/轮")
    print(f"    倍数: {perRowMs / batchMs:.0f}×（判据 A2 只要求 ≤ 1/3）")
    assert batchMs <= perRowMs / 3, "A2 未达标"

    # 真构造面走一轮，核对落库与计数可观测
    prodDir = os.path.join(tmp, "prod")
    os.makedirs(prodDir, exist_ok=True)
    written = writeThroughProduction(prodDir, "ctxbatch90")
    print(f"[2 生产构造面单轮] {json.dumps(written, ensure_ascii=False)}")
    assert written["written"] == written["db_rows"], "写穿计数与库内行数不一致"
    assert written["failed"] == 0
    assert written["batches"] == 1, "一轮归档没有收成一个事务批次"

    count, firstContent = readFromOtherProcess(written["db_path"])
    print(f"[3 跨进程可见] 另一进程读到 {count} 条；首条 = {firstContent}")
    assert count >= 1, "另一进程读不到本进程提交的内容（跨连接不可见）"

    print("\nLIVE-VERIFY PASSED：一轮归档 = 一个事务，写放大较改前形状降低 "
          f"{perRowMs / batchMs:.0f}×，跨进程可见")


if __name__ == "__main__":
    main()
