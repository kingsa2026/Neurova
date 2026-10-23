# -*- coding: utf-8 -*-
"""可选 ANN 向量后端规模探针（build / search / 召回对照）。

口径：
- 直接走 `neurova.knowledge.vector_ann.resolveAnnBackend()` 的真后端，
  向量为归一化随机矩阵（dim=32），id 为字符串序号——与生产
  `KnowledgeVectorIndex` 交给后端的数据形状一致（dict -> 矩阵）。
- 召回对照：ANN top-k 与同数据精确内积 top-k 的交集 / k，样本 5 条 query。
- 未安装可选依赖时如实报 unavailable 并返回 1，不静默跳过。
- 数据根隔离（`isolatedDataRoot`），不发网络请求。

跑法：`.venv/Scripts/python.exe tests/manual/knowledgeAnnScaleProbe.py [sizes]`
默认 10000,100000,1000000。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

isolatedDataRoot(prefix="neurovaAnnProbe")

import numpy as np  # noqa: E402

from neurova.knowledge.vector_ann import resolveAnnBackend  # noqa: E402

DIM = 32
TOP_K = 10
QUERY_COUNT = 5


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _run(backend, size: int, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    matrix = _unit(rng.random((size, DIM), dtype=np.float32))
    ids = [str(index) for index in range(size)]
    vectors = {ids[index]: matrix[index] for index in range(size)}

    build_start = time.perf_counter()
    handle = backend.build(vectors)
    build_ms = (time.perf_counter() - build_start) * 1000.0

    query_indices = rng.choice(size, size=QUERY_COUNT, replace=False)
    queries = matrix[query_indices]
    search_start = time.perf_counter()
    ann_hits = [backend.search(handle, queries[row].tolist(), TOP_K) for row in range(QUERY_COUNT)]
    search_ms = (time.perf_counter() - search_start) * 1000.0 / QUERY_COUNT

    recall = 0.0
    for row in range(QUERY_COUNT):
        exact_scores = matrix @ queries[row]
        exact = np.argpartition(-exact_scores, TOP_K)[:TOP_K]
        ann_ids = {str(item[0]) for item in ann_hits[row]}
        recall += len(ann_ids & {str(i) for i in exact}) / TOP_K
    recall /= QUERY_COUNT

    del vectors, handle
    return {
        "size": size,
        "dim": DIM,
        "build_ms": round(build_ms, 1),
        "search_ms": round(search_ms, 2),
        "recall_at_k": round(recall, 4),
        "top_k": TOP_K,
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    sizes = [int(value) for value in sys.argv[1:]] or [10_000, 100_000, 1_000_000]
    backend, reason = resolveAnnBackend()
    if backend is None:
        print("[FAIL] ANN 后端不可用：%s（基础 requirements.txt 已含 hnswlib，重装后重跑）" % reason)
        return 1
    print("后端：%s；阈值内维度：%d" % (backend.name, DIM))
    for size in sizes:
        reading = _run(backend, size)
        print("size=%-9d build=%-10s ms  search=%-8s ms  recall@%d=%s" % (
            reading["size"], reading["build_ms"], reading["search_ms"],
            reading["top_k"], reading["recall_at_k"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())