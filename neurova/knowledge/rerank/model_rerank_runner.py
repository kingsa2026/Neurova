"""模型重排（Dify RerankModelRunner 同型）。

rerank_provider(query, doc_texts) -> List[float]（与候选等长）。
provider 为注入式扩展点（bge-reranker / cohere rerank / LLM 打分等由
调用方装配——当前仓库无内置 rerank 模型）；provider 异常或返回长度
不符时，有 fallback_weights 则退化加权融合，否则原样抛出。
"""

from typing import Callable, List, Optional

from .weight_rerank_runner import WeightRerankRunner


class ModelRerankRunner:
    def __init__(
        self,
        rerank_provider: Callable[[str, List[str]], List[float]],
        fallback_weights: Optional[dict] = None,
    ):
        self._provider = rerank_provider
        self._fallback = WeightRerankRunner(fallback_weights) if fallback_weights else None

    def rerank(self, query, docs):
        if not docs:
            return []
        try:
            texts = [str(doc.get("content") or doc.get("id", "")) for doc in docs]
            scores = [float(s) for s in self._provider(query, texts)]
            if len(scores) != len(docs):
                raise ValueError(
                    f"rerank provider 返回 {len(scores)} 个分数 vs {len(docs)} 个候选"
                )
        except Exception:
            if self._fallback is None:
                raise
            return self._fallback.rerank(query, docs)
        scored = [
            {"index": int(doc.get("index", pos)), "score": scores[pos], "doc": doc}
            for pos, doc in enumerate(docs)
        ]
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored
