"""
检索上下文注入 - 语义理解增强、混合检索策略、上下文构建优化
支持结果缓存和向量索引复用
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContextInjector:
    """
    上下文注入器
    
    提供检索上下文注入功能：
    - 语义理解增强
    - 混合检索策略（关键词+向量）
    - 上下文构建优化
    - 结果缓存
    - 向量索引复用
    """
    
    def __init__(
        self,
        memory_manager: Any = None,
        vector_search: Any = None,
        max_context_tokens: int = 4000,
        cache_ttl: int = 300,
    ):
        """初始化上下文注入器
        
        Args:
            memory_manager: 记忆管理器
            vector_search: 向量搜索引擎
            max_context_tokens: 最大上下文token数
            cache_ttl: 缓存有效期（秒）
        """
        self._memory_manager = memory_manager
        self._vector_search = vector_search
        self._max_context_tokens = max_context_tokens
        self._cache_ttl = cache_ttl
        
        # 缓存
        self._context_cache: Dict[str, Tuple[Any, float]] = {}
        self._query_cache: Dict[str, Tuple[Any, float]] = {}
        
        # 向量索引
        self._vector_index = None
        self._index_last_build = 0.0
        self._index_build_interval = 3600  # 索引重建间隔（秒）
        
        # 统计信息
        self._stats = {
            "total_context_builds": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "keyword_searches": 0,
            "vector_searches": 0,
            "hybrid_searches": 0,
        }
        
        # 线程安全
        self._lock = threading.RLock()
        
        logger.info("ContextInjector 初始化完成")
    
    def _get_vector_search(self) -> Optional[Any]:
        """获取向量搜索引擎
        
        Returns:
            向量搜索引擎实例
        """
        if self._vector_search is None:
            try:
                # 尝试创建默认向量搜索
                from neurova.cognitive_layers.memory_layer.vector_search_advanced import create_vector_search
                self._vector_search = create_vector_search(backend="auto")
                logger.info("创建默认向量搜索引擎")
            except Exception as e:
                logger.warning(f"无法创建向量搜索引擎: {e}")
        
        return self._vector_search
    
    def _rebuild_vector_index(self, memories: List[Any]) -> None:
        """重建向量索引
        
        Args:
            memories: 记忆列表
        """
        try:
            vector_search = self._get_vector_search()
            if vector_search is None:
                return
            
            # 提取记忆内容
            documents = []
            for memory in memories:
                content = getattr(memory, 'content', None) or getattr(memory, 'text', None)
                if content:
                    documents.append({
                        "id": getattr(memory, 'id', str(id(memory))),
                        "content": content,
                        "metadata": {
                            "timestamp": getattr(memory, 'timestamp', None),
                            "emotion": getattr(memory, 'emotion', None),
                            "category": getattr(memory, 'category', None),
                        },
                    })
            
            if documents:
                # 构建索引
                if hasattr(vector_search, 'build_index'):
                    vector_search.build_index(documents)
                    self._vector_index = vector_search
                    self._index_last_build = time.time()
                    logger.info(f"重建向量索引，包含 {len(documents)} 个文档")
            
        except Exception as e:
            logger.error(f"重建向量索引失败: {e}")
    
    def build_context(
        self,
        query: str,
        max_results: int = 10,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """构建上下文
        
        Args:
            query: 查询文本
            max_results: 最大结果数
            use_cache: 是否使用缓存
            
        Returns:
            上下文构建结果
        """
        with self._lock:
            try:
                # 检查缓存
                if use_cache:
                    cached = self._get_from_cache(self._context_cache, query)
                    if cached is not None:
                        self._stats["cache_hits"] += 1
                        return cached
                
                self._stats["cache_misses"] += 1
                
                # 增强查询
                enhanced_query = self.enhance_query(query)
                
                # 混合搜索
                search_results = self._hybrid_search(enhanced_query, max_results)
                
                # 排序结果
                ranked_results = self.rank_results(search_results, query)
                
                # 生成摘要
                summary = self._generate_summary(ranked_results)
                
                # 构建上下文
                context = {
                    "query": query,
                    "enhanced_query": enhanced_query,
                    "results": ranked_results[:max_results],
                    "summary": summary,
                    "total_results": len(ranked_results),
                    "build_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                
                # 更新缓存
                self._update_cache(self._context_cache, query, context)
                
                # 更新统计
                self._stats["total_context_builds"] += 1
                
                return context
                
            except Exception as e:
                logger.error(f"构建上下文失败: {e}")
                return {
                    "query": query,
                    "error": str(e),
                    "results": [],
                    "summary": "",
                }
    
    def enhance_query(self, query: str) -> str:
        """增强查询
        
        Args:
            query: 原始查询
            
        Returns:
            增强后的查询
        """
        try:
            # 检查查询缓存
            cached = self._get_from_cache(self._query_cache, query)
            if cached is not None:
                return cached
            
            # 查询扩展
            expanded = self._expand_query(query)
            
            # 更新缓存
            self._update_cache(self._query_cache, query, expanded)
            
            return expanded
            
        except Exception as e:
            logger.warning(f"增强查询失败: {e}")
            return query
    
    def rank_results(
        self,
        results: List[Dict[str, Any]],
        query: str,
    ) -> List[Dict[str, Any]]:
        """排序结果
        
        Args:
            results: 搜索结果
            query: 原始查询
            
        Returns:
            排序后的结果
        """
        try:
            if not results:
                return []
            
            # 计算每个结果的相关性分数
            scored_results = []
            for result in results:
                relevance = self._calculate_relevance(result, query)
                result["relevance_score"] = relevance
                scored_results.append(result)
            
            # 按相关性排序
            scored_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
            
            return scored_results
            
        except Exception as e:
            logger.warning(f"排序结果失败: {e}")
            return results
    
    def _keyword_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """关键词搜索
        
        Args:
            query: 查询文本
            max_results: 最大结果数
            
        Returns:
            搜索结果
        """
        try:
            if self._memory_manager is None:
                return []
            
            # 尝试使用记忆管理器的搜索功能
            if hasattr(self._memory_manager, 'search'):
                results = self._memory_manager.search(
                    query=query,
                    limit=max_results,
                )
                
                # 标准化结果格式
                normalized = []
                for result in results:
                    normalized.append({
                        "id": getattr(result, 'id', str(id(result))),
                        "content": getattr(result, 'content', '') or getattr(result, 'text', ''),
                        "metadata": {
                            "timestamp": getattr(result, 'timestamp', None),
                            "emotion": getattr(result, 'emotion', None),
                            "category": getattr(result, 'category', None),
                        },
                        "source": "keyword_search",
                    })
                
                self._stats["keyword_searches"] += 1
                return normalized
            
            return []
            
        except Exception as e:
            logger.warning(f"关键词搜索失败: {e}")
            return []
    
    def _vector_search_cached(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """缓存的向量搜索
        
        Args:
            query: 查询文本
            max_results: 最大结果数
            
        Returns:
            搜索结果
        """
        try:
            vector_search = self._get_vector_search()
            if vector_search is None:
                return []
            
            # 检查是否需要重建索引
            if self._vector_index is None or (time.time() - self._index_last_build) > self._index_build_interval:
                # 获取记忆并重建索引
                if self._memory_manager and hasattr(self._memory_manager, 'get_all'):
                    memories = self._memory_manager.get_all()
                    self._rebuild_vector_index(memories)
            
            if self._vector_index is None:
                return []
            
            # 执行向量搜索
            if hasattr(self._vector_index, 'search'):
                results = self._vector_index.search(
                    query=query,
                    top_k=max_results,
                )
                
                # 标准化结果格式
                normalized = []
                for result in results:
                    normalized.append({
                        "id": result.get("id", ""),
                        "content": result.get("content", ""),
                        "metadata": result.get("metadata", {}),
                        "vector_score": result.get("score", 0.0),
                        "source": "vector_search",
                    })
                
                self._stats["vector_searches"] += 1
                return normalized
            
            return []
            
        except Exception as e:
            logger.warning(f"向量搜索失败: {e}")
            return []
    
    def _hybrid_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """混合搜索
        
        Args:
            query: 查询文本
            max_results: 最大结果数
            
        Returns:
            搜索结果
        """
        try:
            # 关键词搜索
            keyword_results = self._keyword_search(query, max_results)
            
            # 向量搜索
            vector_results = self._vector_search_cached(query, max_results)
            
            # 合并结果
            all_results = {}
            
            # 添加关键词搜索结果
            for result in keyword_results:
                result_id = result.get("id", "")
                if result_id:
                    all_results[result_id] = result
            
            # 添加向量搜索结果（如果ID重复，合并信息）
            for result in vector_results:
                result_id = result.get("id", "")
                if result_id:
                    if result_id in all_results:
                        # 合并向量分数
                        all_results[result_id]["vector_score"] = result.get("vector_score", 0.0)
                        all_results[result_id]["source"] = "hybrid"
                    else:
                        all_results[result_id] = result
            
            # 转换为列表
            results = list(all_results.values())
            
            self._stats["hybrid_searches"] += 1
            return results
            
        except Exception as e:
            logger.warning(f"混合搜索失败: {e}")
            return []
    
    def _expand_query(self, query: str) -> str:
        """扩展查询
        
        Args:
            query: 原始查询
            
        Returns:
            扩展后的查询
        """
        try:
            # 简单的查询扩展：添加同义词
            expanded_terms = []
            
            # 提取关键词
            words = query.split()
            expanded_terms.extend(words)
            
            # 添加常见同义词映射
            synonym_map = {
                "开心": ["快乐", "高兴", "愉快"],
                "悲伤": ["难过", "伤心", "沮丧"],
                "愤怒": ["生气", "恼火", "气愤"],
                "恐惧": ["害怕", "担心", "焦虑"],
                "喜欢": ["喜爱", "爱好", "偏好"],
                "讨厌": ["厌恶", "反感", "不喜欢"],
            }
            
            for word in words:
                if word in synonym_map:
                    expanded_terms.extend(synonym_map[word])
            
            # 去重
            unique_terms = list(dict.fromkeys(expanded_terms))
            
            return " ".join(unique_terms)
            
        except Exception as e:
            logger.warning(f"扩展查询失败: {e}")
            return query
    
    def _calculate_relevance(
        self,
        result: Dict[str, Any],
        query: str,
    ) -> float:
        """计算相关性
        
        Args:
            result: 搜索结果
            query: 查询文本
            
        Returns:
            相关性分数 (0-1)
        """
        try:
            score = 0.0
            
            # 基础分数（来自搜索）
            if "vector_score" in result:
                score += result["vector_score"] * 0.6
            
            # 内容匹配度
            content = result.get("content", "")
            if content and query:
                # 简单的词重叠计算
                query_words = set(query.split())
                content_words = set(content.split())
                overlap = len(query_words & content_words)
                if query_words:
                    score += (overlap / len(query_words)) * 0.4
            
            # 时间新鲜度
            metadata = result.get("metadata", {})
            timestamp = metadata.get("timestamp")
            if timestamp:
                if isinstance(timestamp, str):
                    try:
                        timestamp = datetime.datetime.fromisoformat(timestamp)
                    except:
                        pass
                
                if isinstance(timestamp, datetime.datetime):
                    # 计算时间衰减
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
                    
                    days_old = (now - timestamp).days
                    time_decay = max(0.5, 1.0 - days_old / 365)
                    score *= time_decay
            
            return min(1.0, max(0.0, score))
            
        except Exception as e:
            logger.warning(f"计算相关性失败: {e}")
            return 0.5
    
    def _generate_summary(self, results: List[Dict[str, Any]]) -> str:
        """生成摘要
        
        Args:
            results: 搜索结果
            
        Returns:
            摘要文本
        """
        try:
            if not results:
                return "没有找到相关记忆"
            
            # 提取主要内容
            contents = []
            for result in results[:5]:  # 只取前5个结果
                content = result.get("content", "")
                if content:
                    # 截断过长的内容
                    if len(content) > 200:
                        content = content[:200] + "..."
                    contents.append(content)
            
            if not contents:
                return "没有找到相关内容"
            
            # 生成摘要
            summary = "找到以下相关记忆：\n"
            for i, content in enumerate(contents, 1):
                summary += f"{i}. {content}\n"
            
            return summary.strip()
            
        except Exception as e:
            logger.warning(f"生成摘要失败: {e}")
            return "生成摘要时出错"
    
    def _get_from_cache(
        self,
        cache: Dict[str, Tuple[Any, float]],
        key: str,
    ) -> Optional[Any]:
        """从缓存获取
        
        Args:
            cache: 缓存字典
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或过期则返回None
        """
        if key in cache:
            value, timestamp = cache[key]
            if (time.time() - timestamp) < self._cache_ttl:
                return value
            else:
                # 过期，删除
                del cache[key]
        return None
    
    def _update_cache(
        self,
        cache: Dict[str, Tuple[Any, float]],
        key: str,
        value: Any,
    ) -> None:
        """更新缓存
        
        Args:
            cache: 缓存字典
            key: 缓存键
            value: 缓存值
        """
        cache[key] = (value, time.time())
        
        # 限制缓存大小
        if len(cache) > 1000:
            # 删除最旧的缓存
            oldest_key = min(cache.keys(), key=lambda k: cache[k][1])
            del cache[oldest_key]
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计
        
        Returns:
            缓存统计信息
        """
        with self._lock:
            return {
                "context_cache_size": len(self._context_cache),
                "query_cache_size": len(self._query_cache),
                "cache_ttl": self._cache_ttl,
                "hit_rate": self._stats["cache_hits"] / max(1, self._stats["cache_hits"] + self._stats["cache_misses"]),
            }
    
    def clear_cache(self) -> None:
        """清除缓存"""
        with self._lock:
            self._context_cache.clear()
            self._query_cache.clear()
            logger.info("上下文注入器缓存已清除")
    
    def rebuild_index(self, memories: Optional[List[Any]] = None) -> None:
        """重建索引
        
        Args:
            memories: 记忆列表，为None时从记忆管理器获取
        """
        with self._lock:
            try:
                if memories is None and self._memory_manager:
                    if hasattr(self._memory_manager, 'get_all'):
                        memories = self._memory_manager.get_all()
                    else:
                        memories = []
                
                if memories:
                    self._rebuild_vector_index(memories)
                    logger.info("索引重建完成")
                else:
                    logger.warning("没有记忆数据用于重建索引")
                    
            except Exception as e:
                logger.error(f"重建索引失败: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            cache_stats = self.get_cache_stats()
            return {
                **self._stats,
                **cache_stats,
                "index_last_build": self._index_last_build,
                "vector_index_available": self._vector_index is not None,
            }


# 全局实例管理
_context_injector_instances: Dict[str, ContextInjector] = {}
_context_injector_lock = threading.Lock()


def get_context_injector(
    memory_manager: Any = None,
    vector_search: Any = None,
) -> ContextInjector:
    """获取上下文注入器单例
    
    Args:
        memory_manager: 记忆管理器
        vector_search: 向量搜索引擎
        
    Returns:
        上下文注入器实例
    """
    global _context_injector_instances
    
    with _context_injector_lock:
        instance_id = "default"
        if instance_id not in _context_injector_instances:
            _context_injector_instances[instance_id] = ContextInjector(
                memory_manager=memory_manager,
                vector_search=vector_search,
            )
        return _context_injector_instances[instance_id]


def reset_context_injector() -> None:
    """重置上下文注入器单例"""
    global _context_injector_instances
    
    with _context_injector_lock:
        _context_injector_instances.clear()


def reset_all_context_injectors() -> None:
    """重置所有上下文注入器单例"""
    reset_context_injector()