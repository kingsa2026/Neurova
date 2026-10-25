"""知识检索策略层。

RetrievalMethod 四态：
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
import threading
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
    """检索方法四态"""

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


#: 取用 jieba 的**唯一入口**（全仓）。jieba 的冷启动（`initialize()` 建前缀字典）
#: 实测 0.5–0.8s，在 CI 那种多格并行的场子里被 GIL 争抢放大到 8s 以上（实测 8.1s 构建
#: 字典 + 8.65s 首调），足以把一条 30s 的用例墙撞穿——`test_service_closed_loop` 三格就
#: 这么在 CI 红过。故本入口在第一次取用时**当场把字典建好**，把成本收在调用方手里。
#:
#: 在此之前全仓有两份各调各的取用口：本模块的 `_get_jieba()` 与
#: `neurova/evolution/eval/constraints._token_jaccard()` 里那句裸 `import jieba`。
#: 前者只 `import`（字典仍是懒建），后者连 import 都不缓存——两处都能在"用例跑着跑着"
#: 触发一次冷启动，谁也说不清那次抖动是谁付的账。按教义第 6/7 条收口到这里一份。
_JIEBA_LOAD_LOCK = threading.RLock()
_jieba: Any = None


def isJiebaWarm() -> bool:
    """进程内的 jieba 字典是否已建完（`False` = 未建/不可用）。

    为什么需要这个口：`jieba.initialize()` 是**进程级一次性**冷启动——首次切词时在
    调用方栈上同步建字典（CI runner 上实测把一格 30s 的判据撑到超时，而且红的位置在
    建字典、不在被测逻辑）。已经有调用方在进程起手做暖机；没有这个口的话，那件事只能
    靠"谁记得先 import 一次"来保证，谁也不知道自己是不是第一个。
    """
    return _jieba not in (None, False)


def warmJieba() -> bool:
    """把字典**提前**建起来，返回是否可用（已在则直接返回，幂等）。

    为什么必须有一个"提前付"的口，而不只留 `_get_jieba()`：DCL 解决的是"谁来建"，
    解决不了"什么时候建"。首次取用就地建字典，成本就落在**首调方**的关键路径上，
    而首调方是随机的。本机实测这笔成本对负载极度敏感（同一棵树）：

    ```
    空载首次 _get_jieba():                    0.56s
    3 条抢 GIL 的线程并发时首次 _get_jieba():  92.30s     ← 30s 格墙的 3 倍
    预热之后再取用:                            0.001s
    ```

    CI 的受保护子集正是"7953 格同进程 + `--cov` 插桩 + 多档并发"的场子。构建
    `cnb-sq6-1k5q1kqrc#003` 里 7953 格全绿、唯一那条红是
    `test_service_closed_loop::test_accept_produces_pending_proposal` 撞 30s 墙，
    栈底停在 `_get_jieba() → _j.initialize() → gen_pfdict`：它是那场子里第一个切中文的
    用例，替所有人付了这笔账。这正是台账 §6-408 那一族（冷启动＋抢 GIL）在取用口上的
    残留——上一轮只把成本**收口**到一处，没有让它**提前**付。

    两处消费方（都在前提侧，不在被测代码里）：`tests/conftest.py` 的
    `pytest_configure`（会话装配期）与需要显式暖机的脚本。失败按不可用记下、不抛。
    """
    return _get_jieba() is not None


def _get_jieba() -> Any:
    """进程级惰性加载 jieba；不可用返回 None（调用方回退 n-gram）。

    缺席走 n-gram 是"失败方向"的弱化版（缺一个 jieba 维度的精度，不是检索坏掉），
    但**必须**留下 WARN 日志——否则升级 ABI / funasr 冲突卸载会让 FTS/BM25
    静默回退，监控盲。

    双检锁 + 首次即建字典（见上面 `_JIEBA_LOAD_LOCK` 那段）：并发的第二个调用方等第一个
    建完再返回，不会各自 `initialize()` 一次；建失败的按 `False` 记下来，不反复重试。
    """
    global _jieba
    if _jieba is not None:
        return _jieba if _jieba is not False else None
    with _JIEBA_LOAD_LOCK:
        if _jieba is not None:
            return _jieba if _jieba is not False else None
        try:
            import jieba as _j

            _j.setLogLevel(logging.WARNING)
            # 字典在这里一次建完：调用方拿到的就是"可直接切"的实例，
            # 不会在后续某条无关键上付这笔冷启动。
            _j.initialize()
            _jieba = _j
        except Exception as exc:  # noqa: BLE001 — 可选依赖，缺席走回退
            _jieba = False
            logger.warning(
                "知识库 jieba 不可用，FTS/BM25 静默回退 n-gram（中文检索精度降级）: %s", exc
            )
    return None if _jieba is False else _jieba


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
