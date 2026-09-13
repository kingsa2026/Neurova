# -*- coding: utf-8 -*-
"""rerank 模型通道客户端（Yuxi 对比 P0-3 接线）。

根因修复：Dify 对标轮建好了 ModelRerankRunner/factory，但唯一生产装配点
`semantic_search_api._resolve_rerank_provider` 恒返回 None——"声明未接线"。
本模块补上真实链路：provider_manager 配置里带 `rerank` 能力的模型 →
OpenAI 兼容 `POST {base_url}/rerank`（SiliconFlow/Jina/Cohere 系协议：
请求 {model, query, documents, top_n} → 响应 {results:[{index,
relevance_score}]}），返回 `(query, texts)->scores` 的同步 callable，
由端点层经 asyncio.to_thread 调用（不阻塞事件循环）。

错误分型是硬要求（Yuxi 反面教材：aquery 吞错 return []，"零结果"与
"后端故障"不可区分）：
- RerankConfigError：配置面问题（模型未配置/服务商禁用/无 base_url）
- RerankBackendError(kind=network|http|contract)：调用面故障
两类都必须能被调用方如实写进响应，不得伪装成正常排序。
"""
import os
from typing import Callable, List, Optional

import httpx

__all__ = [
    "RerankConfigError",
    "RerankBackendError",
    "find_rerank_model",
    "build_rerank_provider",
    "get_provider_manager",
]

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("NEUROVA_RERANK_TIMEOUT") or 10.0)
_RERANK_CAPABILITY = "rerank"


class RerankConfigError(RuntimeError):
    """rerank 通道配置问题（非后端故障）。reason 供响应层如实透出。"""

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


class RerankBackendError(RuntimeError):
    """rerank 后端调用故障。kind ∈ network|http|contract。"""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


def get_provider_manager():
    """惰性单例（测试经 monkeypatch 本函数注入替身 manager）。"""
    from neurova.llm.provider_manager import get_provider_manager as _get

    return _get()


def find_rerank_model(manager=None) -> Optional[str]:
    """能力发现：第一个被显式标记 rerank 能力的模型 id（无则 None）。"""
    mgr = manager or get_provider_manager()
    for p in mgr.list_providers():
        if not getattr(p, "enabled", True):
            continue
        meta = getattr(p, "model_metadata", None) or {}
        for model_id, m in meta.items():
            caps = [str(c).strip().lower() for c in ((m or {}).get("capabilities") or [])]
            if _RERANK_CAPABILITY in caps:
                return model_id
    return None


def build_rerank_provider(
    model_name: str = "", manager=None
) -> Callable[[str, List[str]], List[float]]:
    """解析出可调用的 rerank provider：(query, doc_texts) -> scores(与候选等长)。

    model_name 为空时走 find_rerank_model() 能力发现；两路皆无 →
    RerankConfigError(not_configured)。
    """
    model = (model_name or "").strip() or (find_rerank_model(manager) or "")
    if not model:
        raise RerankConfigError(
            "未配置 rerank 模型（provider 能力标记或显式指定其一）",
            reason=f"not_configured:{model_name or '(default)'}",
        )
    mgr = manager or get_provider_manager()
    target = None
    for p in mgr.list_providers():
        names = set(getattr(p, "models", None) or [])
        names |= set(getattr(p, "discovered_models", None) or [])
        if getattr(p, "default_model", None):
            names.add(p.default_model)
        if model in names:
            target = p
            break
    if target is None:
        raise RerankConfigError(
            f"rerank 模型 {model!r} 未在任何已配置服务商的模型列表中找到",
            reason=f"not_configured:{model}",
        )
    if not getattr(target, "enabled", True):
        raise RerankConfigError(
            f"服务商 {getattr(target, 'name', '?')!r} 已禁用",
            reason=f"provider_disabled:{getattr(target, 'name', 'unknown')}",
        )
    base_url = (getattr(target, "base_url", "") or "").rstrip("/")
    if not base_url:
        raise RerankConfigError(
            f"服务商 {getattr(target, 'name', '?')!r} 缺少 base_url",
            reason="provider_no_base_url",
        )
    api_key = getattr(target, "api_key", None) or ""

    def provider(query: str, doc_texts: List[str]) -> List[float]:
        texts = list(doc_texts)
        payload = {
            "model": model,
            "query": query,
            "documents": texts,
            "top_n": len(texts),
            "return_documents": False,
        }
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            resp = httpx.post(
                f"{base_url}/rerank",
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as e:
            raise RerankBackendError(f"rerank 后端不可达: {e}", kind="network") from e
        if resp.status_code >= 400:
            raise RerankBackendError(
                f"rerank 后端 HTTP {resp.status_code}: {resp.text[:200]}", kind="http"
            )
        try:
            results = resp.json().get("results")
        except (ValueError, AttributeError) as e:
            raise RerankBackendError(
                "rerank 后端响应非 JSON 或缺 results", kind="contract"
            ) from e
        if not isinstance(results, list):
            raise RerankBackendError("rerank 后端 results 字段缺失或非列表", kind="contract")
        scores: List[Optional[float]] = [None] * len(texts)
        for item in results:
            idx = (item or {}).get("index")
            score = (item or {}).get("relevance_score")
            if idx is None or score is None or not (0 <= int(idx) < len(texts)) or scores[int(idx)] is not None:
                raise RerankBackendError(
                    "rerank 后端 index/score 契约不符（越界、重复或缺字段）", kind="contract"
                )
            scores[int(idx)] = float(score)
        if any(s is None for s in scores):
            got = sum(1 for s in scores if s is not None)
            raise RerankBackendError(
                f"rerank 后端返回 {got} 个分数 vs {len(texts)} 个候选", kind="contract"
            )
        return [float(s) for s in scores]

    return provider
