#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/007 保留策略 live-verify：真库、真生产构造面、真收敛读数。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_ledger_gc_90.py

验四件事（判据 A5 + D11）：
- GC 触发点在生产可达：经**真生产构造面**（真 `Agent` → 真 `ContextOrchestrator`）
  归档若干轮后，`ledger_gc.runs` 真的涨了（改前挂在不可达的驱逐路径上，恒 0）；
- 保留策略两维默认生效：`keep_count` 超限后内容表收敛到上限；
- FTS 与内容表不脱节：清理前后两表行数相等；
- 清理读数随清理扣减，且**与库内实况一致**（不写成会过期的快照）。
"""
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def ftsRows(dbPath):
    conn = sqlite3.connect(dbPath)
    try:
        return conn.execute("SELECT COUNT(*) FROM evicted_fts").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def contentRows(dbPath):
    conn = sqlite3.connect(dbPath)
    try:
        return conn.execute("SELECT COUNT(*) FROM evicted_chunks").fetchone()[0]
    finally:
        conn.close()


def archiveThroughProduction(cwd, agentId, rounds=3):
    """真 Agent → 真 orchestrator：走生产归档路径（GC 触发点所在的那条路）。"""
    import asyncio

    from neurova.agent_core import Agent, AgentConfig

    os.chdir(cwd)
    agent = Agent(AgentConfig(name=agentId, agent_id=agentId, llm_model="gpt-4o", workspace_path=cwd))
    orchestrator = agent.context_orchestrator
    for r in range(rounds):
        history = [
            {"role": "user", "content": f"第{r}轮第{i}条：保留策略与磁盘占用讨论"} for i in range(4)
        ]
        asyncio.run(
            orchestrator.build_context(
                user_input="继续", session_context=history, relevant_memories=[], experience_items=[]
            )
        )
    pool = orchestrator.context_pool
    stats = pool.get_retention_stats()
    return pool, stats


def main():
    tmp = tempfile.mkdtemp(prefix="ctxLedgerGc90_")
    print(f"[setup] 临时目录: {tmp}")

    # ── 1. 生产构造面上的 GC 触发：两段读法，缺一段都证明不了"可达"
    #
    # 1a. 稳态（N=20，模块常量不动）：归档提交必须计入节流计数。改前该计数
    #     只被 `_archive_evicted` 递增，而它在生产构造面永不执行——故本段是
    #     触发点搬家的直接判据。
    # 1b. 把 N 临时调小（仅本脚本为在一次运行里看清真实触发；常量本身不动）：
    #     观察 `ledger_gc.runs` 真的涨了，且 `removed` 与库内实际一致。
    import neurova.context_pool as cpModule

    prodDir = os.path.join(tmp, "prod")
    os.makedirs(prodDir, exist_ok=True)
    pool, stats = archiveThroughProduction(prodDir, "ctxgc90", rounds=3)
    dbPath = pool._ledger_db.db_path
    batches = stats["ledger_persistence"]["batches"]
    print(
        "[1a 生产面节流计数] "
        + json.dumps(
            {"batches": batches, "gc_counter": pool._ledger_gc_counter,
             "counter_limit": cpModule._LEDGER_GC_EVERY},
            ensure_ascii=False,
        )
    )
    assert pool._ledger_gc_counter == batches, (
        "归档提交没有计入 GC 节流——触发点仍挂在不可达路径上"
    )
    pool._ledger_db.close()

    originalEvery = cpModule._LEDGER_GC_EVERY
    cpModule._LEDGER_GC_EVERY = 2
    try:
        tightDir = os.path.join(tmp, "prod_tight")
        os.makedirs(tightDir, exist_ok=True)
        poolTight, statsTight = archiveThroughProduction(tightDir, "ctxgc90tight", rounds=3)
    finally:
        cpModule._LEDGER_GC_EVERY = originalEvery
    tightRows = contentRows(poolTight._ledger_db.db_path)
    print(
        "[1b 生产面真实触发（N 临时调为 2）] "
        + json.dumps(
            {"gc_runs": statsTight["ledger_gc"]["runs"], "gc_removed": statsTight["ledger_gc"]["removed"],
             "last_error": statsTight["ledger_gc"]["last_error"], "db_rows": tightRows},
            ensure_ascii=False,
        )
    )
    assert statsTight["ledger_gc"]["runs"] >= 1, "生产面上 GC 一次都没触发（触发点仍不可达）"
    assert statsTight["ledger_gc"]["last_error"] is None, "生产面 GC 报错"
    poolTight._ledger_db.close()
    os.chdir(ROOT)

    # ── 2. 保留策略两维默认生效（真库批量写入 → 池侧节流触发收敛）
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context.pool_models import ContextInput, ContextSource
    from neurova.context_pool import ContextPool

    limitPath = os.path.join(tmp, "retention.db")
    ledger = EvictionLedgerDB(db_path=limitPath, user_id="u", agent_id="a", keep_count=200)
    poolLimit = ContextPool(user_id="u", agent_id="a", session_id="s1", ttl_seconds=0, ledger_db=ledger)
    import neurova.context_pool as cpModule

    cpModule._LEDGER_GC_EVERY = 1  # 稳态下每批都触发；只为在一次运行里看清收敛
    try:
        for i in range(900):
            poolLimit.add_context(
                ContextInput(source=ContextSource.CONVERSATION, content=f"归档条目 {i}", metadata={"turn_id": f"t{i}"})
            )
        statsLimit = poolLimit.get_retention_stats()
    finally:
        cpModule._LEDGER_GC_EVERY = originalEvery

    content = contentRows(limitPath)
    fts = ftsRows(limitPath)
    print(
        "[2 保留策略收敛] "
        + json.dumps(
            {"keep_count": 200, "content_rows": content, "fts_rows": fts,
             "gc_runs": statsLimit["ledger_gc"]["runs"], "gc_removed": statsLimit["ledger_gc"]["removed"]},
            ensure_ascii=False,
        )
    )
    assert content == 200, f"内容表未收敛到上限（{content}）"
    assert fts == content, f"FTS 与内容表脱节（{fts} vs {content}）"

    # ── 3. 清理读数与实际一致（不写成会过期的快照）
    reported = statsLimit["ledger_gc"]["removed"]
    expected = 900 - 200
    print(f"[3 清理读数核对] 上报 removed={reported} / 实际减少 {expected}")
    assert reported == expected, "清理条数上报与库内实际减少不一致"
    ledger.close()

    # ── 4. keep_days 维度（注入旧 evicted_at）
    import datetime

    daysPath = os.path.join(tmp, "retention_days.db")
    days = EvictionLedgerDB(db_path=daysPath, user_id="u", agent_id="a", keep_days=30)
    for i in range(5):
        days.record(content=f"旧条目 {i}", session_id="s1")
    old = (datetime.datetime.now() - datetime.timedelta(days=90)).isoformat()
    conn = sqlite3.connect(daysPath)
    try:
        conn.execute("UPDATE evicted_chunks SET evicted_at = ?", (old,))
        conn.commit()
    finally:
        conn.close()
    removedDays = days.gc_stale()
    print(
        "[4 keep_days 维度] "
        + json.dumps({"removed": removedDays, "content_rows": days.count(), "fts_rows": ftsRows(daysPath)},
                     ensure_ascii=False)
    )
    assert removedDays == 5 and days.count() == 0 and ftsRows(daysPath) == 0
    days.close()

    print("\nLIVE-VERIFY PASSED：GC 触发点在生产可达，保留策略两维默认生效，"
          "FTS 与内容表对齐，清理读数与库内实况一致")


if __name__ == "__main__":
    main()
