"""rerank 双模入口。

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


def buildRunner(config: dict, providerResolver=None):
    """唯一的 runner 装配口（工单 014）。旁路 API 与对话主路都从这里拿。

    返回 `(runner, method_label, note)`：`note=None` 表示正常；请求 `model` 而模型通道
    不可用时退化为加权融合，**note 必须带原因**、label 必须是实际生效的那个——
    把退化标成 "model" 就是冒充已生效。

    装配只此一份：两处各写一遍就会各差一段（同 §5 第四条硬约束的病，只是长在排序上）。
    """
    from .model_rerank_runner import ModelRerankRunner
    from .weight_rerank_runner import WeightRerankRunner

    method = (config.get("method") or "weight").strip().lower()
    weights = config.get("weights") or None
    if method not in ("weight", "model"):
        raise ValueError(f"未知 rerank method: {method!r}（有效值: weight / model）")

    if method == "model":
        from neurova.llm import rerank_client as rc

        provider_name = str(config.get("rerank_provider") or "").strip()
        if providerResolver is None:
            providerResolver = rc.build_rerank_provider
        try:
            provider = providerResolver(provider_name)
        except rc.RerankConfigError as e:
            # 只吞"配置类"故障：后端故障（RerankBackendError）继续上抛，
            # 让调用方按故障处理而不是被一次静默退化抹平。
            return WeightRerankRunner(weights), "weight", {
                "requested": "model", "reason": e.reason}
        if provider is None:
            return WeightRerankRunner(weights), "weight", {
                "requested": "model", "reason": "provider_unavailable:%s" % (provider_name or "(default)")}
        return ModelRerankRunner(provider, fallback_weights=weights), "model", None
    return WeightRerankRunner(weights), "weight", None
