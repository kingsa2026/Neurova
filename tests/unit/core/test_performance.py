"""
测试：performance — 性能优化模块 (MemoryCache, PerformanceMonitor, cached 装饰器)
"""

import time
from unittest.mock import patch

from neurova.performance import MemoryCache, PerformanceMonitor, cached


class TestMemoryCache:
    """测试 MemoryCache 缓存管理器"""

    def test_init_defaults(self):
        """默认参数初始化"""
        cache = MemoryCache()
        assert cache.max_size == 1000
        assert cache.ttl == 300
        assert len(cache.cache) == 0

    def test_init_custom(self):
        """自定义参数初始化"""
        cache = MemoryCache(max_size=10, ttl=60)
        assert cache.max_size == 10
        assert cache.ttl == 60

    def test_set_and_get(self):
        """设置后能正确获取"""
        cache = MemoryCache(max_size=100, ttl=60)
        cache.set("query1", {"result": "data"})
        result = cache.get("query1")
        assert result == {"result": "data"}

    def test_get_missing_key(self):
        """不存在的键返回 None"""
        cache = MemoryCache()
        assert cache.get("nonexistent") is None

    def test_get_expired(self):
        """过期键返回 None 并自动删除"""
        cache = MemoryCache(max_size=100, ttl=0)  # TTL=0 立即过期
        cache.set("query", "data")
        time.sleep(0.01)  # 确保时间过去
        result = cache.get("query")
        assert result is None
        # 过期条目应被删除
        assert "query" not in cache.cache
        assert "query" not in cache.access_count
        assert "query" not in cache.last_access

    def test_get_updates_access_count(self):
        """获取时更新访问次数"""
        cache = MemoryCache(max_size=100, ttl=60)
        cache.set("q", "data")
        cache.get("q")
        assert cache.access_count.get(cache._generate_key("q")) == 1
        cache.get("q")
        assert cache.access_count.get(cache._generate_key("q")) == 2

    def test_set_evicts_lru(self):
        """超过 max_size 时淘汰最少访问的条目"""
        cache = MemoryCache(max_size=3, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # 访问 a 两次，b 一次，c 零次
        cache.get("a")
        cache.get("a")
        cache.get("b")
        # 添加 d，应淘汰 c（访问最少）
        cache.set("d", 4)
        assert cache.get("d") == 4
        assert cache.get("a") == 1
        assert cache.get("c") is None  # 被淘汰

    def test_clear(self):
        """清空缓存"""
        cache = MemoryCache(max_size=100, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert len(cache.cache) == 0
        assert len(cache.access_count) == 0
        assert len(cache.last_access) == 0

    def test_stats(self):
        """统计信息"""
        cache = MemoryCache(max_size=10, ttl=300)
        stats = cache.stats()
        assert stats["size"] == 0
        assert stats["max_size"] == 10
        assert stats["ttl"] == 300
        assert stats["hit_rate"] == 0.0

        cache.set("q", 1)
        stats2 = cache.stats()
        assert stats2["size"] == 1

    def test_generate_key_deterministic(self):
        """相同参数生成相同键"""
        cache = MemoryCache()
        k1 = cache._generate_key("hello", lang="cn")
        k2 = cache._generate_key("hello", lang="cn")
        assert k1 == k2

    def test_generate_key_different_args(self):
        """不同参数生成不同键"""
        cache = MemoryCache()
        k1 = cache._generate_key("hello", lang="cn")
        k2 = cache._generate_key("hello", lang="en")
        assert k1 != k2

    def test_evict_oldest_when_full_and_all_zero_access(self):
        """满容量时淘汰最早条目"""
        cache = MemoryCache(max_size=2, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # 应淘汰 a
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_key_not_in_access_count_still_works(self):
        """access_count/last_access 缺失键时 get 不应报错"""
        cache = MemoryCache()
        key = cache._generate_key("test")
        # 手动绕过 set 直接写入 cache（模拟 state 不一致）
        cache.cache[key] = {"data": "val", "timestamp": time.time()}
        cache.last_access[key] = time.time()  # 确保 TTL 检查能通过
        result = cache.get("test")
        assert result == "val"


class TestPerformanceMonitor:
    """测试 PerformanceMonitor 性能监控器"""

    def test_start_and_stop(self):
        """开始和停止计时"""
        monitor = PerformanceMonitor()
        monitor.start("op1")
        time.sleep(0.01)
        duration = monitor.stop("op1")
        assert duration > 0
        assert "op1" in monitor.duration

    def test_stop_unstarted(self):
        """停止未开始的操作为返回 0.0"""
        monitor = PerformanceMonitor()
        assert monitor.stop("nonexistent") == 0.0

    def test_get_stats(self):
        """获取性能统计"""
        monitor = PerformanceMonitor()
        monitor.start("a")
        time.sleep(0.01)
        monitor.stop("a")
        stats = monitor.get_stats()
        assert "a" in stats["operations"]
        assert "a" in stats["durations"]
        assert stats["total_time"] > 0

    def test_multiple_operations(self):
        """多个操作统计"""
        monitor = PerformanceMonitor()
        monitor.start("op1")
        monitor.stop("op1")
        monitor.start("op2")
        monitor.stop("op2")
        stats = monitor.get_stats()
        assert set(stats["operations"]) == {"op1", "op2"}
        assert len(stats["durations"]) == 2

    def test_print_report(self, capsys):
        """打印报告"""
        monitor = PerformanceMonitor()
        monitor.start("task")
        time.sleep(0.01)
        monitor.stop("task")
        monitor.print_report()
        captured = capsys.readouterr()
        assert "性能报告" in captured.out
        assert "task" in captured.out
        assert "总耗时" in captured.out


class TestCachedDecorator:
    """测试 cached 装饰器（同步版本）"""

    def test_cache_hit(self):
        """缓存命中时不重复执行"""
        call_count = 0

        @cached(ttl=60)
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert compute(5) == 10
        assert call_count == 1
        # 第二次应命中缓存
        assert compute(5) == 10
        assert call_count == 1  # 未增加

    def test_cache_miss_different_args(self):
        """不同参数应重新计算"""
        call_count = 0

        @cached(ttl=60)
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert compute(1) == 2
        assert compute(2) == 4
        assert call_count == 2

    def test_cache_eviction(self):
        """TTL 过期后应重新计算"""
        call_count = 0

        @cached(ttl=0)  # 立即过期
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x

        compute(1)
        assert call_count == 1
        time.sleep(0.01)
        compute(1)
        # 注意：cached 装饰器内部 MemoryCache 使用 ttl，但 get 检查的是 time.time() - last_access
        # TTL=0 意味着每次 get 都会过期
        assert call_count == 2
