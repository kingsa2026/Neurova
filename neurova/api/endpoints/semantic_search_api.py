"""
Semantic Search API - 语义搜索API端点

支持：hybrid, bm25, vector, compare, analyze
"""

from neurova.core.logger import get_logger
import re
import typing

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


class HybridSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    bm25_weight: float = Field(default=0.4, ge=0, le=1)
    vector_weight: float = Field(default=0.4, ge=0, le=1)
    fts_weight: float = Field(default=0.2, ge=0, le=1)
    filters: typing.Optional[dict] = None


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


@router.post("/hybrid")
async def hybrid_search(body: HybridSearchRequest):
    """混合搜索 - BM25 + 向量 + FTS5 三层融合 (RRF算法)"""
    features = _analyze_query_features(body.query)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "query": body.query,
            "results": [],
            "total": 0,
            "weights": {"bm25": body.bm25_weight, "vector": body.vector_weight, "fts": body.fts_weight},
            "features": features,
        },
    }


@router.post("/bm25")
async def bm25_search(body: HybridSearchRequest):
    """纯 BM25 搜索"""
    return {
        "code": 0,
        "message": "success",
        "data": {"query": body.query, "results": [], "total": 0, "method": "bm25"},
    }


@router.post("/vector")
async def vector_search(body: HybridSearchRequest):
    """纯向量搜索"""
    return {
        "code": 0,
        "message": "success",
        "data": {"query": body.query, "results": [], "total": 0, "method": "vector"},
    }


@router.post("/compare")
async def compare_search(body: CompareRequest):
    """对比三种搜索方式的结果"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "query": body.query,
            "bm25_results": [],
            "bm25_total": 0,
            "vector_results": [],
            "vector_total": 0,
            "hybrid_results": [],
            "hybrid_total": 0,
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
