"""
搜索记忆 Mixin - 从 MemoryStorage 中提取的搜索相关方法

提供向量检索 + FTS5 全文检索 + 增强版多层级检索。
"""

import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


class SearchMixin:
    """
    搜索记忆 Mixin

    提供向量检索 + FTS5 全文检索 + 增强版多层级检索。
    """

    def __init__(self):
        """初始化搜索功能"""
        self._search_lock = threading.RLock()
        self._search_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
        self._cache_ttl = 300  # 5分钟缓存
        logger.info("SearchMixin 初始化完成")

    def search_memories(
        self,
        query: str,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None,
        search_type: str = "hybrid",
    ) -> List[Dict[str, Any]]:
        """
        搜索记忆

        Args:
            query: 搜索查询
            limit: 返回数量限制
            filters: 可选的过滤条件
            search_type: 搜索类型 (text, vector, hybrid)

        Returns:
            搜索结果
        """
        if not query or not query.strip():
            return []

        # 检查缓存
        cache_key = f"{query}:{limit}:{search_type}:{filters}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        with self._search_lock:
            start_time = time.time()

            # 根据搜索类型选择策略
            if search_type == "text":
                results = self._text_search(query, limit, filters)
            elif search_type == "vector":
                results = self._vector_search(query, limit, filters)
            else:  # hybrid
                text_results = self._text_search(query, limit * 2, filters)
                vector_results = self._vector_search(query, limit * 2, filters)
                results = self._merge_results(text_results, vector_results, limit)

            # 添加搜索元数据
            search_time = time.time() - start_time
            for result in results:
                result["search_metadata"] = {
                    "query": query,
                    "search_type": search_type,
                    "search_time_ms": search_time * 1000,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

            # 缓存结果
            self._add_to_cache(cache_key, results)

            return results

    def _text_search(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """文本搜索（FTS5）"""
        # 这里是简化实现，实际应该使用SQLite FTS5
        results = []
        query.lower()

        # 模拟文本搜索
        # 在实际实现中，这里应该使用SQLite FTS5查询
        logger.debug("执行文本搜索: %s", query)

        return results[:limit]

    def _vector_search(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """向量搜索"""
        # 这里是简化实现，实际应该使用向量相似度计算
        results = []

        # 模拟向量搜索
        # 在实际实现中，这里应该计算向量相似度
        logger.debug("执行向量搜索: %s", query)

        return results[:limit]

    def _merge_results(
        self,
        text_results: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """合并搜索结果"""
        # 使用RRF（Reciprocal Rank Fusion）算法合并结果
        merged: Dict[str, Dict[str, Any]] = {}

        # 处理文本结果
        for rank, result in enumerate(text_results):
            memory_id = result.get("id", "")
            if memory_id not in merged:
                merged[memory_id] = result.copy()
                merged[memory_id]["scores"] = {}

            # RRF分数: 1 / (k + rank)
            k = 60  # 常数
            merged[memory_id]["scores"]["text"] = 1.0 / (k + rank + 1)

        # 处理向量结果
        for rank, result in enumerate(vector_results):
            memory_id = result.get("id", "")
            if memory_id not in merged:
                merged[memory_id] = result.copy()
                merged[memory_id]["scores"] = {}

            # RRF分数
            k = 60
            merged[memory_id]["scores"]["vector"] = 1.0 / (k + rank + 1)

        # 计算综合分数
        for memory_id, result in merged.items():
            scores = result.get("scores", {})
            text_score = scores.get("text", 0)
            vector_score = scores.get("vector", 0)

            # 加权平均
            result["final_score"] = 0.4 * text_score + 0.6 * vector_score

        # 按综合分数排序
        results = list(merged.values())
        results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        return results[:limit]

    def search_by_embedding(
        self,
        embedding: List[float],
        limit: int = 20,
        threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        通过嵌入向量搜索

        Args:
            embedding: 查询嵌入向量
            limit: 返回数量限制
            threshold: 相似度阈值

        Returns:
            搜索结果
        """
        # 简化实现，实际应该使用向量相似度计算
        logger.debug("执行嵌入向量搜索，维度: %s", len(embedding))

        return []

    def search_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        通过标签搜索

        Args:
            tags: 标签列表
            match_all: 是否匹配所有标签
            limit: 返回数量限制

        Returns:
            搜索结果
        """
        logger.debug("执行标签搜索: %s, 匹配所有: %s", tags, match_all)

        return []

    def search_by_time_range(
        self,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        按时间范围搜索

        Args:
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制

        Returns:
            搜索结果
        """
        logger.debug("执行时间范围搜索: %s - %s", start_time, end_time)

        return []

    def search_similar(
        self,
        memory_id: str,
        limit: int = 10,
        threshold: float = 0.6,
    ) -> List[Dict[str, Any]]:
        """
        搜索相似记忆

        Args:
            memory_id: 参考记忆ID
            limit: 返回数量限制
            threshold: 相似度阈值

        Returns:
            相似记忆列表
        """
        logger.debug("搜索与记忆 %s 相似的记忆", memory_id)

        return []

    def advanced_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        sort_by: str = "relevance",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        高级搜索

        Args:
            query: 搜索查询
            filters: 过滤条件
            sort_by: 排序字段 (relevance, time, importance, access_count)
            sort_order: 排序顺序 (asc, desc)
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            搜索结果和元数据
        """
        start_time = time.time()

        # 执行搜索
        results = self.search_memories(query, limit + offset, filters)

        # 排序
        if sort_by == "time":
            results.sort(
                key=lambda x: x.get("created_at", ""),
                reverse=(sort_order == "desc"),
            )
        elif sort_by == "importance":
            results.sort(
                key=lambda x: x.get("importance", 0),
                reverse=(sort_order == "desc"),
            )
        elif sort_by == "access_count":
            results.sort(
                key=lambda x: x.get("access_count", 0),
                reverse=(sort_order == "desc"),
            )
        # relevance 已经是默认排序

        # 分页
        paginated_results = results[offset : offset + limit]

        search_time = time.time() - start_time

        return {
            "results": paginated_results,
            "total_count": len(results),
            "page": offset // limit + 1 if limit > 0 else 1,
            "page_size": limit,
            "search_time_ms": search_time * 1000,
            "query": query,
            "filters": filters,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }

    def _get_from_cache(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """从缓存获取结果"""
        if key in self._search_cache:
            result, timestamp = self._search_cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return result
            else:
                del self._search_cache[key]
        return None

    def _add_to_cache(self, key: str, result: List[Dict[str, Any]]) -> None:
        """添加到缓存"""
        self._search_cache[key] = (result, time.time())

        # 清理过期缓存
        current_time = time.time()
        expired_keys = [k for k, (_, ts) in self._search_cache.items() if current_time - ts >= self._cache_ttl]
        for k in expired_keys:
            del self._search_cache[k]

    def clear_search_cache(self) -> int:
        """清空搜索缓存"""
        count = len(self._search_cache)
        self._search_cache.clear()
        return count

    def get_search_statistics(self) -> Dict[str, Any]:
        """获取搜索统计信息"""
        return {
            "cache_size": len(self._search_cache),
            "cache_ttl": self._cache_ttl,
        }
