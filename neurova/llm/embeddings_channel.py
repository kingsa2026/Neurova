# -*- coding: utf-8 -*-
"""LLM 层 embeddings 通道（R11，参照系 ad 追平批三）。

全仓向量此前只有本地 bge-small-zh（ONNXEmbeddingEngine）一条路。本通道按
OpenAI 兼容 /embeddings 约定接云端嵌入（siliconflow / dashscope-compatible /
zhipu 等已铺量服务商均有此端点），供记忆/活水池/技能语义**可选切换**。

激活：NEUROVA_EMBEDDING_PROVIDER（provider id）与 NEUROVA_EMBEDDING_MODEL
（模型 id）**同时**设置才启用；缺任一 → 不激活，默认仍本地（存量行为
逐位不变）。

诚实口径：远程通道失败**不回落本地**——不同嵌入空间的向量不可比，静默
换空间会污染既有向量索引；失败按 EmbeddingChannelError（encode）/ None
（encodeOrNone）暴露，由消费方按"本轮无嵌入"处理。
"""
from __future__ import annotations

import os
import time
from typing import List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

EMBEDDING_PROVIDER_ENV = "NEUROVA_EMBEDDING_PROVIDER"
EMBEDDING_MODEL_ENV = "NEUROVA_EMBEDDING_MODEL"


class EmbeddingChannelError(RuntimeError):
    """远程嵌入通道失败（诚实暴露，不回落本地）。"""


def getEmbeddingChannelTarget() -> Optional[Tuple[str, str]]:
    """读取远程通道配置；返回 (provider_id, model)，未配置返回 None。"""
    provider_id = os.environ.get(EMBEDDING_PROVIDER_ENV, "").strip()
    model = os.environ.get(EMBEDDING_MODEL_ENV, "").strip()
    if provider_id and model:
        return provider_id, model
    return None


def _resolveProvider(provider_id: str) -> Tuple[str, str]:
    """解析服务商凭据（管理面 ProviderConfig 单源），返回 (api_key, base_url)。"""
    from neurova.llm.provider_manager import get_provider_manager

    pm = get_provider_manager()
    if pm is None:
        raise EmbeddingChannelError(f"provider manager 不可用，无法解析 {provider_id}")
    provider = pm.get_provider(provider_id)
    if provider is None:
        raise EmbeddingChannelError(f"嵌入服务商不存在: {provider_id}")
    api_key = getattr(provider, "api_key", None) or getattr(provider, "encrypted_api_key", None)
    base_url = (getattr(provider, "base_url", "") or "").rstrip("/")
    if not base_url:
        raise EmbeddingChannelError(f"嵌入服务商缺 base_url: {provider_id}")
    return str(api_key or ""), base_url


def embedTexts(
    texts: List[str],
    *,
    provider_id: str,
    model: str,
    timeout: float = 30.0,
) -> List[List[float]]:
    """OpenAI 兼容 /embeddings：返回与 texts 等序的向量列表。

    失败一律抛 EmbeddingChannelError（不造零向量、不回落本地）。
    """
    if not texts:
        return []
    api_key, base_url = _resolveProvider(provider_id)
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model, "input": list(texts)}
    started = time.time()
    try:
        resp = httpx.post(f"{base_url}/embeddings", headers=headers,
                          json=body, timeout=timeout)
    except Exception as e:
        raise EmbeddingChannelError(
            f"embeddings 请求失败（{provider_id}/{model}）: {e}") from e
    if resp.status_code != 200:
        raise EmbeddingChannelError(
            f"embeddings 上游 {resp.status_code}（{provider_id}/{model}）: "
            f"{resp.text[:200]}")
    data = resp.json().get("data") or []
    vectors: List[Optional[List[float]]] = [None] * len(texts)
    for item in data:
        try:
            idx = int(item.get("index", 0))
        except (TypeError, ValueError):
            raise EmbeddingChannelError(
                f"embeddings 响应 index 非法: {item.get('index')!r}") from None
        vec = item.get("embedding")
        if vec is None:
            raise EmbeddingChannelError(
                f"embeddings 响应缺 embedding 字段（index={idx}）")
        if 0 <= idx < len(vectors):
            vectors[idx] = [float(x) for x in vec]
    if any(v is None for v in vectors):
        raise EmbeddingChannelError(
            f"embeddings 响应向量数不齐：要 {len(texts)} 条，回 {len(data)} 条")
    result = [v for v in vectors if v is not None]
    logger.debug("embeddings 通道 %s/%s：%d 条，%.0fms", provider_id, model,
                 len(result), (time.time() - started) * 1000)
    return result
