"""
向量检索引擎 - 纯 Python 实现的 TF-IDF 语义搜索
支持索引持久化和缓存
"""

import collections
import datetime
import logging
import math
import os
import threading
import typing
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import pickle
import json

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    index: int = -1


@dataclass
class IndexStats:
    """索引统计"""
    total_documents: int
    total_tokens: int
    vocabulary_size: int
    average_document_length: float
    index_size_bytes: int


class VectorSearch:
    """
    向量检索引擎
    
    基于TF-IDF的语义搜索，支持：
    - 文档索引和检索
    - 索引持久化
    - 缓存优化
    - 增量更新
    """
    
    def __init__(
        self,
        index_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化向量检索引擎
        
        Args:
            index_path: 索引文件路径
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 索引路径
        self._index_path = index_path
        
        # 文档存储
        self._documents: List[Dict[str, Any]] = []
        self._document_ids: List[str] = []
        self._document_map: Dict[str, int] = {}
        
        # TF-IDF 索引
        self._tf: List[Dict[str, float]] = []  # 每个文档的TF
        self._idf: Dict[str, float] = {}  # 全局IDF
        self._vocabulary: Set[str] = set()
        self._document_freq: Dict[str, int] = {}  # 包含每个词的文档数
        
        # 缓存
        self._query_cache: Dict[str, List[SearchResult]] = {}
        self._cache_max_size = self._config.get("cache_max_size", 1000)
        self._cache_hits = 0
        self._cache_misses = 0
        
        # 配置
        self._max_features = self._config.get("max_features", 10000)
        self._min_df = self._config.get("min_df", 2)  # 最小文档频率
        self._max_df = self._config.get("max_df", 0.95)  # 最大文档频率比例
        self._stop_words = set(self._config.get("stop_words", []))
        
        # 统计
        self._total_queries = 0
        self._total_index_time = 0.0
        
        # 加载现有索引
        if self._index_path and os.path.exists(self._index_path):
            self._load_index()
        
        logger.info(f"VectorSearch initialized: {len(self._documents)} documents")
    
    @property
    def size(self) -> int:
        """文档数量"""
        return len(self._documents)
    
    def _load_index(self) -> bool:
        """
        加载索引
        
        Returns:
            是否加载成功
        """
        try:
            with open(self._index_path, 'rb') as f:
                data = pickle.load(f)
            
            self._documents = data.get('documents', [])
            self._document_ids = data.get('document_ids', [])
            self._document_map = data.get('document_map', {})
            self._tf = data.get('tf', [])
            self._idf = data.get('idf', {})
            self._vocabulary = data.get('vocabulary', set())
            self._document_freq = data.get('document_freq', {})
            
            logger.info(f"Index loaded: {len(self._documents)} documents")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to load index: {e}")
            return False
    
    def save_index(self) -> bool:
        """
        保存索引
        
        Returns:
            是否保存成功
        """
        if not self._index_path:
            logger.warning("No index path specified")
            return False
        
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
            
            data = {
                'documents': self._documents,
                'document_ids': self._document_ids,
                'document_map': self._document_map,
                'tf': self._tf,
                'idf': self._idf,
                'vocabulary': self._vocabulary,
                'document_freq': self._document_freq,
                'saved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            
            with open(self._index_path, 'wb') as f:
                pickle.dump(data, f)
            
            logger.info(f"Index saved: {len(self._documents)} documents")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save index: {e}")
            return False
    
    def _tokenize(self, text: str) -> List[str]:
        """
        分词
        
        Args:
            text: 输入文本
            
        Returns:
            词列表
        """
        import re
        
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
    
    def _compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        """
        计算词频（TF）
        
        Args:
            tokens: 词列表
            
        Returns:
            TF字典
        """
        if not tokens:
            return {}
        
        counter = Counter(tokens)
        total = len(tokens)
        
        # 归一化
        tf = {token: count / total for token, count in counter.items()}
        
        return tf
    
    def _compute_idf(self) -> None:
        """计算逆文档频率（IDF）"""
        n = len(self._documents)
        if n == 0:
            self._idf = {}
            return
        
        # 计算IDF
        self._idf = {}
        for token, freq in self._document_freq.items():
            # 使用平滑IDF
            self._idf[token] = math.log((n + 1) / (freq + 1)) + 1
    
    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """
        添加多个文本
        
        Args:
            texts: 文本列表
            metadatas: 元数据列表
            ids: ID列表
            
        Returns:
            添加的文档ID列表
        """
        if not texts:
            return []
        
        # 生成ID
        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in range(len(texts))]
        
        # 确保元数据列表长度匹配
        if metadatas is None:
            metadatas = [{} for _ in range(len(texts))]
        
        added_ids = []
        
        for i, (text, metadata, doc_id) in enumerate(zip(texts, metadatas, ids)):
            if self.add_text(text, metadata, doc_id):
                added_ids.append(doc_id)
        
        # 重建IDF
        self._compute_idf()
        
        # 清空查询缓存
        self._query_cache.clear()
        
        logger.info(f"Added {len(added_ids)} documents")
        return added_ids
    
    def add_text(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None,
    ) -> bool:
        """
        添加单个文本
        
        Args:
            text: 文本内容
            metadata: 元数据
            doc_id: 文档ID
            
        Returns:
            是否添加成功
        """
        with self._lock:
            # 生成ID
            if doc_id is None:
                import uuid
                doc_id = str(uuid.uuid4())
            
            # 检查是否已存在
            if doc_id in self._document_map:
                logger.warning(f"Document {doc_id} already exists, skipping")
                return False
            
            # 分词
            tokens = self._tokenize(text)
            
            # 计算TF
            tf = self._compute_tf(tokens)
            
            # 更新文档频率
            for token in set(tokens):
                self._document_freq[token] = self._document_freq.get(token, 0) + 1
            
            # 更新词汇表
            self._vocabulary.update(tokens)
            
            # 存储文档
            index = len(self._documents)
            self._documents.append({
                'id': doc_id,
                'text': text,
                'metadata': metadata or {},
                'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            self._document_ids.append(doc_id)
            self._document_map[doc_id] = index
            self._tf.append(tf)
            
            return True
    
    def rebuild_index(self) -> None:
        """重建索引"""
        with self._lock:
            # 重新计算所有TF
            self._tf = []
            self._document_freq.clear()
            self._vocabulary.clear()
            
            for doc in self._documents:
                text = doc.get('text', '')
                tokens = self._tokenize(text)
                tf = self._compute_tf(tokens)
                self._tf.append(tf)
                
                # 更新文档频率
                for token in set(tokens):
                    self._document_freq[token] = self._document_freq.get(token, 0) + 1
                
                # 更新词汇表
                self._vocabulary.update(tokens)
            
            # 重新计算IDF
            self._compute_idf()
            
            # 清空缓存
            self._query_cache.clear()
            
            logger.info(f"Index rebuilt: {len(self._documents)} documents")
    
    def _cosine_similarity(
        self,
        vec1: Dict[str, float],
        vec2: Dict[str, float],
    ) -> float:
        """
        计算余弦相似度
        
        Args:
            vec1: 向量1
            vec2: 向量2
            
        Returns:
            相似度分数 (0-1)
        """
        # 获取所有键
        all_keys = set(vec1.keys()) | set(vec2.keys())
        
        if not all_keys:
            return 0.0
        
        # 计算点积和范数
        dot_product = 0.0
        norm1 = 0.0
        norm2 = 0.0
        
        for key in all_keys:
            v1 = vec1.get(key, 0.0)
            v2 = vec2.get(key, 0.0)
            
            dot_product += v1 * v2
            norm1 += v1 * v1
            norm2 += v2 * v2
        
        # 避免除零
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        
        return dot_product / (math.sqrt(norm1) * math.sqrt(norm2))
    
    def search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.0,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        搜索相似文档
        
        Args:
            query: 查询文本
            limit: 返回结果数量限制
            threshold: 相似度阈值
            metadata_filter: 元数据过滤器
            
        Returns:
            搜索结果列表
        """
        with self._lock:
            self._total_queries += 1
            
            # 检查缓存
            cache_key = f"{query}:{limit}:{threshold}:{json.dumps(metadata_filter or {}, sort_keys=True)}"
            if cache_key in self._query_cache:
                self._cache_hits += 1
                return self._query_cache[cache_key]
            
            self._cache_misses += 1
            
            # 查询分词
            query_tokens = self._tokenize(query)
            if not query_tokens:
                return []
            
            # 计算查询TF-IDF
            query_tf = self._compute_tf(query_tokens)
            query_tfidf = {}
            for token, tf_value in query_tf.items():
                idf_value = self._idf.get(token, 1.0)
                query_tfidf[token] = tf_value * idf_value
            
            # 计算相似度
            results = []
            for i, doc in enumerate(self._documents):
                # 应用元数据过滤器
                if metadata_filter:
                    doc_metadata = doc.get('metadata', {})
                    match = True
                    for key, value in metadata_filter.items():
                        if doc_metadata.get(key) != value:
                            match = False
                            break
                    if not match:
                        continue
                
                # 计算文档TF-IDF
                doc_tf = self._tf[i]
                doc_tfidf = {}
                for token, tf_value in doc_tf.items():
                    idf_value = self._idf.get(token, 1.0)
                    doc_tfidf[token] = tf_value * idf_value
                
                # 计算相似度
                similarity = self._cosine_similarity(query_tfidf, doc_tfidf)
                
                if similarity >= threshold:
                    results.append(SearchResult(
                        text=doc.get('text', ''),
                        score=similarity,
                        metadata=doc.get('metadata', {}),
                        index=i,
                    ))
            
            # 按相似度排序
            results.sort(key=lambda x: x.score, reverse=True)
            
            # 限制结果数量
            results = results[:limit]
            
            # 更新缓存
            if len(self._query_cache) >= self._cache_max_size:
                # 清空最旧的缓存
                self._query_cache.clear()
            self._query_cache[cache_key] = results
            
            return results
    
    def remove_text(self, doc_id: str) -> bool:
        """
        删除文档
        
        Args:
            doc_id: 文档ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            if doc_id not in self._document_map:
                return False
            
            index = self._document_map[doc_id]
            
            # 获取文档tokens
            doc_tf = self._tf[index]
            tokens = set(doc_tf.keys())
            
            # 更新文档频率
            for token in tokens:
                if token in self._document_freq:
                    self._document_freq[token] -= 1
                    if self._document_freq[token] <= 0:
                        del self._document_freq[token]
            
            # 删除文档
            self._documents.pop(index)
            self._document_ids.pop(index)
            self._tf.pop(index)
            
            # 更新映射
            del self._document_map[doc_id]
            for i in range(index, len(self._documents)):
                old_id = self._document_ids[i]
                self._document_map[old_id] = i
            
            # 重建IDF
            self._compute_idf()
            
            # 清空缓存
            self._query_cache.clear()
            
            return True
    
    def clear(self) -> None:
        """清空索引"""
        with self._lock:
            self._documents.clear()
            self._document_ids.clear()
            self._document_map.clear()
            self._tf.clear()
            self._idf.clear()
            self._vocabulary.clear()
            self._document_freq.clear()
            self._query_cache.clear()
            
            logger.info("Index cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取索引统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            # 计算平均文档长度
            total_length = sum(len(doc.get('text', '')) for doc in self._documents)
            avg_length = total_length / len(self._documents) if self._documents else 0
            
            # 计算索引大小
            index_size = 0
            if self._index_path and os.path.exists(self._index_path):
                index_size = os.path.getsize(self._index_path)
            
            return {
                "total_documents": len(self._documents),
                "total_tokens": sum(len(tf) for tf in self._tf),
                "vocabulary_size": len(self._vocabulary),
                "average_document_length": round(avg_length, 2),
                "index_size_bytes": index_size,
                "total_queries": self._total_queries,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "cache_hit_rate": self._cache_hits / max(self._total_queries, 1),
                "cache_size": len(self._query_cache),
                "max_features": self._max_features,
                "min_df": self._min_df,
                "max_df": self._max_df,
            }
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        获取文档
        
        Args:
            doc_id: 文档ID
            
        Returns:
            文档数据，如果不存在返回None
        """
        with self._lock:
            if doc_id not in self._document_map:
                return None
            
            index = self._document_map[doc_id]
            return self._documents[index].copy()
    
    def get_documents(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        获取文档列表
        
        Args:
            limit: 数量限制
            offset: 偏移量
            
        Returns:
            文档列表
        """
        with self._lock:
            return self._documents[offset:offset+limit]
    
    def update_document(
        self,
        doc_id: str,
        text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        更新文档
        
        Args:
            doc_id: 文档ID
            text: 新文本
            metadata: 新元数据
            
        Returns:
            是否更新成功
        """
        with self._lock:
            if doc_id not in self._document_map:
                return False
            
            index = self._document_map[doc_id]
            doc = self._documents[index]
            
            # 更新文本
            if text is not None:
                # 删除旧索引
                old_tf = self._tf[index]
                for token in old_tf.keys():
                    if token in self._document_freq:
                        self._document_freq[token] -= 1
                        if self._document_freq[token] <= 0:
                            del self._document_freq[token]
                
                # 添加新索引
                tokens = self._tokenize(text)
                new_tf = self._compute_tf(tokens)
                self._tf[index] = new_tf
                
                for token in set(tokens):
                    self._document_freq[token] = self._document_freq.get(token, 0) + 1
                
                self._vocabulary.update(tokens)
                
                doc['text'] = text
            
            # 更新元数据
            if metadata is not None:
                doc['metadata'].update(metadata)
            
            # 更新时间
            doc['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            # 重建IDF
            self._compute_idf()
            
            # 清空缓存
            self._query_cache.clear()
            
            return True
    
    def __del__(self):
        """析构函数，确保索引保存"""
        try:
            if self._index_path:
                self.save_index()
        except Exception:
            pass


# 全局单例
_vector_search: Optional[VectorSearch] = None
_search_lock = threading.Lock()


def get_vector_search(
    index_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> VectorSearch:
    """
    获取全局向量检索引擎单例
    
    Args:
        index_path: 索引文件路径
        config: 配置字典
        
    Returns:
        VectorSearch实例
    """
    global _vector_search
    if _vector_search is None:
        with _search_lock:
            if _vector_search is None:
                _vector_search = VectorSearch(
                    index_path=index_path,
                    config=config,
                )
    return _vector_search


def reset_vector_search() -> None:
    """重置全局向量检索引擎（用于测试）"""
    global _vector_search
    with _search_lock:
        if _vector_search:
            try:
                _vector_search.save_index()
            except Exception:
                pass
        _vector_search = None