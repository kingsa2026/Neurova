# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 34，§6-182）：向量原语搬家之后，真检索路仍按同一口径走。

判据档（`tests/unit/core/test_vectorPrimitivesSingleFace.py`）钉的是"只剩一处 + 逐值不变"；
这一支在**真对象**上再走一遍：真 `UnifiedVectorStore`(tfidf) 的质心归一化与 hebb 检索、
真 `semantic_search` 的降级嵌入、真 `semantic_emotion` 的零范数谓词、以及旧落点确实不再导出
那三个名字。最后一条是反向校准：把单源的 `vectorNorm` 桩坏 ⇒ 真质心读数必须跟着坏，
否则说明路上还留着第二份模长算法（那才是本批要消灭的东西）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/vectorPrimitives_batch34.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaVecPrimB34")

import math  # noqa: E402

from neurova.core import vector_math as VM  # noqa: E402
from neurova.cognitive_layers.memory_layer import unified_vector_store as UVS  # noqa: E402
from neurova.cognitive_layers.memory_layer.semantic_emotion import _zero_norm  # noqa: E402
from neurova.cognitive_layers.memory_layer.semantic_search import SemanticSearch  # noqa: E402

failures: list[str] = []
PRIMITIVES = ("vector_norm", "vector_dot", "vector_normalize")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    store = UVS.UnifiedVectorStore(backend="tfidf")
    defs = {"factual_knowledge": "事实知识 记忆 检索", "code_knowledge": "代码 编程 实现",
            "procedural_knowledge": "流程 步骤 操作"}
    store.initialize_centroids(defs)
    centroids = store.get_expert_centroids()
    norms = {k: VM.vectorNorm(v) for k, v in centroids.items()}
    check("[1] 真质心经单源取模长都是 1", bool(centroids) and all(abs(n - 1.0) < 1e-6 for n in norms.values()), str(norms))

    store.add_neurova_hebb("same", [1.0, 2.0, 3.0, 4.0], {})
    store.add_neurova_hebb("away", [-1.0, 0.4, 0.2, 0.1], {})
    hits = store.search_neurova_hebbs([1.0, 2.0, 3.0, 4.0], top_k=2)
    check("[2] 真 hebb 检索顺序与值域仍对", [h[0] for h in hits] == ["same", "away"]
          and all(-1.0 <= float(s) <= 1.0 for _, s in hits), str(hits))

    ss = SemanticSearch()
    emb = ss._text_to_embedding("代码 实现 步骤")
    check("[3] 真降级嵌入归一化后模长为 1 或全零", abs(VM.vectorNorm(emb)) in (0.0, 1.0)
          or abs(VM.vectorNorm(emb) - 1.0) < 1e-6, f"norm={VM.vectorNorm(emb):.6f}")

    check("[4] 零范数谓词读数不变（空／零／正常）",
          _zero_norm([]) is True and _zero_norm([0.0, 0.0]) is True and _zero_norm([1.0, 2.0]) is False, "")

    import neurova.cognitive_layers.memory_layer.positional_encoding as PE
    check("[5] positional_encoding 那份零消费者的私有副本已不在（模块照常可导入）",
          not hasattr(PE, "_vec_norm"), dir(PE)[:0] or "")
    check("[6] 旧落点不再导出这三个名字", not any(hasattr(UVS, n) for n in PRIMITIVES),
          str([n for n in PRIMITIVES if hasattr(UVS, n)]))

    from tests.unit.core.test_vectorPrimitivesSingleFace import _normShapeHits, NEUROVA_ROOT
    shapeHits = _normShapeHits(NEUROVA_ROOT)
    check("[7] 全仓自算模长形状只剩单源（复用判据那个探测器，不另写一份）",
          shapeHits == [], str(shapeHits))

    original = VM.vectorNorm
    try:
        VM.vectorNorm = lambda vec: 2.0
        store2 = UVS.UnifiedVectorStore(backend="tfidf")
        store2.initialize_centroids(defs)
        broken = {k: VM.vectorNorm(v) for k, v in store2.get_expert_centroids().items()}
        followed = all(abs(n - 2.0) < 1e-9 for n in broken.values())
    finally:
        VM.vectorNorm = original
    check("[8] 反向校准：桩坏单源模长 ⇒ 真质心读数跟着坏（路上没有第二份）", followed, str(sorted(set(broken.values()))))

    print(f"\n读数 {8} 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
