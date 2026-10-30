"""知识混合检索服务。

落点：
chat 主路（KnowledgeRetrieverAdapter）此前只用 TF-IDF 分片索引（纯词法），
ONNX 向量索引只挂在 semantic-search 端点——两套索引互不相认。本模块把四路
（tfidf 分片 / bm25 / fts / vector 持久化索引）收进一个函数，rank-based
加权 RRF 融合，API 与 chat 共用单源。

纪律：
- tfidf 主路异常**上抛**——它是全链健康探针，吞掉会把"数据库坏了"伪装成
  "没有相关知识"；bm25/fts/vector 是补充视角，单路异常只记日志、该路置空。
- 可见性先行：语料取 repo.visible_items（scope 过滤后），vector 路按用户
  索引文件天然隔离 + 融合后回映可见集双保险——不可见条目不可能进结果。
- RRF 只消费秩不消费分数（各路分数域不同：tfidf/bm25 归一余弦、fts [0,1]、
  rrf 值域 ~[0,0.03]），与 semantic_search_api 已验证的融合语义一致。
- bm25_rank/rrf_fusion 同时是 semantic_search_api 的委托目标（单源，防
"""

from __future__ import annotations

import inspect
import math
import os
import time
from functools import wraps
from typing import Any, Dict, Iterable, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.knowledge.retrieval_metrics import get_retrieval_metrics
from neurova.knowledge.search import full_text_search
from neurova.knowledge.splitter import build_index_content

logger = get_logger(__name__)

# 四路缺省权重：词法两路（tfidf 字粒度分片 + bm25 词粒度）为主，# 语义 vector 次之，fts 覆盖式评分提供第三视角
DEFAULT_ROUTE_WEIGHTS = {
    "tfidf": 0.30, "bm25": 0.30, "vector": 0.25, "fts": 0.15, "graph": 0.0,
}
GRAPH_ROUTE_WEIGHT_ENV = "NEUROVA_KB_GRAPH_ROUTE_WEIGHT"
RRF_K = 60
# 大语料时辅助词法路的候选上限：主索引仍是全量；BM25/FTS 只在主索引
# 返回的候选上重排，避免 100k 语料每轮全量 tokenize。小语料不受影响。
DEFAULT_AUX_SCAN_LIMIT = 10_000
AUX_SCAN_LIMIT_ENV = "NEUROVA_KB_AUX_SCAN_LIMIT"
FTS_INDEX_ENV = "NEUROVA_KB_FTS_INDEX"
_FTS_OFF_VALUES = ("0", "false", "off", "no")

# vector_index 参数哨兵：_AUTO=取进程单例；None=显式关闭向量路
_AUTO = object()


def rrf_fusion(
    routes: Dict[str, List[Tuple[str, float]]],
    weights: Dict[str, float],
    k: int = RRF_K,
) -> List[Tuple[str, float]]:
    """加权 RRF：score(d) = Σ_route w_route / (k + rank_route(d))，rank 从 1 起。"""
    fused: Dict[str, float] = {}
    for route_name, results in routes.items():
        w = float(weights.get(route_name, 0.0))
        if w <= 0.0:
            continue
        for rank, (doc_id, _score) in enumerate(results, 1):
            fused[doc_id] = fused.get(doc_id, 0.0) + w / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def bm25_rank(
    query: str,
    corpus: List[Dict[str, Any]],
    top_k: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
) -> List[Tuple[str, float]]:
    """Okapi BM25（自 semantic_search_api 原样平移——分词走 knowledge.search.
    tokenize(jieba)，分数按最大原始分归一 [0,1]，不过滤零分文档）。"""
    from neurova.knowledge.search import tokenize as _tokenize

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
    raw_scores.sort(key=lambda x: x[1], reverse=True)
    return raw_scores[:top_k]


def _graphShadowReading(out: Any, boundArguments) -> Optional[Dict[str, Any]]:
    """影子读数（specs/2026-10-30 W3）：graph 候选与最终 top-k 的关系。

    rank 从 1 起；不改变返回值，纯读数。无候选返回 None（缺读数点名，不伪造 0）。
    """
    graphRanks = boundArguments.arguments.get("graphRanks")
    if not graphRanks:
        return None
    candidateIds = [str(entryId) for entryId, _score in graphRanks if entryId]
    if not candidateIds:
        return None
    outIds = [
        str(row.get("knowledge_id"))
        for row in out or [] if (row or {}).get("knowledge_id")
    ]
    topRank = None
    for entryId in candidateIds:
        if entryId in outIds:
            topRank = outIds.index(entryId) + 1
            break
    limit = boundArguments.arguments.get("limit") or 10
    topSet = set(outIds[: max(1, int(limit))])
    return {
        "candidates": len(candidateIds),
        "top_candidate_final_rank": topRank,
        "overlap_at_k": sum(1 for entryId in candidateIds if entryId in topSet),
    }


def _recordRetrieval(func):
    """记录成功/失败的检索读数；装饰器不改变返回值和异常传播。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        started = time.monotonic()
        try:
            out = func(*args, **kwargs)
        except Exception:
            get_retrieval_metrics().record(
                hits=0, elapsedMs=(time.monotonic() - started) * 1000, error=True
            )
            raise
        try:
            boundArguments = inspect.signature(func).bind(*args, **kwargs)
        except TypeError:
            boundArguments = None
        # 影子档 graphWeight=0：graph 候选仍在 breakdown 里（供诊断），但没参与融合，
        # 路计数把它算成命中就会让「on 才含 graph」恒真——路计数只认真参与融合的路。
        graphFused = bool(
            boundArguments is not None
            and float(boundArguments.arguments.get("graphWeight") or 0.0) > 0.0
        )
        route_counts: Dict[str, int] = {}
        for row in out or []:
            breakdown = (row or {}).get("confidence_breakdown") or {}
            routes = ("tfidf", "bm25", "fts", "vector") + (("graph",) if graphFused else ())
            for route in routes:
                if float(breakdown.get(route, 0.0) or 0.0) > 0.0:
                    route_counts[route] = route_counts.get(route, 0) + 1
        graphShadow = (
            _graphShadowReading(out, boundArguments) if boundArguments is not None else None
        )
        get_retrieval_metrics().record(
            hits=len(out or []),
            elapsedMs=(time.monotonic() - started) * 1000,
            routeCounts=route_counts,
            graphShadow=graphShadow,
        )
        return out

    return wrapper


@_recordRetrieval
def hybrid_search_knowledge(
    repo: Any,
    user: Optional[Dict[str, Any]],
    query: str,
    limit: int = 10,
    scope: str = "all",
    agent_id: Optional[str] = None,
    vector_index: Any = _AUTO,
    weights: Optional[Dict[str, float]] = None,
    k: int = RRF_K,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    source: Optional[str] = None,
    updated_after: Optional[float] = None,
    graphRanks: Optional[List[Tuple[str, float]]] = None,
    graphSupport: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    graphWeight: Optional[float] = None,
    geo_radius: Optional[Dict[str, Any]] = None,
    geo_bbox: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """四路 RRF 知识混合检索（可选图谱条目影子路由）。

    返回可见条目 dict 副本 + score（RRF 融合分）+ rrf_score 别名 +
    confidence_breakdown（{tfidf,bm25,fts,vector,rrf} 各路原始分/融合分），
    tfidf 路命中附带的 chunk_hits 一并透传。

    参数:
        repo: KnowledgeRepository（duck-typing：search_visible_items 必需，
            visible_items/vector 语料缺失时自动降级）
        vector_index: 显式注入向量索引（测试/禁用）；_AUTO=进程单例；None=关
    """
    user = user or {}
    if not query or not str(query).strip():
        return []

    route_scores: Dict[str, Dict[str, float]] = {
        "tfidf": {}, "bm25": {}, "fts": {}, "vector": {}, "graph": {},
    }
    if graphWeight is None:
        try:
            graphWeight = float(os.environ.get(GRAPH_ROUTE_WEIGHT_ENV, "0") or 0.0)
        except (TypeError, ValueError):
            graphWeight = 0.0
    if graphRanks:
        route_scores["graph"] = {
            str(entryId): float(score or 0.0)
            for entryId, score in graphRanks if entryId
        }

    # ── 可见语料（辅助路；构建失败该路置空，不影响主路）─────────────
    visible_map: Dict[str, Dict[str, Any]] = {}
    corpus: List[Dict[str, str]] = []
    try:
        for it in repo.visible_items(
            user, scope=scope, category=category, agent_id=agent_id,
            tags=tags, source=source, updated_after=updated_after,
            geo_radius=geo_radius, geo_bbox=geo_bbox,
        ):
            kid = str(it.get("knowledge_id", ""))
            if not kid or not isinstance(it, dict):
                continue
            visible_map[kid] = it
            corpus.append(
                {
                    "id": kid,
                    "content": build_index_content(
                        str(it.get("title", "")), str(it.get("content", ""))
                    ),
                }
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("知识 hybrid：可见语料构建失败（bm25/fts 路降级）: %s", e)

    # ── 主路：tfidf 分片索引（异常上抛，全链故障必须暴露）────────────
    # 大语料时把同一次检索的候选上限抬到 aux_cap，供 BM25/FTS 作为有界
    # 候选池；主路输出仍只取前 limit*2，保持既有 RRF 行为。
    try:
        aux_cap = max(int(os.environ.get(AUX_SCAN_LIMIT_ENV, DEFAULT_AUX_SCAN_LIMIT)), 1)
    except (TypeError, ValueError):
        aux_cap = DEFAULT_AUX_SCAN_LIMIT
    large_corpus = bool(corpus) and len(corpus) > aux_cap
    lexical_limit = max(limit * 2, 10)
    if large_corpus:
        lexical_limit = min(len(corpus), aux_cap)
    lexical_all = repo.search_visible_items(
        user=user, query=query, scope=scope, agent_id=agent_id,
        limit=lexical_limit, category=category, tags=tags,
        source=source, updated_after=updated_after,
        geo_radius=geo_radius, geo_bbox=geo_bbox,
    )
    if lexical_all is None:
        lexical_all = []
    lexical = lexical_all[: max(limit * 2, 10)]
    lexical_map: Dict[str, Dict[str, Any]] = {}
    for it in lexical:
        kid = str(it.get("knowledge_id", ""))
        if not kid:
            continue
        lexical_map[kid] = dict(it)
        route_scores["tfidf"][kid] = float(it.get("score", 0.0))

    if large_corpus:
        keep = {str(it.get("knowledge_id", "")) for it in lexical_all}
        before = len(corpus)
        corpus = [c for c in corpus if c["id"] in keep]
        logger.debug(
            "知识 hybrid：辅助路候选上限 %d，语料 %d→%d（主索引仍全量）",
            aux_cap, before, len(corpus),
        )

    used_fts = False
    if large_corpus and (
        os.environ.get(FTS_INDEX_ENV) or "on"
    ).strip().lower() not in _FTS_OFF_VALUES and hasattr(repo, "ftsSearch"):
        try:
            fts_hits = repo.ftsSearch(
                query, user, scope=scope, agent_id=agent_id, category=category,
                tags=tags, source=source, updated_after=updated_after,
                limit=max(limit * 2, 10),
            )
            for hit in fts_hits or []:
                kid = str(hit.get("id") or hit.get("knowledge_id") or "")
                if kid and kid in visible_map:
                    route_scores["bm25"][kid] = max(
                        float(hit.get("score", 0.0) or 0.0), 0.0
                    )
            used_fts = True
            logger.debug("知识 hybrid：大语料走 FTS5 倒排（%d 命中）", len(fts_hits or []))
        except Exception as e:  # noqa: BLE001
            logger.debug("知识 hybrid：FTS5 索引失败（回退内存词法路）: %s", e)

    if corpus and not used_fts:
        # 融合路只收正分命中：bm25_rank/full_text_search 保留零分文档是
        # API 对比视图的契约，但 RRF 按秩计分——零分"命中"给秩权重是纯噪声
        try:
            for doc_id, s in bm25_rank(query, corpus, top_k=max(limit * 2, 10)):
                if s > 0:
                    route_scores["bm25"][str(doc_id)] = float(s)
        except Exception as e:  # noqa: BLE001
            logger.debug("知识 hybrid：bm25 路失败（置空降级）: %s", e)
        try:
            for doc_id, s in full_text_search(query, corpus, top_k=max(limit * 2, 10)):
                if s > 0:
                    route_scores["fts"][str(doc_id)] = float(s)
        except Exception as e:  # noqa: BLE001
            logger.debug("知识 hybrid：fts 路失败（置空降级）: %s", e)

    # ── 向量路（持久化 ONNX 索引；引擎不可用/异常 → 置空降级）────────
    if vector_index is _AUTO:
        try:
            from neurova.knowledge.vector_index import get_knowledge_vector_index

            vector_index = get_knowledge_vector_index()
        except Exception as e:  # noqa: BLE001
            logger.debug("知识 hybrid：向量索引单例不可用（向量路降级）: %s", e)
            vector_index = None
    if vector_index is not None:
        try:
            for hit in vector_index.search(
                query, user, top_k=max(limit * 2, 10), repo=repo
            ):
                kid = str(hit.get("id", ""))
                if kid:
                    route_scores["vector"][kid] = float(hit.get("score", 0.0))
        except Exception as e:  # noqa: BLE001
            logger.debug("知识 hybrid：向量路失败（置空降级）: %s", e)

    # ── 融合与回映（双保险隔离：回映只认 tfidf/可见集）───────────────
    routes: Dict[str, List[Tuple[str, float]]] = {
        name: sorted(m.items(), key=lambda kv: kv[1], reverse=True)
        for name, m in route_scores.items()
    }
    effectiveWeights = dict(weights or DEFAULT_ROUTE_WEIGHTS)
    if graphWeight and graphWeight > 0:
        effectiveWeights["graph"] = float(graphWeight)
    else:
        effectiveWeights.pop("graph", None)
    routes["graph"] = [
        (entryId, score) for entryId, score in (graphRanks or [])
    ]
    fused = rrf_fusion(routes, effectiveWeights, k=k)

    # ── 末端精排（工单 014，灭 B05；关闸即取 RRF 前 limit 名，行为与接入前逐字一致）──
    from neurova.knowledge.rerank.main_path import (
        MainPathRerankConfig,
        refineMainPathResults,
    )

    rerankConfig = MainPathRerankConfig.fromEnv()
    take = max(1, int(limit)) * (max(rerankConfig.poolFactor, 1) if rerankConfig.enabled else 1)

    out: List[Dict[str, Any]] = []
    for kid, rrf in fused[: take]:
        item = lexical_map.get(kid)
        if item is None:
            item = visible_map.get(kid)
        if item is None:
            continue  # 不可见/已删除条目：任何路的命中都不回灌（隔离兜底）
        merged = dict(item)
        merged["score"] = rrf
        merged["rrf_score"] = rrf
        merged["confidence_breakdown"] = {
            "tfidf": round(route_scores["tfidf"].get(kid, 0.0), 4),
            "bm25": round(route_scores["bm25"].get(kid, 0.0), 4),
            "fts": round(route_scores["fts"].get(kid, 0.0), 4),
            "vector": round(route_scores["vector"].get(kid, 0.0), 4),
            "graph": round(route_scores.get("graph", {}).get(kid, 0.0), 4),
            "rrf": round(rrf, 6),
        }
        if graphSupport and kid in graphSupport:
            merged["graph_support"] = list(graphSupport[kid])
        out.append(merged)
    out, rerankNote = refineMainPathResults(query, out, limit=limit, config=rerankConfig)
    if rerankNote:
        logger.warning("知识 hybrid：末端精排降级 %s", rerankNote)
    return out
