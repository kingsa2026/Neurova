"""
BM25 排序算法 - 概率相关性排序模型

BM25 是信息检索领域的经典排序算法，综合考虑了词频(TF)、逆文档频率(IDF)
和文档长度归一化，计算词项与文档的相关性分数。

公式：
  score(D, Q) = Σ IDF(qi) × (f(qi,D) × (k1 + 1)) / (f(qi,D) + k1 × (1 - b + b × |D|/avgdl))

  其中:
  - IDF(qi) = ln((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
  - f(qi,D) = 词项 qi 在文档 D 中的词频
  - |D| = 文档 D 的长度（词数）
  - avgdl = 文档集合的平均长度
  - k1 = 词频饱和参数（通常 1.2-2.0）
  - b = 长度归一化参数（通常 0.75）
"""

import collections
import logging
import math
import re
import threading
import typing
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass
class BM25Result:
    """BM25 搜索结果"""
    doc_id: str
    score: float
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BM25Scorer:
    """
    BM25 评分器
    
    实现 BM25 概率相关性排序算法，支持：
    - 文档索引和检索
    - 参数调优（k1, b）
    - 增量更新
    """
    
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化 BM25 评分器
        
        Args:
            k1: 词频饱和参数（通常 1.2-2.0）
            b: 长度归一化参数（通常 0.75）
            config: 配置字典
        """
        self._k1 = k1
        self._b = b
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 文档存储
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._doc_lengths: Dict[str, int] = {}
        self._doc_count = 0
        self._avg_doc_length = 0.0
        
        # 词频统计
        self._term_freq: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._doc_freq: Dict[str, int] = defaultdict(int)
        self._vocabulary: Set[str] = set()
        
        # 停用词
        self._stop_words: Set[str] = set(self._config.get("stop_words", []))
        
        # 统计
        self._total_queries = 0
        self._total_index_time = 0.0
        
        logger.info(f"BM25Scorer initialized: k1={k1}, b={b}")
    
    def _tokenize(self, text: str) -> List[str]:
        """
        分词
        
        Args:
            text: 输入文本
            
        Returns:
            词列表
        """
        # 转换为小写
        text = text.lower()
        
        # 提取单词
        tokens = re.findall(r'\b\w+\b', text)
        
        # 过滤停用词和短词
        tokens = [
            token for token in tokens
            if token not in self._stop_words and len(token) > 1
        ]
        
        return tokens
    
    def fit(self, documents: List[Dict[str, Any]]) -> None:
        """
        拟合文档集合
        
        Args:
            documents: 文档列表，每个文档包含 'id', 'content', 'metadata' 等字段
        """
        with self._lock:
            import time
            start_time = time.time()
            
            # 清空现有索引
            self._documents.clear()
            self._doc_lengths.clear()
            self._term_freq.clear()
            self._doc_freq.clear()
            self._vocabulary.clear()
            
            # 索引文档
            for doc in documents:
                doc_id = doc.get('id', '')
                content = doc.get('content', '')
                
                if not doc_id or not content:
                    continue
                
                # 存储文档
                self._documents[doc_id] = doc
                
                # 分词
                tokens = self._tokenize(content)
                self._doc_lengths[doc_id] = len(tokens)
                
                # 统计词频
                term_counts = Counter(tokens)
                for term, count in term_counts.items():
                    self._term_freq[term][doc_id] = count
                    self._doc_freq[term] += 1
                    self._vocabulary.add(term)
            
            # 更新统计
            self._doc_count = len(self._documents)
            if self._doc_count > 0:
                self._avg_doc_length = sum(self._doc_lengths.values()) / self._doc_count
            else:
                self._avg_doc_length = 0.0
            
            self._total_index_time += time.time() - start_time
            
            logger.info(f"BM25 fitted: {self._doc_count} documents, {len(self._vocabulary)} terms")
    
    def get_scores(self, query: str) -> Dict[str, float]:
        """
        获取查询对所有文档的 BM25 分数
        
        Args:
            query: 查询文本
            
        Returns:
            文档ID到分数的映射
        """
        with self._lock:
            self._total_queries += 1
            
            # 查询分词
            query_tokens = self._tokenize(query)
            if not query_tokens:
                return {}
            
            # 计算每个文档的分数
            scores: Dict[str, float] = {}
            
            for doc_id in self._documents:
                score = self._score_document(doc_id, query_tokens)
                if score > 0:
                    scores[doc_id] = score
            
            return scores
    
    def score(self, query: str, doc_id: str) -> float:
        """
        计算查询与单个文档的 BM25 分数
        
        Args:
            query: 查询文本
            doc_id: 文档ID
            
        Returns:
            BM25 分数
        """
        with self._lock:
            if doc_id not in self._documents:
                return 0.0
            
            query_tokens = self._tokenize(query)
            if not query_tokens:
                return 0.0
            
            return self._score_document(doc_id, query_tokens)
    
    def _score_document(self, doc_id: str, query_tokens: List[str]) -> float:
        """
        计算文档的 BM25 分数
        
        Args:
            doc_id: 文档ID
            query_tokens: 查询词列表
            
        Returns:
            BM25 分数
        """
        if doc_id not in self._documents:
            return 0.0
        
        doc_length = self._doc_lengths.get(doc_id, 0)
        if doc_length == 0:
            return 0.0
        
        score = 0.0
        
        for term in query_tokens:
            if term not in self._vocabulary:
                continue
            
            # 获取词项在文档中的频率
            tf = self._term_freq.get(term, {}).get(doc_id, 0)
            if tf == 0:
                continue
            
            # 计算 IDF
            n = self._doc_freq.get(term, 0)
            idf = math.log((self._doc_count - n + 0.5) / (n + 0.5) + 1)
            
            # 计算 TF 归一化
            tf_normalized = (tf * (self._k1 + 1)) / (
                tf + self._k1 * (1 - self._b + self._b * doc_length / self._avg_doc_length)
            )
            
            # 累加分数
            score += idf * tf_normalized
        
        return score
    
    def search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> List[BM25Result]:
        """
        搜索文档
        
        Args:
            query: 查询文本
            limit: 返回结果数量限制
            threshold: 分数阈值
            
        Returns:
            搜索结果列表
        """
        # 获取所有文档分数
        scores = self.get_scores(query)
        
        # 过滤和排序
        results = []
        for doc_id, score in scores.items():
            if score >= threshold:
                doc = self._documents.get(doc_id, {})
                results.append(BM25Result(
                    doc_id=doc_id,
                    score=score,
                    content=doc.get('content', ''),
                    metadata=doc.get('metadata', {}),
                ))
        
        # 按分数排序
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 限制结果数量
        return results[:limit]
    
    def remove(self, doc_id: str) -> bool:
        """
        移除文档
        
        Args:
            doc_id: 文档ID
            
        Returns:
            是否移除成功
        """
        with self._lock:
            if doc_id not in self._documents:
                return False
            
            # 获取文档信息
            doc_length = self._doc_lengths.get(doc_id, 0)
            
            # 更新词频统计
            for term in self._vocabulary:
                if doc_id in self._term_freq.get(term, {}):
                    tf = self._term_freq[term][doc_id]
                    del self._term_freq[term][doc_id]
                    self._doc_freq[term] -= 1
                    if self._doc_freq[term] <= 0:
                        del self._doc_freq[term]
                        self._vocabulary.discard(term)
            
            # 删除文档
            del self._documents[doc_id]
            del self._doc_lengths[doc_id]
            
            # 更新统计
            self._doc_count = len(self._documents)
            if self._doc_count > 0:
                self._avg_doc_length = sum(self._doc_lengths.values()) / self._doc_count
            else:
                self._avg_doc_length = 0.0
            
            return True
    
    def clear(self) -> None:
        """清空索引"""
        with self._lock:
            self._documents.clear()
            self._doc_lengths.clear()
            self._term_freq.clear()
            self._doc_freq.clear()
            self._vocabulary.clear()
            self._doc_count = 0
            self._avg_doc_length = 0.0
            
            logger.info("BM25 index cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "document_count": self._doc_count,
                "vocabulary_size": len(self._vocabulary),
                "average_document_length": round(self._avg_doc_length, 2),
                "k1": self._k1,
                "b": self._b,
                "total_queries": self._total_queries,
                "total_index_time": round(self._total_index_time, 3),
                "stop_words_count": len(self._stop_words),
            }


class Bm25Index:
    """
    BM25 索引
    
    封装 BM25Scorer，提供更高级的索引管理功能
    """
    
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化 BM25 索引
        
        Args:
            k1: 词频饱和参数
            b: 长度归一化参数
            config: 配置字典
        """
        self._scorer = BM25Scorer(k1=k1, b=b, config=config)
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        
        logger.info("Bm25Index initialized")
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> int:
        """
        添加文档
        
        Args:
            documents: 文档列表
            
        Returns:
            添加的文档数量
        """
        with self._lock:
            added_count = 0
            
            for doc in documents:
                doc_id = doc.get('id', '')
                if doc_id and doc_id not in self._documents:
                    self._documents[doc_id] = doc
                    added_count += 1
            
            # 重建索引
            if added_count > 0:
                self._scorer.fit(list(self._documents.values()))
            
            return added_count
    
    def search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> List[BM25Result]:
        """
        搜索文档
        
        Args:
            query: 查询文本
            limit: 返回结果数量限制
            threshold: 分数阈值
            
        Returns:
            搜索结果列表
        """
        return self._scorer.search(query, limit=limit, threshold=threshold)
    
    def remove(self, doc_id: str) -> bool:
        """
        移除文档
        
        Args:
            doc_id: 文档ID
            
        Returns:
            是否移除成功
        """
        with self._lock:
            if doc_id in self._documents:
                del self._documents[doc_id]
                self._scorer.fit(list(self._documents.values()))
                return True
            return False
    
    def _rebuild(self) -> None:
        """重建索引"""
        with self._lock:
            self._scorer.fit(list(self._documents.values()))
    
    def clear(self) -> None:
        """清空索引"""
        with self._lock:
            self._documents.clear()
            self._scorer.clear()
    
    def size(self) -> int:
        """获取文档数量"""
        return len(self._documents)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        stats = self._scorer.get_stats()
        stats["index_document_count"] = len(self._documents)
        return stats


# 全局单例
_bm25_index: Optional[Bm25Index] = None
_bm25_lock = threading.Lock()


def get_bm25_index(
    k1: float = 1.5,
    b: float = 0.75,
    config: Optional[Dict[str, Any]] = None,
) -> Bm25Index:
    """
    获取全局 BM25 索引单例
    
    Args:
        k1: 词频饱和参数
        b: 长度归一化参数
        config: 配置字典
        
    Returns:
        Bm25Index实例
    """
    global _bm25_index
    if _bm25_index is None:
        with _bm25_lock:
            if _bm25_index is None:
                _bm25_index = Bm25Index(k1=k1, b=b, config=config)
    return _bm25_index


def reset_bm25_index() -> None:
    """重置全局 BM25 索引（用于测试）"""
    global _bm25_index
    with _bm25_lock:
        if _bm25_index:
            _bm25_index.clear()
        _bm25_index = None