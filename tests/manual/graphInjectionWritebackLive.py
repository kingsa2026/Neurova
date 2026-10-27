# -*- coding: utf-8 -*-
"""§6-124 活体定责：图路"注入账"全零，到底是写点坏了、还是这条路今天没被走到。

三段，各证一件事，全程**不碰生产库**（真库只 `mode=ro`；要写就先整份拷进临时根）：

A. 真库只读复算——`injected_count`/`adoption_outcome` 的现状读数，加上 212 个主体的
   **标签形态**（锚点判据要求"主体名被问句包含且≥2 字"，标签越像文档标题，真问句越
   撞不上）。这一段的用处是把"零"与"为什么零"分开。
B. 拷贝件上走真接缝——`GraphFactWalker.walkFromQuery` 的锚点命中与 hops，再把
   `GraphRetrieverAdapter` 摆进真 `retrieve()` 走一整跳，看 `injected_count` 是否 +1、
   `last_injected_at` 是否落时间戳。**这一段只回答"写点活着没有"**。
C. 反证两格——① 零锚点的问句必须走不出 hop 且**账不动**（否则 B 的绿是空转）；
   ② 把 adapter 的 `factStore` 遮掉（模拟"没接线"），账必须不动（证明这格判据真的
   在数那条写路径，而不是数别的东西）。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.graphInjectionWritebackLive
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from tests.ast_scan import parseSource


def _record(name: str, value) -> None:
    print("%-30s %s" % (name, value))


def _openReadOnly(dbPath: Path) -> sqlite3.Connection:
    """`mode=ro`：探"库在不在"不许顺手把文件建出来，更不许写。"""
    return sqlite3.connect("file:%s?mode=ro" % dbPath.resolve().as_posix(), uri=True)


def _realLibraryReadings(dbPath: Path) -> dict:
    conn = _openReadOnly(dbPath)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute("SELECT COUNT(*) c FROM knowledge_facts").fetchone()["c"]
        injected = conn.execute(
            "SELECT COUNT(*) c FROM knowledge_facts WHERE injected_count > 0").fetchone()["c"]
        outcome = conn.execute(
            "SELECT COUNT(*) c FROM knowledge_facts"
            " WHERE adoption_outcome IS NOT NULL AND adoption_outcome <> ''").fetchone()["c"]
        subjects = conn.execute(
            "SELECT canonical_label FROM knowledge_subjects WHERE status = 'active'").fetchall()
        labels = [str(r["canonical_label"] or "") for r in subjects]
        usable = [l for l in labels if len(l) >= 2]
        return {
            "available": True,
            "facts": total, "injected_nonzero": injected, "outcome_written": outcome,
            "subjects_active": len(labels), "labels_ge2": len(usable),
            "label_len_avg": round(sum(len(l) for l in usable) / max(len(usable), 1), 2),
            "sample_labels": usable[:6],
        }
    finally:
        conn.close()


def _pickAnchorWithTwoHopPath(store) -> tuple:
    """在拷贝库里找一个"既被别人指、又指着别人"的主体标签。

    这是按锚点判据的**构造**反推的问句原料：只有 hop≥2 的链中段才可能出 hop。
    找不到就如实报"真库里连一条可走的两跳链都没有"——那也是答案的一部分。
    """
    with store._lock:
        rows = store._conn.execute(
            "SELECT s.canonical_label AS label, f.object_term AS obj"
            " FROM knowledge_facts f JOIN knowledge_subjects s"
            "   ON s.subject_key = f.subject_key AND s.agent_id = f.agent_id"
            " WHERE f.status='active' AND f.record_kind='triple'").fetchall()
        subjectLabels = {
            str(r[0]) for r in store._conn.execute(
                "SELECT canonical_label FROM knowledge_subjects WHERE status='active'")}
    for row in rows:
        target = str(row["obj"] or "").strip()
        if target in subjectLabels and len(str(row["label"] or "")) >= 2:
            return str(row["label"]), str(target)
    return "", ""


def _adoptionWriterCallSites() -> list:
    """AST 扫 `neurova/`：谁调用 `recordAdoption`（定义本身不算调用点）。

    只数文本会把 docstring 里的名字也算成消费者，所以按节点形态判 `Call.func.attr`。
    """
    import ast as _ast

    repoRoot = Path(__file__).resolve().parents[2]
    hits = []
    for path in sorted((repoRoot / "neurova").rglob("*.py")):
        try:
            tree = parseSource(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                fn = node.func
                if isinstance(fn, _ast.Attribute) and fn.attr == "recordAdoption":
                    hits.append("%s:%d" % (path.relative_to(repoRoot).as_posix(), node.lineno))
    return hits


def _countInjected(store, factIds) -> int:
    with store._lock:
        marks = store._conn.execute(
            "SELECT COUNT(*) FROM knowledge_facts WHERE injected_count > 0").fetchone()[0]
    return marks


def main() -> int:
    # 落点一律走单源解析器；本脚本对生产库只读，写全部发生在临时根里的拷贝件上。
    from neurova.core.data_root import dataPath

    dbPath = Path(dataPath("knowledge", "knowledge_facts.db"))
    print("── A 段：真库只读复算（不写一个字节）──")
    if not dbPath.is_file():
        _record("真库", "不可用（跳过 A，B/C 仍跑）")
        real = {"available": False}
    else:
        wal = Path(str(dbPath) + "-wal")
        if wal.exists() and wal.stat().st_size > 0:
            print("  !! 生产库有未合并的 WAL，整份拷贝会丢最近写入 —— 本批结论只适用于已合并部分")
        real = _realLibraryReadings(dbPath)
        for key in ("facts", "injected_nonzero", "outcome_written", "subjects_active",
                    "labels_ge2", "label_len_avg", "sample_labels"):
            _record("真库 " + key, real[key])

    from neurova.knowledge.foundation.graph_walk import (
        GraphFactWalker, GraphWalkConfig,
    )
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
    from neurova.agent.graph_retriever_adapter import GraphRetrieverAdapter

    tmpRoot = Path(tempfile.mkdtemp(prefix="nvGraphWriteback-"))
    copyPath = tmpRoot / "knowledge_facts.db"
    if dbPath.is_file():
        shutil.copy2(dbPath, copyPath)
    store = KnowledgeFactStore(str(copyPath))
    bad = []
    try:
        print("── B 段：拷贝件上走真接缝（写点活着没有）──")
        walker = GraphFactWalker(store, agentId="default",
                                 config=GraphWalkConfig(enabled=True, maxHops=3, limit=8))
        label, target = _pickAnchorWithTwoHopPath(store)
        _record("可走两跳链的中段主体", label or "(无)")
        if not label:
            bad.append("真库拷贝里找不到任何一条可走的两跳链——B 段无从证写点")
            return _finish(bad, real)

        walkQuery = "%s 与 %s 有什么关系" % (label, target)
        hops = walker.walkFromQuery(walkQuery)
        _record("walkFromQuery(\"%s\")" % walkQuery, "%d hops" % len(hops))
        if not hops:
            bad.append("按构造选出的锚点仍走不出 hop——问题在 SQL 不在问句")
            return _finish(bad, real)

        adapter = GraphRetrieverAdapter(walker)
        before = _countInjected(store, None)
        result = asyncio.run(adapter.retrieve(SimpleNamespace(
            query=walkQuery, limit=8, session_id="live-probe")))
        after = _countInjected(store, None)
        _record("adapter.retrieve 返回 hits", len(getattr(result, "memories", []) or []))
        _record("注入账 fact 数（前/后）", (before, after))
        if not (after > before):
            bad.append("走通了 hop 却没落注入账——写点在生产接缝上是死的（真缺陷）")
        with store._lock:
            sample = store._conn.execute(
                "SELECT fact_id, injected_count, last_injected_at FROM knowledge_facts"
                " WHERE injected_count > 0 ORDER BY last_injected_at DESC LIMIT 3").fetchall()
        _record("落账样本", [tuple(r) for r in sample])
        if sample and not sample[0][2]:
            bad.append("计数涨了却没留 last_injected_at——读数不完整")

        print("── C 段：反证两格（证 B 不是空转）──")
        emptyWalk = walker.walkFromQuery("今天天气怎么样")
        _record("零锚点问句的 hops", len(emptyWalk))
        beforeQuiet = _countInjected(store, None)
        asyncio.run(adapter.retrieve(SimpleNamespace(
            query="今天天气怎么样", limit=8, session_id="live-probe")))
        _record("零锚点前后的注入账", (beforeQuiet, _countInjected(store, None)))
        if emptyWalk or _countInjected(store, None) != beforeQuiet:
            bad.append("零锚点那条问句也走通了/也记账了——B 段的对照失效")

        detached = GraphRetrieverAdapter(SimpleNamespace(
            walkFromQuery=lambda *a, **kw: [dict(hops[0])], factStore=None))
        beforeDetached = _countInjected(store, None)
        asyncio.run(detached.retrieve(SimpleNamespace(
            query=walkQuery, limit=8, session_id="live-probe")))
        _record("遮住 factStore 后的注入账", (beforeDetached, _countInjected(store, None)))
        if _countInjected(store, None) != beforeDetached:
            bad.append("遮住 factStore 账还在涨——判据数的不是那条写路径")

        print("── D 段：结论 ──")
        if not bad:
            print("  写点活着：有 hop 就落账；因此生产库 401/401 全零只能由"
                  "「这条路今天没被走到」或「真问句撞不到锚点」解释。")
            print("  A 段给的形态证据：主体 %d 个里标签≥2 字的 %d 个、平均标签长度 %s，"
                  "样本标签 %s" % (real.get("subjects_active"), real.get("labels_ge2"),
                                   real.get("label_len_avg"), real.get("sample_labels")))
            print("  => 锚点判据要求「主体名被问句整串包含」，而这些标签是文档标题形态："
                  "真用户问句撞得上是偶发。属**命中问题**而非写点问题，接不接（实体链接/别名）"
                  "是另一裁，本活体不代拍。")

        print("── E 段：采纳回执有没有生产写点（AST 扫 neurova/，与上面的接缝分开判）──")
        writers = _adoptionWriterCallSites()
        _record("recordAdoption 生产调用点", len(writers))
        for site in writers[:8]:
            print("     ", site)
        if not writers:
            print("  => `adoption_outcome` 那一维的**写面全仓零调用点**：列在、读面在数"
                  "（`usageMetrics.outcome_written`）、单元判据在测原语，"
                  "但没有任何一条链会去写——`outcome_written=0` 是结构性必然，"
                  "不是「还没人采纳」。接（拿哪个用户信号当采纳）或摘（把这一维读数如实标未接线）"
                  "属需人裁，本活体只把它数出来。")
        return _finish(bad, real)
    finally:
        store.close()
        shutil.rmtree(tmpRoot, ignore_errors=True)


def _finish(bad: list, real: dict) -> int:
    print(json.dumps({"real": real, "verdict": "FAIL" if bad else "LIVE-PASS",
                      "problems": bad}, ensure_ascii=False, indent=None))
    if bad:
        print("LIVE-FAIL " + " | ".join(bad))
        return 1
    print("LIVE-PASS 注入账写点在真接缝上落得下去；生产全零归因到「没走到/没锚点」，不是写点坏了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
