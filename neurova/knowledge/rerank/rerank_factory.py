"""rerank 双模入口（Dify RerankRunnerFactory 同型）。

method="weight"（默认，无外部依赖）/ "model"（需 rerank_provider）。
空输入恒返回 []。
"""

from .model_rerank_runner import ModelRerankRunner
from .weight_rerank_runner import WeightRerankRunner


def rerank(query, docs, method="weight", weights=None, rerank_provider=None):
    """重排入口。

    docs: [{"index": int, "id": str, "bm25"?: f, "vector"?: f, "fts"?: f, "content"?: str}, ...]
    返回 [{"index", "score", "doc"(原引用)}] 按 score 降序。
    method 非法抛 ValueError。
    """
    if not docs:
        return []
    m = (method or "weight").strip().lower()
    if m == "weight":
        return WeightRerankRunner(weights).rerank(query, docs)
    if m == "model":
        if rerank_provider is None:
            raise ValueError("method='model' 需要 rerank_provider")
        return ModelRerankRunner(rerank_provider, fallback_weights=weights).rerank(query, docs)
    raise ValueError(f"未知 rerank method: {method!r}（有效值: weight / model）")
