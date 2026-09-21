#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/002 迁移 live-verify：真 v0 库 → 真生产构造面 → v1 迁移后读数。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_ledger_migration_90.py

验四件事（判据 A6 + U1 兜底）：
- 造一个真 v0 库（002 实施前的 DDL + 旧写入形状，含同内容重复行）；
- 经**生产构造面**（真 `Agent` → 真 `ContextOrchestrator` → `EvictionLedgerDB`）打开它，
  走 `db_migration` 的 `context_ledger` 版本域迁移；
- 读数：user_version、列/索引齐备、digest 回填与重复行合并、幂等（重跑返回空）；
- 召回链路：作用域（列 + 旧行 metadata 兜底）与归档时刻都取得到。
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# 002 实施前的库前像（v0）：无 user_version、无 digest/created_at/chat_scope
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
    evicted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evicted_user ON evicted_chunks(user_id, agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'
);
"""

# 分区列取生产构造面的实际取值（orchestrator 取 `agent_ref.agent_id` / `agent_ref.user_id`，
# 本仓 Agent 对象不带这两属性 → 落在 `default`）。脚本按构造面本身取数，不另写推断。
LEGACY_ROWS = [
    ("default", "default", "project_roomB", "t1", "conversation", "群聊归档：下季度发布计划",
     '{"chat_scope": "room:project_roomB"}', "2026-09-01T00:00:00"),
    ("default", "default", "project_roomB", "t1", "conversation", "群聊归档：下季度发布计划",
     '{"chat_scope": "room:project_roomB"}', "2026-09-01T00:00:01"),
    ("default", "default", "s_direct", "t2", "conversation", "单聊归档：设备固件升级窗口",
     '{"chat_scope": "direct"}', "2026-09-01T00:00:02"),
    ("default", "default", None, "t3", "conversation", "无 metadata 的旧行：灰度顺序先华东",
     None, "2026-09-01T00:00:03"),
]


def buildLegacyDb(dbPath):
    """造真 v0 库：旧 DDL + 旧写入形状（旧代码不带新列也能写）。"""
    conn = sqlite3.connect(dbPath)
    conn.executescript(LEGACY_DDL)
    for row in LEGACY_ROWS:
        cur = conn.execute(
            "INSERT INTO evicted_chunks"
            " (user_id, agent_id, session_id, turn_id, source, content, metadata, evicted_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            row,
        )
        conn.execute("INSERT INTO evicted_fts(rowid, content) VALUES (?,?)", (cur.lastrowid, row[5]))
    conn.commit()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM evicted_chunks").fetchone()[0]
    conn.close()
    return version, rows


def readLedgerFacts(dbPath):
    conn = sqlite3.connect(dbPath)
    conn.row_factory = sqlite3.Row
    try:
        columns = sorted(r[1] for r in conn.execute("PRAGMA table_info(evicted_chunks)"))
        indexes = sorted(r[1] for r in conn.execute("PRAGMA index_list(evicted_chunks)"))
        rows = conn.execute("SELECT COUNT(*) FROM evicted_chunks").fetchone()[0]
        ftsRows = conn.execute("SELECT COUNT(*) FROM evicted_fts").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        digested = conn.execute(
            "SELECT COUNT(*) FROM evicted_chunks WHERE content_digest IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "user_version": version,
        "columns": columns,
        "indexes": indexes,
        "rows": rows,
        "fts_rows": ftsRows,
        "rows_without_digest": digested,
    }


def legacyDbPath(cwd, agentId):
    """生产构造面下 `EvictionLedgerDB` 实际使用的库路径（`data/context_ledger/<agent>.db`）。

    生产形状里 orchestrator 取的是 `agent_ref.agent_id`（本仓 Agent 对象不带该属性
    → 落在 `default`），故路径从构造面自身读回，不在脚本里另写一份推断。
    """
    p = os.path.join(cwd, "data", "context_ledger", f"{agentId}.db")
    return p if os.path.exists(p) else os.path.join(cwd, "data", "context_ledger", "default.db")


def migrateThroughProduction(cwd, agentId):
    """走生产构造面打开旧库（Agent → orchestrator → EvictionLedgerDB 迁移）。"""
    from neurova.agent_core import Agent, AgentConfig

    os.chdir(cwd)
    agent = Agent(AgentConfig(name=agentId, agent_id=agentId, llm_model="gpt-4o", workspace_path=cwd))
    return agent.context_orchestrator.context_pool._ledger_db.db_path


def recallThroughProduction(cwd, agentId, query):
    from neurova.agent_core import Agent, AgentConfig

    os.chdir(cwd)
    agent = Agent(AgentConfig(name=agentId, agent_id=agentId, llm_model="gpt-4o", workspace_path=cwd))
    pool = agent.context_orchestrator.context_pool
    recalled = pool.recall_evicted(query=query, limit=10)
    return [
        {
            "content": c.content,
            "chat_scope": (c.metadata or {}).get("chat_scope"),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in recalled
    ]


def main():
    workdir = tempfile.mkdtemp(prefix="ctxLedgerMigration90_")
    agentId = "ctxmig90"
    os.makedirs(os.path.join(workdir, "data", "context_ledger"), exist_ok=True)
    dbPath = legacyDbPath(workdir, agentId)

    beforeVersion, beforeRows = buildLegacyDb(dbPath)
    print(f"[1 前像 v0 库] user_version={beforeVersion} 行数={beforeRows}（含 1 条同内容重复行）")

    started = time.perf_counter()
    dbPath = migrateThroughProduction(workdir, agentId)
    bootElapsed = (time.perf_counter() - started) * 1000
    after = readLedgerFacts(dbPath)
    print(f"[2 经生产构造面迁移] 全量 Agent 启动含迁移 {bootElapsed:.0f} ms → "
          + json.dumps(after, ensure_ascii=False))

    # 纯迁移耗时（同一前像副本、同一迁移链，不含 Agent 启动）
    copyDir = tempfile.mkdtemp(prefix="ctxLedgerMigrationCopy90_")
    copyPath = os.path.join(copyDir, "copy.db")
    buildLegacyDb(copyPath)
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    started = time.perf_counter()
    EvictionLedgerDB(db_path=copyPath, user_id="default", agent_id="default")
    pureElapsed = (time.perf_counter() - started) * 1000
    print(f"[2b 纯迁移（4 行前像库）] {pureElapsed:.1f} ms")

    assert after["user_version"] == 1, "生产构造面未把旧库迁到 v1"
    assert {"content_digest", "created_at", "chat_scope"} <= set(after["columns"]), after["columns"]
    assert {"uniq_digest", "idx_scope_id"} <= set(after["indexes"]), after["indexes"]
    assert after["rows_without_digest"] == 0, "旧行 content_digest 未回填"
    assert after["rows"] == 3, f"同内容重复行未合并：{after['rows']} 行"
    assert after["fts_rows"] == 3, f"FTS 与内容表行数脱节：{after['fts_rows']}"

    again = migrateThroughProduction(workdir, agentId) and readLedgerFacts(dbPath)
    print(f"[3 重跑迁移幂等] user_version={again['user_version']} 行数={again['rows']}")
    assert again == after, "重跑迁移改变了库状态（非幂等）"

    recalled = recallThroughProduction(workdir, agentId, "固件")
    print(f"[4 召回链路（旧行作用域/归档时刻）] {json.dumps(recalled, ensure_ascii=False)}")
    assert len(recalled) == 1, f"旧库内容召回不到：{recalled}"
    assert recalled[0]["chat_scope"] == "direct", "旧行作用域读不回来（U1 兜底未生效）"
    assert recalled[0]["created_at"].startswith("2026-09-01"), "归档时刻未回退到 evicted_at"

    print("\nLIVE-VERIFY PASSED：真 v0 库经生产构造面迁到 v1，"
          "回填/合并/幂等/作用域兜底全部成立")


if __name__ == "__main__":
    main()
