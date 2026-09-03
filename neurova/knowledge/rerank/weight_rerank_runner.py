"""加权分融合重排（Dify WeightRerankRunner 同型）。

score = Σ_c w_c · doc[c]（缺通道按 0）；与查询无关——通道分数已在
召回期算好，此处只做加权融合与排序。
"""


class WeightRerankRunner:
    DEFAULT_WEIGHTS = {"bm25": 0.4, "vector": 0.4, "fts": 0.2}

    def __init__(self, weights=None):
        self._weights = dict(weights) if weights else dict(self.DEFAULT_WEIGHTS)

    def rerank(self, query, docs):
        """docs: [{"index": int, "id": str, "bm25"?: f, "vector"?: f, "fts"?: f}, ...]

        返回 [{"index", "score", "doc"(原引用)}] 按 score 降序。
        """
        if not docs:
            return []
        scored = []
        for pos, doc in enumerate(docs):
            score = sum(
                float(w) * (float(doc.get(ch, 0.0)) if doc.get(ch) is not None else 0.0)
                for ch, w in self._weights.items()
            )
            scored.append({"index": int(doc.get("index", pos)), "score": score, "doc": doc})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored
