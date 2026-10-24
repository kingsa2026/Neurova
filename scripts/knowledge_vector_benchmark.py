"""知识向量路规模基准（hnswlib，384 维，余弦）。

用法：
    .venv/Scripts/python.exe scripts/knowledge_vector_benchmark.py --sizes 100000 1000000
只写临时目录；读数与 FTS 基准分开报告，不把近似索引的延迟冒充端到端检索。
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


def _unitRows(matrix):
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _p95(values: List[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def runOne(size: int, dim: int, queries: int, topK: int, seed: int) -> Dict[str, Any]:
    import hnswlib
    import numpy as np

    rng = np.random.default_rng(seed)
    with tempfile.TemporaryDirectory(prefix="neurova-vec-") as tmp:
        index = hnswlib.Index(space="cosine", dim=dim)
        index.init_index(max_elements=size, ef_construction=200, M=16)
        started = time.perf_counter()
        batch = 50000
        for offset in range(0, size, batch):
            rows = _unitRows(rng.standard_normal((min(batch, size - offset), dim), dtype=np.float32))
            index.add_items(rows, np.arange(offset, offset + len(rows), dtype="int64"))
        buildSeconds = time.perf_counter() - started
        index.set_ef(64)
        latencies = []
        hits = 0
        for _ in range(queries):
            query = _unitRows(rng.standard_normal((1, dim), dtype=np.float32))
            since = time.perf_counter()
            labels, _dist = index.knn_query(query, k=min(topK, size))
            latencies.append((time.perf_counter() - since) * 1000.0)
            hits += len(labels[0])
        path = str(Path(tmp) / "index.bin")
        index.save_index(path)
        diskMb = Path(path).stat().st_size / (1024 * 1024)
    return {
        "vectors": size, "dim": dim, "queries": queries, "top_k": topK,
        "build_seconds": round(buildSeconds, 3),
        "vectors_per_second": round(size / buildSeconds, 1) if buildSeconds else None,
        "p50_ms": round(statistics.median(latencies), 3),
        "p95_ms": round(_p95(latencies), 3),
        "mean_hits": round(hits / max(queries, 1), 2),
        "index_disk_mb": round(diskMb, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100_000, 1_000_000])
    parser.add_argument("--dim", type=int, default=384)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    readings = [runOne(size, args.dim, args.queries, args.top_k, args.seed)
                for size in args.sizes]
    report = {
        "benchmark": "knowledge_vector_ann",
        "engine": "hnswlib (cosine, M=16, ef_construction=200, ef=64)",
        "dim": args.dim,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": "随机单位向量读数，用于容量/延迟量级判断；不代表真实语料召回率",
        "readings": readings,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
