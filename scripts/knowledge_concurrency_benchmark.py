"""FTS5 多进程并发基准：同一索引文件、多个独立读进程。

用法：
    .venv/Scripts/python.exe scripts/knowledge_concurrency_benchmark.py --size 1000000 --workers 4
只写临时目录；读数用于判断单文件 SQLite 在多读场景下的 p95/吞吐，不替代真实压测。
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_WORDS = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
    "knowledge retrieval vector graph tenant conflict evidence lineage ledger"
).split()


def _doc(index: int) -> Dict[str, Any]:
    return {
        "knowledge_id": "doc-%08d" % index,
        "title": "文档 %d %s" % (index, _WORDS[index % len(_WORDS)]),
        "content": " ".join(_WORDS[(index + step) % len(_WORDS)] for step in range(12)),
        "tenant_id": "tenant-%d" % (index % 4),
        "visibility": "public", "lifecycle_status": "active",
        "updated_at": float(index), "tags": [_WORDS[index % len(_WORDS)]],
        "category": "bench", "source": "concurrency-bench",
    }


def _queryWorker(dbPath: str, queries: int, topK: int, offset: int):
    from neurova.knowledge.fts_index import KnowledgeFtsIndex

    index = KnowledgeFtsIndex(dbPath)
    latencies: List[float] = []
    hits = 0
    try:
        for position in range(queries):
            term = _WORDS[(offset + position) % len(_WORDS)]
            since = time.perf_counter()
            rows = index.search(
                term, {"user_id": "bench", "tenant_id": "tenant-%d" % (offset % 4)},
                limit=topK,
            )
            latencies.append((time.perf_counter() - since) * 1000.0)
            hits += len(rows)
    finally:
        index.close()
    return {"latencies": latencies, "hits": hits}


def _p95(values: List[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=1_000_000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--queries-per-worker", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from neurova.knowledge.fts_index import KnowledgeFtsIndex

    with tempfile.TemporaryDirectory(prefix="neurova-conc-") as tmp:
        dbPath = str(Path(tmp) / "fts.db")
        index = KnowledgeFtsIndex(dbPath)
        started = time.perf_counter()
        for position in range(args.size):
            index._upsertDoc("bench", _doc(position))
        index._conn.commit()
        buildSeconds = time.perf_counter() - started
        index.close()

        ctx = mp.get_context("spawn")
        started = time.perf_counter()
        with ctx.Pool(processes=max(1, args.workers)) as pool:
            results = pool.starmap(
                _queryWorker,
                [(dbPath, args.queries_per_worker, args.top_k,
                  worker * 3) for worker in range(max(1, args.workers))],
            )
        wallSeconds = time.perf_counter() - started
        latencies = [value for result in results for value in result["latencies"]]
        hits = sum(result["hits"] for result in results)
        report = {
            "benchmark": "knowledge_fts_concurrency",
            "docs": args.size,
            "workers": args.workers,
            "queries": len(latencies),
            "build_seconds": round(buildSeconds, 3),
            "wall_seconds": round(wallSeconds, 3),
            "throughput_qps": round(len(latencies) / wallSeconds, 2) if wallSeconds else None,
            "p50_ms": round(statistics.median(latencies), 3),
            "p95_ms": round(_p95(latencies), 3),
            "mean_hits": round(hits / max(len(latencies), 1), 2),
            "disk_mb": round(Path(dbPath).stat().st_size / (1024 * 1024), 2)
            if Path(dbPath).exists() else None,
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
