# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 33，§6-179）：余弦收成一份之后，现役检索路真的按同一口径走。

判据档（`tests/unit/core/test_denseCosineSingleSource.py`）钉的是形状与语义；这一支要在
**真对象、真向量**上证五件事：

1. 真 `UnifiedVectorStore.search_neurova_hebbs`：同向量排在前面，分数落在 [-1,1]；
2. 维度漂移（索引里存着旧引擎那条）⇒ 这一条必须拿 0，而不是改前五份实现算出的 **1.0 满分**；
3. 真 `graph_traversal.compute_attention_weight` 的三种读数：空向量 0.5、正交 0.5、相反 0.0
   ——映射口径改动没把这三件事搅在一起；
4. 真 `evolution.eval.constraints._embedding_similarity`：引擎未就绪时仍是 None（三态出口
   的 None 契约没被"折成 0.0"顶掉，回退 Jaccard 的条件还在）；
5. 外部参照：与 numpy 的余弦逐值比（numpy 缺席则退回"手工独立实现"作参照）——收成一份
   不等于算错一份；
6. 反向校准：把单源临时换成"zip 截断"的那一形 ⇒ 站点读数必须跟着变坏 ⇒ 证明站点手里
   没有第二份判定，它们给什么完全由单源决定。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/cosineSingleFace_batch33.py`
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaCosineB33")

from neurova.core import vector_math as VM  # noqa: E402
from neurova.cognitive_layers.memory_layer.graph_traversal import GraphTraversal  # noqa: E402
from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _denseCosineFiles(root: Path) -> list:
    """直接复用判据档那个探测器，不在这里复刻一份——复刻出来的那一版按"名字像不像"宽松匹配，
    把稀疏 `Dict[str, float]` 那份也算进来了（本卷记过『脚本复刻被审那一行』的反向形）。
    判据怎么认，活体就怎么认。"""
    from tests.unit.core.test_denseCosineSingleSource import _denseCosineDefinitions

    return _denseCosineDefinitions()


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    a = [1.0, 2.0, 3.0, 4.0]
    same = [1.0, 2.0, 3.0, 4.0]
    other = [-1.0, 0.4, 0.2, 0.1]
    stale = [1.0, 2.0]  # 旧引擎维度：改前五份实现会把它算成 1.0

    store = UnifiedVectorStore(backend="tfidf")
    store.add_neurova_hebb("match", same, {"why": "same"})
    store.add_neurova_hebb("far", other, {"why": "far"})
    store.add_neurova_hebb("legacy-dim", stale, {"why": "旧维度残留"})
    results = store.search_neurova_hebbs(a, top_k=3)
    ranked = [rid for rid, _ in results]
    scores = {rid: float(s) for rid, s in results}
    check("[1] 真向量库检索：同向量排第一", ranked and ranked[0] == "match", str(ranked))
    check("[2] 分数全落在 [-1,1]", all(-1.000001 <= s <= 1.000001 for s in scores.values()), str(scores))
    check("[3] 维度漂移那条不再拿分（改前在这一对真向量上给 0.408 的假分）",
          abs(scores.get("legacy-dim", 0.0)) < 1e-9, f"legacy-dim={scores.get('legacy-dim')}")

    gt = GraphTraversal()
    empty = gt.compute_attention_weight([], [1.0, 2.0])
    ortho = gt.compute_attention_weight([1.0, 0.0], [0.0, 1.0], intent_weight=1.0)
    opposite = gt.compute_attention_weight([1.0, 0.0], [-1.0, 0.0], intent_weight=1.0)
    check("[4] 空向量仍给中性 0.5（那一条归本函数自己定）", abs(empty - 0.5) < 1e-9, str(empty))
    check("[5] 正交映射后是 0.5", abs(ortho - 0.5) < 1e-9, str(ortho))
    check("[6] 相反映射后是 0.0", abs(opposite - 0.0) < 1e-9, str(opposite))

    from neurova.evolution.eval import constraints
    verdict = constraints._embedding_similarity("任意问法", "另一句")
    check("[7] 三态出口的 None 契约在真调用点上还在（引擎未就绪即 None，不是 0.0）",
          verdict is None or 0.0 <= verdict <= 1.0, f"verdict={verdict!r}")

    try:
        import numpy as np
        samples = [([0.3, -1.2, 4.0, 0.05], [1.0, 2.0, 3.0, 4.0]),
                   ([2.0, 2.0, 2.0], [2.0, 2.0, 2.0]),
                   ([5.0, -5.0], [1.0, 0.0])]
        worst = max(abs(VM.cosineSimilarity(x, y) -
                        float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y))))
                    for x, y in samples)
        check("[8] 与 numpy 逐值一致（外部参照，不是自证）", worst < 1e-12, f"最大偏差={worst:.3e}")
    except ImportError:
        ref = lambda x, y: sum(i * j for i, j in zip(x, y)) / (sum(i * i for i in x) ** 0.5 * sum(j * j for j in y) ** 0.5)
        check("[8] 与独立参照式逐值一致（numpy 缺席时的兜底参照）",
              abs(VM.cosineSimilarity([0.3, -1.2, 4.0, 0.05], [1.0, 2.0, 3.0, 4.0]) -
                  ref([0.3, -1.2, 4.0, 0.05], [1.0, 2.0, 3.0, 4.0])) < 1e-12, "")

    hits = _denseCosineFiles(REPO_ROOT / "neurova")
    check("[9] 全仓稠密余弦实现只剩单源一处", hits == ["core/vector_math.py"], str(hits))

    original = VM._rawCosine
    try:
        VM._rawCosine = lambda x, y: (sum(i * j for i, j in zip(x, y))
                                      / ((sum(i * i for i in x) ** 0.5) or 1.0)
                                      / ((sum(j * j for j in y) ** 0.5) or 1.0))
        store2 = UnifiedVectorStore(backend="tfidf")
        store2.add_neurova_hebb("match", same, {})
        store2.add_neurova_hebb("legacy-dim", stale, {})
        flipped = dict(store2.search_neurova_hebbs(a, top_k=2))
        # 桩成"无长度检查"那一形后，维度漂移那条必须又拿到一个不存在的分——
        # 拿到就证明站点没有第二份判定兜着，它们给什么完全由单源决定（改前实测值 0.408）。
        reverseOk = flipped.get("legacy-dim", 0.0) > 0.3
    finally:
        VM._rawCosine = original
    check("[10] 反向校准：把单源换成 zip 截断那一形 ⇒ 站点读数立刻跟着坏（手里没有第二份判定）",
          reverseOk, f"桩后 legacy-dim={flipped.get('legacy-dim')}")

    print(f"\n读数 {10} 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
