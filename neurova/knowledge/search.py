"""知识检索策略层（P0-3 — Dify 对标）。

RetrievalMethod 四态（参照 Dify api/core/rag/retrieval_methods.py）：
数据源内的检索方法选择，与多库路由是分开的两层。

- full_text_search：IDF 加权词覆盖评分（真实 [0,1] 分数）——复活
  semantic_search_api 的 fts 路（旧实现分数恒 0 占位，见该文件
  _fts_search_impl 注释）
- keyword_search：查询词子串命中覆盖率（零分词依赖，关键词态）

与 BM25 的关系：BM25 是词频饱和的概率排序（bm25 通道），full_text 是
覆盖式评分（fts 通道）——两通道互补，RRF 融合时提供不同视角。
"""

from __future__ import annotations

import logging
import math
import re
from enum import Enum
from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 语义路支持集：向量类后端；词法路支持集：倒排/词频类后端
_VECTOR_BACKENDS = {"faiss", "onnx", "fastembed", "annoy", "hnswlib", "weaviate", "qdrant"}
_FULLTEXT_BACKENDS = {"tfidf", "bm25", "fts5", "fts", "keyword"}


def _normalize_backend(backend: str) -> str:
    return (backend or "").strip().lower().replace("-", "_")


class RetrievalMethod(str, Enum):
    """检索方法四态（枚举值对齐 Dify RetrievalMethod 命名）"""

    SEMANTIC_SEARCH = "semantic_search"
    FULL_TEXT_SEARCH = "full_text_search"
    HYBRID_SEARCH = "hybrid_search"
    KEYWORD_SEARCH = "keyword_search"

    @classmethod
    def from_str(cls, value: str) -> "RetrievalMethod":
        """宽松解析：大小写/连字符/空格不敏感，接受短别名（semantic/hybrid/...）"""
        v = _normalize_backend(value)
        aliases = {
            "semantic": cls.SEMANTIC_SEARCH,
            "full_text": cls.FULL_TEXT_SEARCH,
            "fulltext": cls.FULL_TEXT_SEARCH,
            "keyword": cls.KEYWORD_SEARCH,
            "hybrid": cls.HYBRID_SEARCH,
        }
        if v in aliases:
            return aliases[v]
        try:
            return cls(v)
        except ValueError:
            raise ValueError(
                f"未知检索方法: {value!r}（有效值: {[m.value for m in cls]} 或短别名）"
            )

    def is_support_semantic_search(self, backend: str) -> bool:
        """语义路能力位：按向量后端类型判定（词法路恒在，不受此限）"""
        return _normalize_backend(backend) in _VECTOR_BACKENDS

    def is_support_fulltext_search(self, backend: str) -> bool:
        """全文路能力位：按词法后端类型判定"""
        return _normalize_backend(backend) in _FULLTEXT_BACKENDS


def _ngram_tokenize(text: str) -> List[str]:
    """回退分词（jieba 不可用时）：英文按空格切分；中文提取 2-4 字连续片段。"""
    if not text:
        return []
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5\s]", " ", text.lower())
    tokens = cleaned.split()
    tokens.extend(re.findall(r"[\u4e00-\u9fa5]{2,4}", text))
    return [t for t in tokens if len(t) >= 2]


def _get_jieba() -> Any:
    """进程级惰性加载 jieba；不可用返回 None（调用方回退 n-gram）。

    缺席走 n-gram 是"失败方向"的弱化版（缺一个 jieba 维度的精度，不是检索坏掉），
    但**必须**留下 WARN 日志——否则升级 ABI / funasr 冲突卸载会让 FTS/BM25
    静默回退，监控盲。"""
    global _jieba
    if _jieba is not None:
        return _jieba if _jieba is not False else None
    try:
        import jieba as _j

        _j.setLogLevel(logging.WARNING)
        _jieba = _j
    except Exception as exc:  # noqa: BLE001 — 可选依赖，缺席走回退
        _jieba = False
        logger.warning(
            "知识库 jieba 不可用，FTS/BM25 静默回退 n-gram（中文检索精度降级）: %s", exc
        )
    return None if _jieba is False else _jieba


_jieba: Any = None


def tokenize(text: str) -> List[str]:
    """中英文分词（jieba 真分词优先，缺席回退 n-gram）：

    jieba 路径：中文按词级切分（"量子计算"→["量子","计算"]），英文按词；
    产出 <2 字符的 token 丢弃（单字噪声不进 IDF 统计）。
    """
    if not text:
        return []
    jieba = _get_jieba()
    if jieba is not None:
        cleaned = re.sub(r"[^\w\u4e00-\u9fa5\s]", " ", text.lower())
        tokens = []
        for seg in jieba.cut(cleaned):
            seg = seg.strip()
            # <2 字符的 token 丢弃（单字噪声不进 IDF 统计）
            if len(seg) >= 2:
                tokens.append(seg)
        return tokens
    return _ngram_tokenize(text)


def full_text_search(
    query: str,
    corpus: List[Dict[str, Any]],
    top_k: int = 10,
) -> List[Tuple[str, float]]:
    """FTS 路：IDF 加权词覆盖评分。

    score = Σ_{t∈query∩doc} idf(t) / Σ_{t∈query} idf(t) ∈ (0, 1]
    idf(t) = log(1 + N / (1 + df(t)))

    覆盖式评分与 BM25（词频饱和）互补；只返回 score>0 的文档
    （未命中不进 fts 路，融合层 breakdown 缺席即 0）。
    corpus 元素：{"id": str, "content": str, "title"?: str}
    """
    if not query or not corpus:
        return []
    query_terms = set(tokenize(query))
    if not query_terms:
        return []

    docs: List[Tuple[str, set]] = []
    df: Dict[str, int] = {}
    for doc in corpus:
        doc_id = str(doc.get("id", ""))
        tokens = set(tokenize(str(doc.get("content", ""))))
        if not doc_id or not tokens:
            continue
        docs.append((doc_id, tokens))
        for t in tokens:
            df[t] = df.get(t, 0) + 1
    if not docs:
        return []

    n = len(docs)
    idf = {t: math.log(1 + n / (1 + df.get(t, 0))) for t in query_terms}
    denom = sum(idf.values())
    if denom <= 0:
        return []

    scored: List[Tuple[str, float]] = []
    for doc_id, tokens in docs:
        hit = sum(idf[t] for t in query_terms if t in tokens)
        if hit > 0:
            scored.append((doc_id, hit / denom))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def keyword_search(
    query: str,
    corpus: List[Dict[str, Any]],
    top_k: int = 10,
) -> List[Tuple[str, float]]:
    """KEYWORD 态：查询词（分词片段）在 title+content 的子串命中率。

    score = 命中词数 / 查询词数 ∈ (0, 1]；纯 substring，无索引依赖。
    """
    if not query or not corpus:
        return []
    terms = set(tokenize(query))
    if not terms:
        return []
    scored: List[Tuple[str, float]] = []
    for doc in corpus:
        doc_id = str(doc.get("id", ""))
        if not doc_id:
            continue
        hay = (str(doc.get("title", "")) + "\n" + str(doc.get("content", ""))).lower()
        hits = sum(1 for t in terms if t in hay)
        if hits > 0:
            scored.append((doc_id, hits / len(terms)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
