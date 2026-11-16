# -*- coding: utf-8 -*-
"""CacheRetrieverAdapter 本地缓存有界化（审计 3.2-8，2026-11-17）：

`_simple_cache` 原是无界 dict、只写不淘汰——长驻进程随查询多样性单向增长。
收口到 `core/cache.MemoryCache` 单源（LRU + TTL，AGENTS §3/教义第 6 条），
容量 256、TTL 600s、cleanup_interval=0（读时过期判定，不起后台定时器——
适配器按管线实例构造，每实例一条清理线程是纯浪费）。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.agent.retriever_adapters import CacheRetrieverAdapter
from neurova.core.cache import MemoryCache

CAPACITY = 256


class TestSimpleCacheBounded:
    def test_cache_is_memory_cache_single_source(self):
        adapter = CacheRetrieverAdapter(cache_manager=None)
        assert isinstance(adapter._simple_cache, MemoryCache), (
            "本地缓存必须收口到 core/cache.MemoryCache 单源（LRU+TTL），"
            "无界 dict 只写不淘汰是长驻进程内存泄漏"
        )

    def test_cache_bounded_under_repeated_writes(self):
        adapter = CacheRetrieverAdapter(cache_manager=None)
        for i in range(300):
            asyncio.run(adapter.retrieve(RetrievalContext(query=f"query-{i}")))
        assert len(adapter._simple_cache.keys()) <= CAPACITY, (
            "重复写入后缓存必须停在容量上限内（原 dict 会涨到 300）"
        )

    def test_evicted_entry_no_longer_served(self):
        adapter = CacheRetrieverAdapter(cache_manager=None)
        first_key = "query-0"[:100].strip().lower()
        asyncio.run(adapter.retrieve(RetrievalContext(query="query-0")))
        for i in range(1, 300):
            asyncio.run(adapter.retrieve(RetrievalContext(query=f"query-{i}")))
        assert first_key not in adapter._simple_cache.keys(), (
            "最旧条目应被 LRU 逐出（淘汰语义可验证，不是只加不减）"
        )

    def test_cache_hit_still_served(self):
        """既有契约保持：命中返回缓存内容。"""
        adapter = CacheRetrieverAdapter(cache_manager=None)
        cached = [{"content": "cached memory"}]
        adapter._simple_cache.set("cached query"[:100].strip().lower(), cached)
        result = asyncio.run(adapter.retrieve(RetrievalContext(query="cached query")))
        assert result.memories == cached


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
