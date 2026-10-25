"""知识向量索引的可选 ANN 后端（hnswlib / faiss）。

依赖政策：两者都不在基础依赖里。未安装、版本不兼容或构建失败时，
调用方回退到 `KnowledgeVectorIndex` 的 JSON 全量余弦——ANN 是加速项，
不是正确性的前提。选择顺序与阈值都可配置：

- `NEUROVA_KB_ANN_BACKEND`：auto（默认，优先 hnswlib）/ hnswlib / faiss / off
- `NEUROVA_KB_ANN_MIN_RECORDS`：低于该条数不建 ANN（小语料全量扫描更便宜）

后端只认「固定维度、非零、有限值」的向量；任何一条不满足就拒绝建索引，
由调用方回退，避免近似索引静默丢条目。
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neurova.core import vector_math
from neurova.core.logger import get_logger

logger = get_logger(__name__)

ANN_BACKEND_ENV = "NEUROVA_KB_ANN_BACKEND"
ANN_MIN_RECORDS_ENV = "NEUROVA_KB_ANN_MIN_RECORDS"
DEFAULT_ANN_MIN_RECORDS = 2048


def _unitRows(matrix: Any) -> Any:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class _HnswAnnBackend:
    name = "hnswlib"

    def __init__(self) -> None:
        import hnswlib  # noqa: F401 - 可用性探测

        self._lib = hnswlib

    def build(self, vectors: Dict[str, List[float]]) -> Dict[str, Any]:
        import numpy as np

        ids = list(vectors)
        matrix = np.asarray([vectors[kid] for kid in ids], dtype="float32")
        matrix = _unitRows(matrix)
        index = self._lib.Index(space="cosine", dim=int(matrix.shape[1]))
        index.init_index(max_elements=len(ids), ef_construction=200, M=16)
        index.add_items(matrix, np.arange(len(ids), dtype="int64"))
        index.set_ef(max(64, min(256, len(ids))))
        return {"index": index, "labels": ids}

    def search(
        self, handle: Dict[str, Any], query: Sequence[float], topK: int
    ) -> List[Tuple[str, float]]:
        import numpy as np

        ids: List[str] = handle["labels"]
        k = min(max(1, int(topK)), len(ids))
        q = _unitRows(np.asarray([query], dtype="float32"))
        labels, distances = handle["index"].knn_query(q, k=k)
        return [
            (ids[int(label)], 1.0 - float(distance))
            for label, distance in zip(labels[0], distances[0])
        ]


class _FaissAnnBackend:
    name = "faiss"

    def __init__(self) -> None:
        import faiss  # noqa: F401 - 可用性探测

        self._lib = faiss

    def build(self, vectors: Dict[str, List[float]]) -> Dict[str, Any]:
        import numpy as np

        ids = list(vectors)
        matrix = np.asarray([vectors[kid] for kid in ids], dtype="float32")
        matrix = _unitRows(matrix)
        faiss = self._lib
        try:
            index = faiss.IndexHNSWFlat(
                int(matrix.shape[1]), 32, faiss.METRIC_INNER_PRODUCT
            )
            index.hnsw.efConstruction = 200
            index.hnsw.efSearch = max(64, min(256, len(ids)))
        except Exception:  # noqa: BLE001 - 老版本 faiss 无 HNSW 时退回精确内积
            index = faiss.IndexFlatIP(int(matrix.shape[1]))
        index.add(matrix)
        return {"index": index, "labels": ids}

    def search(
        self, handle: Dict[str, Any], query: Sequence[float], topK: int
    ) -> List[Tuple[str, float]]:
        import numpy as np

        ids: List[str] = handle["labels"]
        k = min(max(1, int(topK)), len(ids))
        q = _unitRows(np.asarray([query], dtype="float32"))
        distances, labels = handle["index"].search(q, k)
        return [
            (ids[int(label)], float(distance))
            for label, distance in zip(labels[0], distances[0])
            if int(label) >= 0
        ]


def resolveAnnBackend(
    preference: Optional[str] = None,
) -> Tuple[Optional[Any], str]:
    """按配置选择后端；返回 (backend|None, reason)。

    reason 为空表示选中；否则是**为什么没有**（off / unknown / not_installed），
    由健康读数原样报出，不把「没装」写成「关掉了」。
    """
    raw = preference if preference is not None else os.environ.get(
        ANN_BACKEND_ENV, "auto"
    )
    choice = str(raw or "auto").strip().lower()
    if choice in ("off", "none", "disabled", "0", "false"):
        return None, "disabled_by_config"
    candidates = {
        "hnswlib": _HnswAnnBackend,
        "faiss": _FaissAnnBackend,
    }
    if choice == "auto":
        order = ["hnswlib", "faiss"]
    elif choice in candidates:
        order = [choice]
    else:
        return None, "unknown_backend:%s" % choice

    failures = []
    for name in order:
        try:
            return candidates[name](), ""
        except Exception as exc:  # noqa: BLE001 - 可选依赖缺失/不兼容都只是"没有"
            failures.append("%s:%s" % (name, exc))
            logger.debug("知识向量 ANN 后端不可用 %s: %s", name, exc)
    return None, "backend_unavailable:" + ";".join(failures)


def annMinRecords(value: Optional[int] = None) -> int:
    if value is not None:
        return max(0, int(value))
    raw = os.environ.get(ANN_MIN_RECORDS_ENV, "")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_ANN_MIN_RECORDS


def prepareVectors(
    records: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, List[float]]]:
    """校验并收集可建索引的向量；维度不一致/空向量/非有限值返回 None（调用方回退）。"""
    vectors: Dict[str, List[float]] = {}
    dimension: Optional[int] = None
    for kid, record in records.items():
        raw = record.get("vector") if isinstance(record, dict) else None
        if not isinstance(raw, (list, tuple)) or not raw:
            return None
        try:
            vector = [float(x) for x in raw]
        except (TypeError, ValueError):
            return None
        if any(not math.isfinite(x) for x in vector):
            return None
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            return None
        if vector_math.vectorNorm(vector) <= vector_math.ZERO_NORM_EPSILON:
            continue  # 零向量没有任何余弦信号，不进 ANN
        vectors[str(kid)] = vector
    return vectors if vectors else None
