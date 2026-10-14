"""
全面单元测试 - cache 模块

测试 neurova/core/cache.py
覆盖 MemoryCache 类。
"""
import time
from datetime import datetime, timedelta

from neurova.core.cache import MemoryCache


class TestMemoryCache:
    """测试 MemoryCache 基本功能"""

    def test_init(self):
        cache = MemoryCache()
        assert cache is not None

    def test_set_and_get(self):
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_non_existent(self):
        cache = MemoryCache()
        assert cache.get("non_existent") is None

    def test_delete(self):
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None

    def test_delete_non_existent(self):
        cache = MemoryCache()
        assert cache.delete("non_existent") is False

    def test_clear(self):
        cache = MemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_get_stats(self):
        cache = MemoryCache()
        stats = cache.get_stats()
        assert isinstance(stats, dict)
