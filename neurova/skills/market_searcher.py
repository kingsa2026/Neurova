from __future__ import annotations

"""
Skill Market Searcher - 技能市场搜索器

支持跨市场搜索技能，并返回统一格式的搜索结果。
"""

import asyncio
import json
from neurova.core import config
from neurova.core.logger import get_logger
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = get_logger(__name__)


@dataclass
class SearchResult:
    """
    搜索结果数据类
    """

    name: str
    source: str
    description: str = ""
    url: str = ""
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    stars: int = 0
    downloads: int = 0
    last_updated: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "stars": self.stars,
            "downloads": self.downloads,
            "last_updated": self.last_updated,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            source=data.get("source", ""),
            description=data.get("description", ""),
            url=data.get("url", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            stars=data.get("stars", 0),
            downloads=data.get("downloads", 0),
            last_updated=data.get("last_updated", ""),
            metadata=data.get("metadata", {}),
        )


class SkillMarketSearcher:
    """
    技能市场搜索器

    支持从多个技能市场搜索技能，包括：
    - GitHub
    - LobeHub
    - ModelScope
    - SkillHub.cn
    """

    # 支持的市场列表
    SUPPORTED_MARKETS = ["github", "lobehub", "modelscope", "skillhub_cn"]

    # 缓存过期时间（秒）
    CACHE_TTL = 300  # 5分钟

    def __init__(self, cache_dir: Optional[str] = None):
        """
        初始化搜索器

        Args:
            cache_dir: 缓存目录路径
        """
        self._cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".neurova", "cache", "market_search")
        self._cache: Dict[str, Dict[str, Any]] = {}

        # 确保缓存目录存在
        os.makedirs(self._cache_dir, exist_ok=True)

        logger.info("SkillMarketSearcher initialized")

    def list_markets(self) -> List[str]:
        """
        列出支持的市场

        Returns:
            List[str]: 支持的市场名称列表
        """
        return self.SUPPORTED_MARKETS.copy()

    def search_all_markets(self, query: str, limit: int = 10) -> List[SearchResult]:
        """
        搜索所有市场

        Args:
            query: 搜索关键词
            limit: 每个市场的结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        all_results = []

        for market in self.SUPPORTED_MARKETS:
            try:
                results = self.search_market(market, query, limit)
                all_results.extend(results)
            except Exception as e:
                logger.warning("Failed to search market %s: %s", market, e)

        # 按相关性评分排序
        all_results.sort(key=lambda x: self._relevance_score(x, query), reverse=True)

        return all_results

    def search_market(self, market: str, query: str, limit: int = 10) -> List[SearchResult]:
        """
        搜索单个市场

        Args:
            market: 市场名称
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表

        Raises:
            ValueError: 市场不存在
        """
        if market not in self.SUPPORTED_MARKETS:
            raise ValueError(f"Unsupported market: {market}. Supported markets: {self.SUPPORTED_MARKETS}")

        # 检查缓存
        cache_key = f"{market}:{query}:{limit}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # 搜索市场
        results = self._search_market(market, query, limit)

        # 添加到缓存
        self._add_to_cache(cache_key, results)

        return results

    def _search_market(self, market: str, query: str, limit: int) -> List[SearchResult]:
        """
        搜索单个市场（内部方法）

        Args:
            market: 市场名称
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        if market == "github":
            return self._search_github(query, limit)
        elif market == "lobehub":
            return self._search_lobehub(query, limit)
        elif market == "modelscope":
            return self._search_modelscope(query, limit)
        elif market == "skillhub_cn":
            return self._search_skillhub_cn(query, limit)
        else:
            return []

    def _search_github(self, query: str, limit: int) -> List[SearchResult]:
        """
        搜索 GitHub 市场

        Args:
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        results = []

        try:
            # 构建搜索 URL
            encoded_query = urllib.parse.quote(f"{query} neurova skill")
            url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page={limit}"

            # 获取 GitHub Token
            token = self._get_github_token()
            headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Neurova-SkillSearcher"}
            if token:
                headers["Authorization"] = f"token {token}"

            # 发送请求
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                for item in data.get("items", []):
                    result = SearchResult(
                        name=item.get("name", ""),
                        source="github",
                        description=item.get("description", ""),
                        url=item.get("html_url", ""),
                        version="1.0.0",
                        author=item.get("owner", {}).get("login", ""),
                        tags=item.get("topics", []),
                        stars=item.get("stargazers_count", 0),
                        last_updated=item.get("updated_at", ""),
                    )
                    results.append(result)

        except Exception as e:
            logger.error("Failed to search GitHub: %s", e)

        return results

    def _search_lobehub(self, query: str, limit: int) -> List[SearchResult]:
        """
        搜索 LobeHub 市场

        Args:
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        results = []

        try:
            # LobeHub API
            encoded_query = urllib.parse.quote(query)
            url = f"https://api.lobehub.com/api/skills/search?q={encoded_query}&limit={limit}"

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                for item in data.get("skills", []):
                    result = SearchResult(
                        name=item.get("name", ""),
                        source="lobehub",
                        description=item.get("description", ""),
                        url=item.get("url", ""),
                        version=item.get("version", "1.0.0"),
                        author=item.get("author", ""),
                        tags=item.get("tags", []),
                        downloads=item.get("downloads", 0),
                    )
                    results.append(result)

        except Exception as e:
            logger.error("Failed to search LobeHub: %s", e)

        return results

    def _search_modelscope(self, query: str, limit: int) -> List[SearchResult]:
        """
        搜索 ModelScope 市场

        Args:
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        results = []

        try:
            # ModelScope API
            encoded_query = urllib.parse.quote(query)
            url = f"https://api.modelscope.cn/api/v1/skills/search?q={encoded_query}&limit={limit}"

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                for item in data.get("data", []):
                    result = SearchResult(
                        name=item.get("name", ""),
                        source="modelscope",
                        description=item.get("description", ""),
                        url=item.get("url", ""),
                        version=item.get("version", "1.0.0"),
                        author=item.get("author", ""),
                        tags=item.get("tags", []),
                        downloads=item.get("downloads", 0),
                    )
                    results.append(result)

        except Exception as e:
            logger.error("Failed to search ModelScope: %s", e)

        return results

    def _search_skillhub_cn(self, query: str, limit: int) -> List[SearchResult]:
        """
        搜索 SkillHub.cn 市场

        Args:
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        results = []

        try:
            # SkillHub.cn API
            encoded_query = urllib.parse.quote(query)
            url = f"https://api.skillhub.cn/api/skills/search?q={encoded_query}&limit={limit}"

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                for item in data.get("skills", []):
                    result = SearchResult(
                        name=item.get("name", ""),
                        source="skillhub_cn",
                        description=item.get("description", ""),
                        url=item.get("url", ""),
                        version=item.get("version", "1.0.0"),
                        author=item.get("author", ""),
                        tags=item.get("tags", []),
                        downloads=item.get("downloads", 0),
                    )
                    results.append(result)

        except Exception as e:
            logger.error("Failed to search SkillHub.cn: %s", e)

        return results

    def _relevance_score(self, result: SearchResult, query: str) -> float:
        """
        计算相关性评分

        Args:
            result: 搜索结果
            query: 搜索关键词

        Returns:
            float: 相关性评分
        """
        score = 0.0
        query_lower = query.lower()

        # 名称匹配
        if query_lower in result.name.lower():
            score += 10.0

        # 描述匹配
        if query_lower in result.description.lower():
            score += 5.0

        # 标签匹配
        for tag in result.tags:
            if query_lower in tag.lower():
                score += 2.0

        # 星数加分
        score += min(result.stars / 1000, 5.0)

        # 下载量加分
        score += min(result.downloads / 1000, 5.0)

        return score

    def _get_from_cache(self, key: str) -> Optional[List[SearchResult]]:
        """
        从缓存获取数据

        Args:
            key: 缓存键

        Returns:
            Optional[List[SearchResult]]: 缓存的数据，如果不存在或过期则返回 None
        """
        if key in self._cache:
            cache_entry = self._cache[key]
            if time.time() - cache_entry["timestamp"] < self.CACHE_TTL:
                return cache_entry["data"]
            else:
                del self._cache[key]
        return None

    def _add_to_cache(self, key: str, data: List[SearchResult]):
        """
        添加到缓存

        Args:
            key: 缓存键
            data: 要缓存的数据
        """
        self._cache[key] = {"data": data, "timestamp": time.time()}

        # 清理过期缓存
        self._clean_cache()

    def _clean_cache(self):
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = [
            key for key, value in self._cache.items() if current_time - value["timestamp"] >= self.CACHE_TTL
        ]
        for key in expired_keys:
            del self._cache[key]

    def _get_github_token(self) -> Optional[str]:
        """
        获取 GitHub Token

        Returns:
            Optional[str]: GitHub Token
        """
        return config.get("GITHUB_TOKEN")

    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()
        logger.info("Cache cleared")

    async def search_all_markets_async(self, query: str, limit: int = 10) -> List[SearchResult]:
        """
        异步搜索所有市场

        Args:
            query: 搜索关键词
            limit: 每个市场的结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        tasks = []
        for market in self.SUPPORTED_MARKETS:
            task = asyncio.create_task(self._search_market_async(market, query, limit))
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for result in results:
            if isinstance(result, list):
                all_results.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Async search failed: %s", result)

        # 按相关性评分排序
        all_results.sort(key=lambda x: self._relevance_score(x, query), reverse=True)

        return all_results

    async def _search_market_async(self, market: str, query: str, limit: int) -> List[SearchResult]:
        """
        异步搜索单个市场

        Args:
            market: 市场名称
            query: 搜索关键词
            limit: 结果限制

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        # 在线程池中执行同步搜索
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.search_market, market, query, limit)
