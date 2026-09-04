"""
Semantic Search API - 语义搜索API端点

支持：hybrid, bm25, vector, compare, analyze

批次 2（RAG 演进）：
- body.source 支持 "memory"（默认，行为不变）与 "knowledge"：
  knowledge 语料 = 当前用户可见的知识条目（标题+正文），
  经 KnowledgeRepository.visible_items 做可见性过滤
- /hybrid 每条结果附带 confidence_breakdown（bm25/vector/fts/rrf 归一化分），
  供前端展示召回可信度
- 检索端点接入 JWT 鉴权（知识语料依赖用户身份；前端此前无调用方）

P0-3（Dify 对标 2026-09-03）：
- fts 路复活：full_text_search（IDF 加权词覆盖，真分数）替换 0.0 占位
- body.retrieval_method 四态（RetrievalMethod）：semantic/full_text/hybrid/keyword
- body.rerank 双模重排出口（WeightRerankRunner/ModelRerankRunner），
  结果带 rerank_score/rerank_method；rerank 异常降级 rrf 原序不阻断
"""

from neurova.core.logger import get_logger
import math
import re
import typing
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.cognitive_layers.memory_layer.manager import get_memory_manager
from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search
from neurova.knowledge.search import RetrievalMethod, full_text_search as _kb_full_text_search
from neurova.knowledge.search import tokenize as _kb_tokenize

logger = get_logger(__name__)
router = APIRouter()


def _get_runtime_memory_manager(request: Request):
    """解析运行时 Agent 的 MemoryManager（断点 S1 修复）。

    模块级单例与运行时 Agent 的 per-agent MemoryManager 内存隔离，
    导致本 API 曾永远检索不到聊天记忆。现优先取 app.state.agents 中
    首个活跃 Agent 的 memory_manager，无活跃 Agent 时才降级单例。
    """
    agents = getattr(request.app.state, "agents", {}) or {}
    for agent in agents.values():
        manager = getattr(agent, "memory_manager", None) or getattr(
            getattr(agent, "memory_agent", None), "memory_manager", None
        )
        if manager is not None:
            return manager
    return get_memory_manager()


class HybridSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    bm25_weight: float = Field(default=0.4, ge=0, le=1)
    vector_weight: float = Field(default=0.4, ge=0, le=1)
    fts_weight: float = Field(default=0.2, ge=0, le=1)
    filters: typing.Optional[dict] = None
    source: str = Field(default="memory", description="语料来源：memory（默认）/ knowledge")
    # P0-3：RetrievalMethod 四态（短别名 semantic/full_text/keyword/hybrid 均可）
    retrieval_method: str = Field(
        default="hybrid",
        description="检索方法：hybrid（默认）/semantic/full_text/keyword",
    )
    # P0-3：rerank 出口，None = 不重排（保持 rrf 次序）
    rerank: typing.Optional[dict] = Field(
        default=None,
        description='重排配置：{"method":"weight","weights":{...}} / {"method":"model","rerank_provider":"<name>"}',
    )


def _load_corpus(body: "HybridSearchRequest", request: Request, current_user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按 body.source 取检索语料。

    - memory（默认）：运行时 Agent 的全部记忆（原行为）
    - knowledge：当前用户可见的知识条目（public + 本人私有 + 共享给我），
      文档内容为 标题\\n正文，id=knowledge_id，并带 title 供前端展示
    """
    if (getattr(body, "source", "memory") or "memory") == "knowledge":
        from neurova.knowledge.repository import get_knowledge_repository

        entries = get_knowledge_repository().visible_items(current_user)
        corpus: List[Dict[str, Any]] = []
        for e in entries:
            title = str(e.get("title", ""))
            content = str(e.get("content", ""))
            corpus.append(
                {
                    "id": str(e.get("knowledge_id", "")),
                    "content": (title + "\n" + content) if title else content,
                    "title": title,
                }
            )
        return corpus
    try:
        mgr = _get_runtime_memory_manager(request)
        return mgr.get_all_memories() or []
    except Exception as e:
        logger.warning("hybrid_search: 获取记忆语料失败: %s", e)
        return []


class CompareRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)


def _analyze_query_features(query: str) -> dict:
    """分析查询特征"""
    words = query.split()
    has_exact = '"' in query
    has_special = bool(re.search(r"[+\-~*]", query))
    word_count = len(words)
    avg_word_len = sum(len(w) for w in words) / max(word_count, 1)

    return {
        "word_count": word_count,
        "avg_word_length": round(avg_word_len, 2),
        "has_exact_match": has_exact,
        "has_special_operators": has_special,
        "is_short_query": word_count <= 2,
        "is_long_query": word_count >= 8,
    }


def _recommend_weights(features: dict) -> dict:
    """根据查询特征推荐权重"""
    if features["is_short_query"]:
        return {
            "bm25_weight": 0.5,
            "vector_weight": 0.3,
            "fts_weight": 0.2,
            "reason": "Short queries favor keyword matching",
        }
    elif features["is_long_query"]:
        return {
            "bm25_weight": 0.3,
            "vector_weight": 0.5,
            "fts_weight": 0.2,
            "reason": "Long queries favor semantic understanding",
        }
    else:
        return {
            "bm25_weight": 0.4,
            "vector_weight": 0.4,
            "fts_weight": 0.2,
            "reason": "Balanced weights for medium queries",
        }


def _get_suggestion(features: dict) -> str:
    """根据查询特征给出建议"""
    if features["is_short_query"]:
        return "Consider adding more context to improve semantic matching"
    if features["is_long_query"]:
        return "Query is detailed; vector search should perform well"
    return "Query length is optimal for hybrid search"


def _tokenize(text: str) -> List[str]:
    """中英文分词（BM25 用）——委托 knowledge.search.tokenize 单一实现，
    与 FTS/keyword 通道保持可比（P0-1 jieba 真分词后双通道同源）。"""
    return _kb_tokenize(text)


def _bm25_search(
    query: str,
    corpus: List[Dict[str, Any]],
    top_k: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
) -> List[Tuple[str, float]]:
    """Okapi BM25 搜索

    分数归一化到 [0, 1]（除以最大原始分数）。
    """
    if not corpus or not query:
        return []
    query_terms = _tokenize(query)
    if not query_terms:
        return []
    N = len(corpus)
    doc_lens: List[int] = []
    df: Dict[str, int] = {}
    doc_tokens: List[List[str]] = []
    for doc in corpus:
        tokens = _tokenize(str(doc.get("content", "")))
        doc_tokens.append(tokens)
        doc_lens.append(len(tokens))
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    avgdl = (sum(doc_lens) / N) if N > 0 else 0.0
    raw_scores: List[Tuple[str, float]] = []
    for i, tokens in enumerate(doc_tokens):
        score = 0.0
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        dl = doc_lens[i]
        for term in query_terms:
            if term not in tf:
                continue
            n = df.get(term, 0)
            idf = math.log((N - n + 0.5) / (n + 0.5) + 1.0)
            denom = tf[term] + k1 * (1 - b + b * (dl / avgdl if avgdl > 0 else 0))
            if denom > 0:
                score += idf * (tf[term] * (k1 + 1)) / denom
        raw_scores.append((str(corpus[i].get("id", "")), score))
    max_score = max((s for _, s in raw_scores), default=0.0)
    if max_score > 0:
        raw_scores = [(mid, s / max_score) for mid, s in raw_scores]
    # 不过滤零分文档：调用方可能需要对比 relevant vs irrelevant（含零分）
    raw_scores.sort(key=lambda x: x[1], reverse=True)
    return raw_scores[:top_k]


def _rrf_fusion(
    bm25_results: List[Tuple[str, float]],
    vector_results: List[Tuple[str, float]],
    fts_results: List[Tuple[str, float]],
    bm25_weight: float = 0.4,
    vector_weight: float = 0.4,
    fts_weight: float = 0.2,
    k: int = 60,
) -> List[Tuple[str, float]]:
    """RRF (Reciprocal Rank Fusion) 三路融合

    RRF(d) = Σ w_i / (k + r_i(d))，其中 r_i(d) 为 d 在第 i 路结果中的排名（从 1 起）。
    """
    all_ids = set(r[0] for r in bm25_results) | set(r[0] for r in vector_results) | set(r[0] for r in fts_results)
    fused: Dict[str, float] = {}
    for mid in all_ids:
        score = 0.0
        for results, weight in [
            (bm25_results, bm25_weight),
            (vector_results, vector_weight),
            (fts_results, fts_weight),
        ]:
            for rank, (rid, _) in enumerate(results, 1):
                if rid == mid:
                    score += weight / (k + rank)
                    break
        fused[mid] = score
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def _vector_search_impl(query: str, all_memories: List[Dict[str, Any]], top_k: int) -> List[Tuple[str, float]]:
    """向量路实现：SemanticSearch.compute_similarity"""
    ss = get_semantic_search()
    scored: List[Tuple[str, float]] = []
    for mem in all_memories:
        content = str(mem.get("content", ""))
        if not content:
            continue
        try:
            score = ss.compute_similarity(query, content)
        except Exception as e:
            logger.warning("compute_similarity 失败: %s", e)
            continue
        if score > 0:
            scored.append((str(mem.get("id", "")), float(score)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _fts_search_impl(query: str, all_memories: List[Dict[str, Any]], top_k: int) -> List[Tuple[str, float]]:
    """FTS 路：knowledge.search.full_text_search（P0-3 复活）。

    IDF 加权词覆盖评分，输出真实 [0,1] 分数；替换旧占位实现
    （search_by_keywords 无分数恒 0.0，且每次调用重建单例关键词索引有副作用）。
    """
    try:
        return _kb_full_text_search(query, all_memories, top_k)
    except Exception as e:
        logger.warning("FTS 全文搜索失败: %s", e)
        return []


def _mem_id_to_content_map(all_memories: List[Dict[str, Any]]) -> Dict[str, str]:
    """构建 id → content 映射"""
    return {str(m.get("id", "")): str(m.get("content", "")) for m in all_memories}


def _vector_search_knowledge(query: str, current_user: Dict[str, Any], top_k: int) -> List[Tuple[str, float]]:
    """知识语料的向量路：持久化索引（遗留修复 ②）。

    ensure_indexed 增量同步当前用户可见条目（重启零重算），
    余弦检索返回 (knowledge_id, score)。
    """
    from neurova.knowledge.repository import get_knowledge_repository
    from neurova.knowledge.vector_index import get_knowledge_vector_index

    idx = get_knowledge_vector_index()
    hits = idx.search(query, current_user, top_k=top_k, repo=get_knowledge_repository())
    return [(str(h["id"]), float(h["score"])) for h in hits]


def _build_rerank_runner(config: dict):
    """按请求配置装配 rerank runner（P0-3；显式装配，无全局态）。

    返回 (runner, method_label)：method="model" 但 provider 不可用时
    退化为加权融合，label 如实回 "weight"。
    """
    from neurova.knowledge.rerank import ModelRerankRunner, WeightRerankRunner

    method = (config.get("method") or "weight").strip().lower()
    weights = config.get("weights") or None

    if method == "model":
        provider_name = str(config.get("rerank_provider") or "").strip()
        provider = _resolve_rerank_provider(provider_name) if provider_name else None
        if provider is not None:
            return ModelRerankRunner(provider, fallback_weights=weights), "model"
        # 无可用 provider → 加权融合退化（多路分数明细仍在）
        logger.info("rerank: 无可用模型重排 provider，退化加权融合")
    return WeightRerankRunner(weights), "weight"


def _resolve_rerank_provider(name: str):
    """解析命名 rerank provider（扩展点：当前无内置实现，恒 None）。

    预留接入面：bge-reranker（本地 ONNX）/ cohere rerank API 等装配后
    在此注册，端点与管线代码无需再改。
    """
    return None


def _single_channel_results(scored, corpus, channel: str) -> List[Dict[str, Any]]:
    """单方法（semantic/full_text/keyword）的统一结果投影。"""
    id_to_content = _mem_id_to_content_map(corpus)
    id_to_title = {str(m.get("id", "")): str(m.get("title", "")) for m in corpus if m.get("title")}
    return [
        {
            "id": mid,
            "title": id_to_title.get(mid, ""),
            "content": id_to_content.get(mid, ""),
            "score": round(float(score), 6),
            "confidence_breakdown": {channel: round(float(score), 4)},
        }
        for mid, score in scored
    ]


@router.post("/hybrid")
async def hybrid_search(
    body: HybridSearchRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """混合搜索 - BM25 + 向量 + FTS 三路融合 (RRF算法)，支持 memory/knowledge 语料

    P0-3：retrieval_method 四态（semantic 只走向量 / full_text 只走词法 /
    keyword 纯子串 / hybrid 三路融合）；可选 rerank 出口重排 hybrid 结果。
    """
    features = _analyze_query_features(body.query)
    corpus = _load_corpus(body, request, current_user)

    try:
        retrieval_method = RetrievalMethod.from_str(body.retrieval_method)
    except ValueError:
        retrieval_method = RetrievalMethod.HYBRID_SEARCH
    is_knowledge = (getattr(body, "source", "memory") or "memory") == "knowledge"

    try:
        if retrieval_method == RetrievalMethod.SEMANTIC_SEARCH:
            if is_knowledge:
                vector_res = _vector_search_knowledge(body.query, current_user, top_k=body.top_k)
            else:
                vector_res = _vector_search_impl(body.query, corpus, top_k=body.top_k)
            results = _single_channel_results(vector_res, corpus, "vector")

        elif retrieval_method == RetrievalMethod.KEYWORD_SEARCH:
            from neurova.knowledge.search import keyword_search

            scored = keyword_search(body.query, corpus, top_k=body.top_k)
            results = _single_channel_results(scored, corpus, "keyword")

        elif retrieval_method == RetrievalMethod.FULL_TEXT_SEARCH:
            scored = _fts_search_impl(body.query, corpus, top_k=body.top_k)
            results = _single_channel_results(scored, corpus, "fts")

        else:  # HYBRID_SEARCH（默认）：三路 RRF + 可选 rerank
            bm25_res = _bm25_search(body.query, corpus, top_k=body.top_k * 2)
            if is_knowledge:
                vector_res = _vector_search_knowledge(body.query, current_user, top_k=body.top_k * 2)
            else:
                vector_res = _vector_search_impl(body.query, corpus, top_k=body.top_k * 2)
            fts_res = _fts_search_impl(body.query, corpus, top_k=body.top_k * 2)
            fused = _rrf_fusion(
                bm25_res,
                vector_res,
                fts_res,
                bm25_weight=body.bm25_weight,
                vector_weight=body.vector_weight,
                fts_weight=body.fts_weight,
            )
            id_to_content = _mem_id_to_content_map(corpus)
            id_to_title = {str(m.get("id", "")): str(m.get("title", "")) for m in corpus if m.get("title")}
            bm25_map = {mid: s for mid, s in bm25_res}
            vector_map = {mid: s for mid, s in vector_res}
            fts_map = {mid: s for mid, s in fts_res}
            results = []
            for mid, rrf_score in fused[: body.top_k]:
                results.append(
                    {
                        "id": mid,
                        "title": id_to_title.get(mid, ""),
                        "content": id_to_content.get(mid, ""),
                        "rrf_score": rrf_score,
                        "score": rrf_score,
                        "confidence_breakdown": {
                            "bm25": round(float(bm25_map.get(mid, 0.0)), 4),
                            "vector": round(float(vector_map.get(mid, 0.0)), 4),
                            "fts": round(float(fts_map.get(mid, 0.0)), 4),
                            "rrf": round(float(rrf_score), 6),
                        },
                    }
                )

            # rerank 出口（异常降级 rrf 原序，不阻断检索）
            if body.rerank and results:
                try:
                    runner, rerank_label = _build_rerank_runner(body.rerank)
                    candidates = [
                        {
                            "index": i,
                            "id": r["id"],
                            "content": r["content"],
                            "bm25": r["confidence_breakdown"]["bm25"],
                            "vector": r["confidence_breakdown"]["vector"],
                            "fts": r["confidence_breakdown"]["fts"],
                        }
                        for i, r in enumerate(results)
                    ]
                    reranked = runner.rerank(body.query, candidates)
                    results = [
                        {**results[rr["index"]],
                         "rerank_score": round(float(rr["score"]), 6),
                         "rerank_method": rerank_label}
                        for rr in reranked
                    ]
                except Exception as e:
                    logger.warning("hybrid rerank 失败（降级 rrf 原序）: %s", e)
    except Exception as e:
        logger.error("hybrid_search 融合失败: %s", e)
        results = []

    return {
        "code": 0,
        "message": "success",
        "data": {
            "query": body.query,
            "source": getattr(body, "source", "memory"),
            "retrieval_method": retrieval_method.value,
            "results": results,
            "total": len(results),
            "weights": {"bm25": body.bm25_weight, "vector": body.vector_weight, "fts": body.fts_weight},
            "features": features,
        },
    }


@router.post("/bm25")
async def bm25_search(
    body: HybridSearchRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """纯 BM25 搜索"""
    corpus = _load_corpus(body, request, current_user)

    try:
        scored = _bm25_search(body.query, corpus, top_k=body.top_k)
        id_to_content = _mem_id_to_content_map(corpus)
        results = [
            {"id": mid, "content": id_to_content.get(mid, ""), "score": score}
            for mid, score in scored
        ]
    except Exception as e:
        logger.error("bm25_search 失败: %s", e)
        results = []

    return {
        "code": 0,
        "message": "success",
        "data": {"query": body.query, "results": results, "total": len(results), "method": "bm25"},
    }


@router.post("/vector")
async def vector_search(
    body: HybridSearchRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """纯向量搜索"""
    corpus = _load_corpus(body, request, current_user)

    try:
        scored = _vector_search_impl(body.query, corpus, top_k=body.top_k)
        id_to_content = _mem_id_to_content_map(corpus)
        results = [
            {"id": mid, "content": id_to_content.get(mid, ""), "score": score}
            for mid, score in scored
        ]
    except Exception as e:
        logger.error("vector_search 失败: %s", e)
        results = []

    return {
        "code": 0,
        "message": "success",
        "data": {"query": body.query, "results": results, "total": len(results), "method": "vector"},
    }


@router.post("/compare")
async def compare_search(
    body: CompareRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """对比三种搜索方式的结果"""
    try:
        mgr = _get_runtime_memory_manager(request)
        all_memories = mgr.get_all_memories() or []
    except Exception as e:
        logger.warning("compare_search: 获取记忆失败: %s", e)
        all_memories = []

    try:
        bm25_scored = _bm25_search(body.query, all_memories, top_k=body.top_k)
        vector_scored = _vector_search_impl(body.query, all_memories, top_k=body.top_k)
        # compare 不依赖 FTS 路传空，避免重复计算
        hybrid_scored = _rrf_fusion(bm25_scored, vector_scored, [])
        id_to_content = _mem_id_to_content_map(all_memories)

        bm25_results = [
            {"id": mid, "content": id_to_content.get(mid, ""), "score": score}
            for mid, score in bm25_scored
        ]
        vector_results = [
            {"id": mid, "content": id_to_content.get(mid, ""), "score": score}
            for mid, score in vector_scored
        ]
        hybrid_results = [
            {"id": mid, "content": id_to_content.get(mid, ""), "rrf_score": score, "score": score}
            for mid, score in hybrid_scored[: body.top_k]
        ]
    except Exception as e:
        logger.error("compare_search 失败: %s", e)
        bm25_results = vector_results = hybrid_results = []

    return {
        "code": 0,
        "message": "success",
        "data": {
            "query": body.query,
            "bm25_results": bm25_results,
            "bm25_total": len(bm25_results),
            "vector_results": vector_results,
            "vector_total": len(vector_results),
            "hybrid_results": hybrid_results,
            "hybrid_total": len(hybrid_results),
        },
    }


@router.post("/analyze")
async def analyze_query(body: dict):
    """分析查询特征 - 评估三种搜索方式的预期表现"""
    query = body.get("query", "")
    features = _analyze_query_features(query)
    weights = _recommend_weights(features)
    suggestion = _get_suggestion(features)

    return {
        "code": 0,
        "message": "success",
        "data": {"query": query, "features": features, "recommended_weights": weights, "suggestion": suggestion},
    }
