"""知识检索规模基准：SQLite + FTS5 的写入吞吐、查询 p50/p95 与磁盘占用。

用法：
    .venv/Scripts/python.exe scripts/knowledge_scale_benchmark.py --sizes 100000 1000000

只写临时目录，不触碰生产数据根。读数落 JSON，供存储迁移决策引用；
没跑过的规模不编造读数（报告里标 unmeasured）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neurova.knowledge.fts_index import KnowledgeFtsIndex

_WORDS = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
    "knowledge retrieval vector graph tenant conflict evidence lineage ledger "
    "budget policy schedule server cache index chunk document ocr pipeline"
).split()


def _doc(index: int) -> Dict[str, Any]:
    return {
        "knowledge_id": "doc-%08d" % index,
        "title": "文档 %d %s" % (index, _WORDS[index % len(_WORDS)]),
        "content": (" ".join(_WORDS[(index + step) % len(_WORDS)] for step in range(12))
                    + " 条目编号 %d" % index),
        "tenant_id": "tenant-%d" % (index % 4),
        "visibility": "public",
        "lifecycle_status": "active",
        "updated_at": float(index),
        "tags": [_WORDS[index % len(_WORDS)]],
        "category": "bench",
        "source": "scale-bench",
    }


def _percentile(values: List[float], ratio: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[position]


def runOne(size: int, queries: int, topK: int) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="neurova-scale-") as tmp:
        dbPath = str(Path(tmp) / "fts.db")
        index = KnowledgeFtsIndex(dbPath)
        started = time.perf_counter()
        for position in range(size):
            index._upsertDoc("bench", _doc(position))
        index._conn.commit()
        buildSeconds = time.perf_counter() - started

        latencies: List[float] = []
        hits = 0
        for queryIndex in range(queries):
            term = _WORDS[queryIndex % len(_WORDS)]
            since = time.perf_counter()
            rows = index.search(
                term,
                {"user_id": "bench", "tenant_id": "tenant-%d" % (queryIndex % 4)},
                limit=topK,
            )
            latencies.append((time.perf_counter() - since) * 1000.0)
            hits += len(rows)
        diskMb = Path(dbPath).stat().st_size / (1024 * 1024)
        index.close()
        return {
            "docs": size,
            "build_seconds": round(buildSeconds, 3),
            "docs_per_second": round(size / buildSeconds, 1) if buildSeconds else None,
            "queries": queries,
            "top_k": topK,
            "p50_ms": round(statistics.median(latencies), 3),
            "p95_ms": round(_percentile(latencies, 0.95), 3),
            "mean_hits": round(hits / max(queries, 1), 2),
            "disk_mb": round(diskMb, 2),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100_000, 1_000_000])
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    readings = []
    for size in args.sizes:
        reading = runOne(size, args.queries, args.top_k)
        readings.append(reading)
        print(json.dumps(reading, ensure_ascii=False))

    decision = {
        "threshold_p95_ms": 500.0,
        "threshold_docs": 1_000_000,
        "verdict": "keep_embedded",
        "basis": "所有实测规模 p95 均低于阈值且规模未超 100 万",
    }
    breached = [
        row for row in readings
        if row["p95_ms"] > decision["threshold_p95_ms"]
        or row["docs"] > decision["threshold_docs"]
    ]
    if breached:
        decision = {
            "threshold_p95_ms": 500.0,
            "threshold_docs": 1_000_000,
            "verdict": "migrate_or_shard",
            "basis": "实测越线: %s" % ", ".join(str(row["docs"]) for row in breached),
        }
    report = {
        "benchmark": "knowledge_scale",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine": "SQLite FTS5 (knowledge_fts_docs + knowledge_fts)",
        "unmeasured": [size for size in (1_000_000, 10_000_000) if size not in args.sizes],
        "readings": readings,
        "decision": decision,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
