#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/005 启动加载 live-verify：真库、真构造面、真读数。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data 生产库）。
用法：PYTHONPATH=. python tests/manual/context_pool_startup_load_90.py

验四件事（判据 A9 + D10 契约）：

- 预置不同规模的真库，经**真生产构造面**（真 `Agent` → 真 `ContextOrchestrator`）
  启动，核对启动只登记条数、零常驻、查询次数为常数；
- 启动代价随规模的变化（给出读数，不写单点值当精确数）；
- `rehydrate(limit)` 显式回载：顺序稳定（`id DESC`）、重复回载不产生第二份；
- `draw` 路径零 DB 访问（用 `set_trace_callback` 逐条 SQL 计数）。
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

AGENT_ID = "ctxstartup90"


def legacyAgnosticDdl():
    """由生产迁移链自身建库：先建 v0 前像，再让台账迁到 v1。"""
    return """
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
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content, tokenize='unicode61 remove_diacritics 2'
);
"""


def seedLegacyDb(dbPath, rows):
    """预置历史归档（v0 前像 + 旧写入形状；启动时由迁移链补列）。"""
    conn = sqlite3.connect(dbPath)
    conn.executescript(legacyAgnosticDdl())
    conn.execute("BEGIN")
    for i in range(rows):
        cur = conn.execute(
            "INSERT INTO evicted_chunks"
            " (user_id, agent_id, session_id, turn_id, source, content, metadata, evicted_at)"
            " VALUES ('default','default','s1', ?, 'conversation', ?, NULL, '2026-09-01T00:00:00')",
            (f"t{i}", f"历史归档第{i}条：设备固件升级窗口与灰度顺序"),
        )
        conn.execute(
            "INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)",
            (cur.lastrowid, f"历史归档第{i}条：设备固件升级窗口与灰度顺序"),
        )
        if (i + 1) % 2000 == 0:
            conn.commit()
            conn.execute("BEGIN")
    conn.commit()
    conn.close()


def tracedLedgerStatements():
    """把台账连接上的每条 SQL 挂进 `traced`（在连接建立那一刻就挂上）。

    直接构造一个真 `EvictionLedgerDB` 也量得到同一件事，但那绕开了生产构造面；
    故用子类覆写 `_openConnection`，再由 orchestrator 经模块属性创建它。
    """
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    class LedgerProbe(EvictionLedgerDB):
        def _openConnection(self):
            conn = super()._openConnection()
            conn.set_trace_callback(traced.append)
            return conn

    return LedgerProbe


def startupThroughProduction(cwd, rows, probe=True):
    """真 Agent → 真 orchestrator：量一次启动（登记）的开销与读数。

    `probe=False` 时不挂 SQL 探针（用于"先把旧库迁到 v1"的预热启动）。
    """
    import neurova.context.eviction_ledger_db as ledgerModule
    from neurova.agent_core import Agent, AgentConfig

    os.chdir(cwd)
    os.makedirs(os.path.join(cwd, "data", "context_ledger"), exist_ok=True)
    dbPath = os.path.join(cwd, "data", "context_ledger", "default.db")
    if not os.path.exists(dbPath):
        seedLegacyDb(dbPath, rows)

    originalLedger = ledgerModule.EvictionLedgerDB
    if probe:
        ledgerModule.EvictionLedgerDB = tracedLedgerStatements()
    try:
        started = time.perf_counter()
        agent = Agent(
            AgentConfig(name=AGENT_ID, agent_id=AGENT_ID, llm_model="gpt-4o", workspace_path=cwd)
        )
        elapsedMs = (time.perf_counter() - started) * 1000
    finally:
        ledgerModule.EvictionLedgerDB = originalLedger

    pool = agent.context_orchestrator.context_pool
    ledger = pool._ledger_db
    stats = pool.get_retention_stats()
    result = {
        "seeded_rows": rows,
        "agent_assembly_ms": round(elapsedMs, 1),
        "resident": pool.resident_count(),
        "ledger_rows": stats["ledger"]["rows"],
        "registered_at_startup": stats["ledger"]["registered_at_startup"],
        "startup_queries": len(traced),
        "db_path": getattr(ledger, "db_path", None),
    }
    return result, pool, ledger, stats


def startupCostOnly(cwd, rows):
    """稳态启动代价：已迁到 v1 的库上「开连接 + 登记 `COUNT(*)`」的墙钟时长。

    先跑一次把库迁到 v1（002 的一次性 schema 升级），再量第二次——A9 要的是
    "每次启动对 DB 做什么"，一次性迁移不该被算进稳态启动代价里。
    """
    import neurova.context.eviction_ledger_db as ledgerModule

    os.chdir(cwd)
    os.makedirs(os.path.join(cwd, "data", "context_ledger"), exist_ok=True)
    dbPath = os.path.join(cwd, "data", "context_ledger", "cost.db")
    seedLegacyDb(dbPath, rows)

    warmer = ledgerModule.EvictionLedgerDB(db_path=dbPath, user_id="default", agent_id="default")
    warmer.close()  # 完成 002 的一次性迁移

    started = time.perf_counter()
    ledger = ledgerModule.EvictionLedgerDB(db_path=dbPath, user_id="default", agent_id="default")
    rowsRead = ledger.count()
    elapsedMs = (time.perf_counter() - started) * 1000
    ledger.close()
    return round(elapsedMs, 1), rowsRead


traced = []


def main():
    tmp = tempfile.mkdtemp(prefix="ctxStartupLoad90_")
    print(f"[setup] 临时目录: {tmp}")
    readings = []
    measured = {}
    costs = {}
    for rows in (0, 200, 5000):
        workdir = os.path.join(tmp, f"scale_{rows}")
        os.makedirs(workdir, exist_ok=True)
        # 首次启动会把 v0 前像库迁到 v1（002 的一次性开销）；A9 量的是**稳态启动**，
        # 故先让库就位，再从第二次启动起读数——两个读数分别打印，不混为一谈。
        traced.clear()
        startupThroughProduction(workdir, rows, probe=False)
        traced.clear()
        result, pool, ledger, stats = startupThroughProduction(workdir, rows)
        readings.append(result)
        print(f"[1 稳态启动登记（库内 {rows} 条）] {json.dumps(result, ensure_ascii=False)}")
        if rows == 0:
            assert result["ledger_rows"] == 0
        else:
            assert result["ledger_rows"] == rows, "启动没有登记库内条数"
        assert result["resident"] == 0, "启动把历史塞回了常驻（D10：只登记，不预载）"
        assert result["registered_at_startup"] is True, "启动登记标记缺失"
        measured[rows] = (pool, ledger)

        costDir = os.path.join(tmp, f"cost_{rows}")
        os.makedirs(costDir, exist_ok=True)
        costMs, costRows = startupCostOnly(costDir, rows)
        costs[rows] = costMs
        print(f"[1b 稳态启动代价（开连接+登记 COUNT，库内 {rows} 条）] {costMs} ms（登记读数 {costRows}）")
        assert costRows == rows

    queryCounts = {r["seeded_rows"]: r["startup_queries"] for r in readings}
    print(f"[2 稳态启动查询次数（与行数无关）] {json.dumps(queryCounts, ensure_ascii=False)}")
    assert len(set(queryCounts.values())) == 1, (
        f"稳态启动查询次数随行数变化：{queryCounts}——启动做了与规模相关的工作"
    )
    print("    （旧库首次启动另付一次 002 的迁移开销，属一次性 schema 升级，不计入 A9）")

    # 3. rehydrate：顺序稳定 + 重复回载不产生第二份
    pool, ledger = measured[200]
    traced.clear()
    firstLoad = pool.rehydrate(limit=10)
    loadedContents = [c.content for c in firstLoad]
    print(f"[3 显式回载] 取回 {len(firstLoad)} 条；首条 = {loadedContents[0]}")
    assert len(firstLoad) == 10
    assert loadedContents[0] == "历史归档第199条：设备固件升级窗口与灰度顺序", "回载顺序不是 id DESC"
    assert pool.resident_count() == 10
    pool.rehydrate(limit=10)
    assert pool.resident_count() == 10, "重复回载产生了第二份常驻条目"

    # 4. draw 路径零 DB 访问
    before = len(traced)
    for _ in range(5):
        pool.draw(need="固件升级窗口")
        pool.query()
        pool.get_contexts()
    after = len(traced)
    print(f"[4 视图路径 DB 访问] draw/query/get_contexts 5 轮：{after - before} 次查询")
    assert after == before, "视图路径查了库（常驻集不是唯一来源）"

    # 5. recall 是唯一读路径
    recalled = pool.recall_evicted(query="灰度顺序", limit=5)
    print(f"[5 显式召回] 取回 {len(recalled)} 条；期间新增查询 {len(traced) - after} 次")
    assert recalled, "显式召回取不到内容（修过头）"

    print(f"\n[读数] 稳态启动代价（开连接 + 登记 COUNT）: {json.dumps(costs)} ms"
          "（Agent 装配成本远大于此且与本批无关，不混入读数）")
    print("LIVE-VERIFY PASSED：启动只登记（查询次数与库规模无关、零预载），"
          "回载顺序稳定且不重复，视图路径零查库")


if __name__ == "__main__":
    main()
