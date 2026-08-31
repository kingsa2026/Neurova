"""Skill Market Searcher v2 - 技能市场搜索器（基于 market_adapters 注册表）

v2 契约（tests/unit/skills/test_market_searcher.py）:
- SearchResult 主字段 skill_name/market（name/source 为向后兼容 property 别名，
  skill_need_analyzer 等既有消费方按旧字段读取）;
- SkillMarketSearcher 持有 registry（默认经 get_market_registry 注入适配器注册表）、
  _cache/_cache_ttl、clear_cache/list_markets 委托 registry;
- search_market / search_all_markets 为同步核心（适配器是 sync urllib），
  另提供 * _async 薄包装供 async 上下文使用（线程池执行，不阻塞事件循环）。

注意: 各适配器的上游 URL 正确性属 market_adapters.py 的职责范围，本模块只做
聚合/缓存/格式映射。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.skills.market_adapters import SkillInfo, get_market_registry

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """跨市场统一搜索结果

    skill_name/market 为主字段；name/source 为兼容别名 property
    （skill_need_analyzer 等旧消费方契约）。
    """

    skill_name: str
    description: str = ""
    market: str = ""
    url: str = ""
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    stars: int = 0
    downloads: int = 0
    last_updated: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """向后兼容别名（= skill_name）"""
        return self.skill_name

    @property
    def source(self) -> str:
        """向后兼容别名（= market）"""
        return self.market

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（同时携带新旧键，消费方任选）"""
        data = asdict(self)
        data["name"] = self.skill_name
        data["source"] = self.market
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
        """从字典创建（兼容旧 name/source 键与 v2 skill_name/market 键）"""
        return cls(
            skill_name=str(data.get("skill_name") or data.get("name") or ""),
            description=str(data.get("description") or ""),
            market=str(data.get("market") or data.get("source") or ""),
            url=str(data.get("url") or ""),
            version=str(data.get("version") or "1.0.0"),
            author=str(data.get("author") or ""),
            tags=list(data.get("tags") or []),
            stars=int(data.get("stars") or 0),
            downloads=int(data.get("downloads") or 0),
            last_updated=str(data.get("last_updated") or ""),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_skill_info(cls, info: SkillInfo, market: str) -> "SearchResult":
        """从适配器 SkillInfo 构造"""
        return cls(
            skill_name=info.name,
            description=info.description,
            market=market or info.source,
            url=info.url or info.download_url,
            version=info.version,
            author=info.author,
            tags=list(info.tags or []),
        )


class SkillMarketSearcher:
    """技能市场搜索器

    基于 SkillMarketRegistry（market_adapters）聚合多市场搜索。
    同步接口为主（适配器为 sync urllib）；search_*_async 供 async 上下文。
    """

    def __init__(self, cache_dir: Optional[str] = None, registry: Any = None):
        """
        Args:
            cache_dir: 缓存目录（兼容旧签名，仅保留目录管理职责）
            registry: SkillMarketRegistry 实例；缺省经 get_market_registry()
                惰性获取（测试可 patch neurova.skills.market_searcher.get_market_registry）
        """
        self._cache_dir = cache_dir or ""
        if registry is None:
            registry = get_market_registry()
        self.registry = registry
        # 查询结果缓存: {key: {"results": [...], "timestamp": float}}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 分钟

        if self._cache_dir:
            import os

            os.makedirs(self._cache_dir, exist_ok=True)

        logger.info("SkillMarketSearcher initialized (registry=%s)", type(registry).__name__)

    # ── 查询 ──

    def search_market(self, market: str, query: str, limit: int = 10) -> List[SearchResult]:
        """搜索单个市场（同步；经 TTL 缓存）"""
        if market not in self.list_market_names():
            raise ValueError(
                f"Unsupported market: {market}. Supported markets: {self.list_market_names()}"
            )

        cache_key = f"{market}:{query}:{limit}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        adapter = self.registry.get_adapter(market)
        infos = adapter.search(query, limit=limit)
        results = [SearchResult.from_skill_info(i, market=market) for i in infos]

        self._add_to_cache(cache_key, results)
        return results

    def search_all_markets(
        self, query: str, limit_per_market: int = 10, markets: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """搜索所有（或指定）市场并按相关性聚合（同步）"""
        names = list(markets) if markets else self.list_market_names()
        all_results: List[SearchResult] = []
        for market in names:
            try:
                all_results.extend(self.search_market(market, query, limit_per_market))
            except Exception as e:  # noqa: BLE001 — 单市场失败不阻断聚合
                logger.warning("Failed to search market %s: %s", market, e)

        all_results.sort(key=lambda x: self._relevance_score(x, query), reverse=True)
        return all_results

    def list_markets(self) -> List[Any]:
        """列出可用市场（透传 registry.list_markets()）"""
        return self.registry.list_markets()

    def list_market_names(self) -> List[str]:
        """市场名列表（registry 返回 dict 时取 name 键）"""
        names = []
        for item in self.list_markets():
            if isinstance(item, dict):
                names.append(str(item.get("name", "")))
            else:
                names.append(str(item))
        return [n for n in names if n]

    # ── async 薄包装（供 async 上下文；线程池执行避免阻塞事件循环） ──

    async def search_market_async(self, market: str, query: str, limit: int = 10) -> List[SearchResult]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.search_market, market, query, limit)

    async def search_all_markets_async(
        self, query: str, limit_per_market: int = 10, markets: Optional[List[str]] = None
    ) -> List[SearchResult]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.search_all_markets, query, limit_per_market, markets)

    # ── 缓存 ──

    def clear_cache(self) -> None:
        """清除全部查询缓存"""
        self._cache.clear()
        logger.info("Market search cache cleared")

    def _get_from_cache(self, key: str) -> Optional[List[SearchResult]]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry.get("timestamp", 0) >= self._cache_ttl:
            del self._cache[key]
            return None
        return entry.get("results")

    def _add_to_cache(self, key: str, results: List[SearchResult]) -> None:
        self._cache[key] = {"results": results, "timestamp": time.time()}

    # ── 相关性 ──

    def _relevance_score(self, result: SearchResult, query: str) -> float:
        """查询相关性评分：名称/描述/标签命中 + 星数与下载量加权"""
        score = 0.0
        query_lower = (query or "").lower()

        if query_lower and query_lower in result.skill_name.lower():
            score += 10.0
        if query_lower and query_lower in result.description.lower():
            score += 5.0
        for tag in result.tags:
            if query_lower and query_lower in str(tag).lower():
                score += 2.0
        score += min(result.stars / 1000, 5.0)
        score += min(result.downloads / 1000, 5.0)
        return score
