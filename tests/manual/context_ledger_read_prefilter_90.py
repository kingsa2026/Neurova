#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/004 读侧预筛与转义 live-verify：真库、真查询路径、真命中对拍。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_ledger_read_prefilter_90.py

验四件事（判据 A3/A4 + D9）：
- CJK 长查询的命中集合与 LIKE 真值**逐条相等**（不只手比条数）；
- `%` / `_` 不被当成 LIKE 通配模式（改前实测库内 N 行时命中 N 行）；
- <3 字符查询**不走 MATCH**（trigram 无索引能力 → 假阴性），由 SQL 轨迹证明；
- 候选集上限生效：高命中查询走"最近 N 条 + 候选内过滤"，不整库拉回。
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

CORPUS = [
    "上下文压缩窗口预算的实测数据：折叠阈值为 36%",
    "上下文池归档与召回路径的隔离闸口讨论",
    "窗口预算与折叠阈值：中文查询在 unicode61 下命中为零",
    "The context window budget decides whether folding triggers.",
    "JSON 工具结果：{\"tool\": \"file_read\", \"bytes\": 4096}",
    "带下划线 a_b 与百分号 100% 的库内文本",
]


def likeTruth(ledger, query):
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = ledger._requireConn().execute(
        "SELECT content FROM evicted_chunks"
        " WHERE user_id = ? AND agent_id = ? AND content LIKE ? ESCAPE '\\'",
        (ledger.user_id, ledger.agent_id, f"%{escaped}%"),
    ).fetchall()
    return sorted(row["content"] for row in rows)


def main():
    tmp = tempfile.mkdtemp(prefix="ctxLedgerPrefilter90_")
    print(f"[setup] 临时目录: {tmp}")

    from neurova.context import eviction_ledger_db as ledgerModule
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    dbPath = os.path.join(tmp, "ledger.db")
    ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
    ledger.beginBatch()
    for index, text in enumerate(CORPUS):
        ledger.record(content=text, turn_id=f"t{index}", session_id="s1")
    ledger.commitBatch()
    print("[0 库内前像] " + json.dumps({"rows": ledger.count()}, ensure_ascii=False))

    # ── 1. CJK 长查询：命中集合逐条对拍 LIKE 真值
    cjk = {}
    for query in ("上下文压缩", "窗口预算", "上下文池"):
        hits = sorted(row["content"] for row in ledger.search(query, limit=50))
        truth = likeTruth(ledger, query)
        cjk[query] = {"hits": len(hits), "truth": len(truth), "equal": hits == truth}
        assert hits == truth, f"查询 {query!r} 命中集合 != LIKE 真值：{hits} vs {truth}"
    print("[1 CJK 对拍] " + json.dumps(cjk, ensure_ascii=False))

    # ── 2. LIKE 元字符不越权
    meta = {}
    for query in ("%", "_", "%_%"):
        hits = sorted(row["content"] for row in ledger.search(query, limit=50))
        truth = likeTruth(ledger, query)
        meta[query] = {"hits": len(hits), "total": ledger.count(), "equal": hits == truth}
        assert hits == truth, f"查询 {query!r} 把输入当成了通配模式：{hits}"
        assert len(hits) < ledger.count() or not hits, f"查询 {query!r} 命中全库"
    print("[2 元字符] " + json.dumps(meta, ensure_ascii=False))

    # ── 3. 短查询不得走 MATCH（用 SQL 轨迹证明"派发决定"，不是看耗时）
    statements = []
    ledger._requireConn().set_trace_callback(statements.append)
    short = {}
    for query in ("归档", "窗口", "a_"):
        statements.clear()
        hits = sorted(row["content"] for row in ledger.search(query, limit=50))
        usedMatch = any("MATCH" in stmt.upper() for stmt in statements)
        short[query] = {"hits": len(hits), "reached_match": usedMatch}
        assert not usedMatch, f"短查询 {query!r} 走了 MATCH（trigram 下即假阴性）"
        assert hits == likeTruth(ledger, query), f"短查询 {query!r} 漏召回"
    print("[3 短查询派发] " + json.dumps(short, ensure_ascii=False))
    ledger._requireConn().set_trace_callback(None)

    # ── 4. 候选集上限：高命中查询走降级分支
    bigPath = os.path.join(tmp, "big.db")
    big = EvictionLedgerDB(db_path=bigPath, user_id="u1", agent_id="a1")
    big.beginBatch()
    for index in range(3000):
        big.record(content=f"第{index}条：上下文压缩与窗口预算的讨论", session_id="s1")
    for index in range(3):
        big.record(content=f"稀疏标记 ZEPHYR{index}：上下文压缩记录", session_id="s1")
    big.commitBatch()
    started = time.perf_counter()
    capped = big.search("上下文", limit=50)
    elapsed = (time.perf_counter() - started) * 1000
    print("[4 候选集上限] " + json.dumps(
        {"candidate_limit": ledgerModule.CANDIDATE_LIMIT, "db_rows": big.count(),
         "returned": len(capped), "latency_ms": round(elapsed, 2),
         "all_contain_substring": all("上下文" in row["content"] for row in capped)},
        ensure_ascii=False,
    ))
    assert capped, "高命中查询返回空集（降级把命中整个丢掉了）"
    assert all("上下文" in row["content"] for row in capped), "降级结果不满足子串约束"

    # ── 5. 与"改前形状"对拍：单次 JOIN + ORDER BY id DESC（旧实现的查询形状）
    #
    # 旧形状的代价随命中规模**非单调**：SQLite 对 FTS 虚表 JOIN 后按内容表 id 排序，
    # 稀疏命中时仍要扫完匹配项再排序（真库 5 万行、1269 命中实测 400+ ms），
    # 而命中密集时反而能靠 FTS 行序早退。
    # 两个读数都如实打印，不挑对自己有利的那条——降级分支买的是**内存有界**
    # （候选集 ≤ CANDIDATE_LIMIT），不是"永远更快"。
    shapes = {}
    for query, label in (("ZEPHYR1", "稀疏命中"), ("上下文压缩", "密集命中")):
        total = big._requireConn().execute(
            "SELECT COUNT(*) FROM evicted_fts WHERE evicted_fts MATCH ?", ('"%s"' % query,)
        ).fetchone()[0]

        def oldShape():
            return big._requireConn().execute(
                "SELECT e.* FROM evicted_chunks e JOIN evicted_fts f ON e.id = f.rowid"
                " WHERE e.user_id = 'u1' AND e.agent_id = 'a1' AND evicted_fts MATCH ?"
                " ORDER BY e.id DESC LIMIT 20",
                ('"%s"' % query,),
            ).fetchall()

        def newShape():
            return big.search(query, limit=20)

        shapes[label] = {
            "match_total": total,
            "old_join_ms": round(_medianMs(oldShape), 2),
            "new_search_ms": round(_medianMs(newShape), 2),
        }
    print("[5 查询形状对拍（真库 3000 行，5 次取中位）] " + json.dumps(shapes, ensure_ascii=False))

    for handle in (ledger, big):
        handle.close()
    print("LIVE-VERIFY PASSED")


def _medianMs(fn, rounds=5):
    fn()
    samples = []
    for _ in range(rounds):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return samples[len(samples) // 2]


if __name__ == "__main__":
    main()
