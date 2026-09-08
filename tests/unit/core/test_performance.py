"""
测试：performance — 性能优化模块（MemoryCache, PerformanceMonitor, cached 装饰器）
对齐 neurova/memory/core/cache.py（MemoryCache 真实载体）与 neurova/performance.py 契约。
"""

import time

from neurova.performance import MemoryCache, PerformanceMonitor, cached


class TestMemoryCache:
    """测试 MemoryCache 缓存管理器（契约：capacity/default_ttl 参数，LRU+TTL）"""

    def test_init_defaults(self):
        """默认参数初始化"""
        cache = MemoryCache()
        stats = cache.get_stats()
        assert stats["capacity"] == 10000
        assert stats["size"] == 0

    def test_init_custom(self):
        """自定义参数初始化"""
        cache = MemoryCache(capacity=10, default_ttl=60)
        stats = cache.get_stats()
        assert stats["capacity"] == 10
        assert stats["size"] == 0

    def test_set_and_get(self):
        """设置后能正确获取"""
        cache = MemoryCache(capacity=100, default_ttl=60)
        cache.set("query1", {"result": "data"})
        result = cache.get("query1")
        assert result == {"result": "data"}

    def test_get_missing_key(self):
        """不存在的键返回 None"""
        cache = MemoryCache()
        assert cache.get("nonexistent") is None

    def test_get_expired(self):
        """过期键返回 None 并删除"""
        cache = MemoryCache(capacity=100, default_ttl=0.01)
        cache.set("query", "data")
        time.sleep(0.05)
        result = cache.get("query")
        assert result is None
        assert "query" not in cache.keys()

    def test_set_per_call_ttl_overrides(self):
        """set 可单次覆盖 TTL"""
        cache = MemoryCache(capacity=100, default_ttl=60)
        cache.set("q", "data", ttl=0.01)
        assert cache.get("q") == "data"
        time.sleep(0.05)
        assert cache.get("q") is None

    def test_set_evicts_lru(self):
        """超过 capacity 时淘汰最久未使用条目"""
        cache = MemoryCache(capacity=3, default_ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # 访问 a、b 使其变新，c 成为最旧
        cache.get("a")
        cache.get("b")
        cache.set("d", 4)
        assert cache.get("d") == 4
        assert cache.get("a") == 1
        assert cache.get("b") == 2
        assert cache.get("c") is None  # 被淘汰

    def test_clear(self):
        """清空缓存并返回条目数"""
        cache = MemoryCache(capacity=100, default_ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        count = cache.clear()
        assert count == 2
        assert cache.keys() == []

    def test_stats(self):
        """统计信息（hits/misses/evictions/size/capacity/hit_rate）"""
        cache = MemoryCache(capacity=10, default_ttl=300)
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["capacity"] == 10
        assert stats["hit_rate"] == 0.0

        cache.set("q", 1)
        cache.get("q")  # hit
        cache.get("missing")  # miss
        stats2 = cache.get_stats()
        assert stats2["size"] == 1
        assert stats2["hits"] == 1
        assert stats2["misses"] == 1

    def test_has_and_delete(self):
        """has/delete 契约"""
        cache = MemoryCache()
        cache.set("k", "v")
        assert cache.has("k") is True
        assert cache.delete("k") is True
        assert cache.has("k") is False

    def test_get_or_set(self):
        """get_or_set：缺失时写入并返回，命中时直接返回"""
        cache = MemoryCache()
        calls = []

        def factory():
            calls.append(1)
            return "computed"

        assert cache.get_or_set("key", factory) == "computed"
        assert cache.get_or_set("key", factory) == "computed"
        assert len(calls) == 1

    def test_evict_oldest_when_full(self):
        """满容量时淘汰最早条目"""
        cache = MemoryCache(capacity=2, default_ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # 应淘汰 a
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3


class TestPerformanceMonitor:
    """测试 PerformanceMonitor 性能监控器"""

    def test_start_and_stop(self):
        """开始和停止计时，返回耗时并写入统计"""
        monitor = PerformanceMonitor()
        timer_id = monitor.start("op1")
        time.sleep(0.01)
        duration = monitor.stop(timer_id)
        assert duration > 0
        stats = monitor.get_stats("op1")
        assert stats["count"] == 1

    def test_stop_unstarted(self):
        """停止未开始的计时器返回 0.0"""
        monitor = PerformanceMonitor()
        assert monitor.stop("nonexistent") == 0.0

    def test_get_stats(self):
        """获取性能统计（_data 结构：count/total_time/min/max/avg/last）"""
        monitor = PerformanceMonitor()
        timer_id = monitor.start("a")
        time.sleep(0.01)
        monitor.stop(timer_id)
        stats = monitor.get_stats()
        assert "a" in stats
        assert stats["a"]["count"] == 1
        assert stats["a"]["total_time"] > 0
        assert stats["a"]["avg_time"] > 0

    def test_get_stats_single_name(self):
        """按名称取单条统计"""
        monitor = PerformanceMonitor()
        timer_id = monitor.start("only")
        monitor.stop(timer_id)

        single = monitor.get_stats("only")
        assert single["count"] == 1
        assert monitor.get_stats("ghost") == {}

    def test_multiple_operations(self):
        """多个操作分别统计"""
        monitor = PerformanceMonitor()
        for name in ("op1", "op2"):
            timer_id = monitor.start(name)
            monitor.stop(timer_id)
        stats = monitor.get_stats()
        assert set(stats.keys()) == {"op1", "op2"}

    def test_print_report(self):
        """打印报告返回报告字符串"""
        monitor = PerformanceMonitor()
        timer_id = monitor.start("task")
        monitor.stop(timer_id)
        report = monitor.print_report()
        assert "性能监控报告" in report
        assert "task" in report

    def test_print_report_empty(self):
        """无数据时报告提示"""
        monitor = PerformanceMonitor()
        assert monitor.print_report() == "没有性能数据"

    def test_clear(self):
        """清空统计数据"""
        monitor = PerformanceMonitor()
        timer_id = monitor.start("task")
        monitor.stop(timer_id)
        monitor.clear()
        assert monitor.get_stats() == {}


class TestCachedDecorator:
    """测试 cached 装饰器"""

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

    def test_cache_ttl_expiry(self):
        """TTL 过期后应重新计算"""
        call_count = 0

        @cached(ttl=0.01)
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x

        compute(1)
        assert call_count == 1
        time.sleep(0.05)
        compute(1)
        assert call_count == 2

    def test_cache_management_methods(self):
        """装饰后函数挂载 cache/cache_clear/cache_stats"""
        @cached(ttl=60, max_size=10)
        def compute(x):
            return x

        assert hasattr(compute, "cache")
        assert hasattr(compute, "cache_clear")
        assert hasattr(compute, "cache_stats")

        compute(1)
        stats = compute.cache_stats()
        assert stats["size"] == 1
        assert compute.cache_clear() >= 1
        assert compute.cache_stats()["size"] == 0

    def test_custom_key_func(self):
        """自定义键生成函数生效"""
        call_count = 0

        def key_func(x):
            return f"fixed_key_{x % 2}"

        @cached(ttl=60, key_func=key_func)
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x

        assert compute(1) == 1
        # 3 与 1 同键 → 命中缓存返回缓存值 1
        assert compute(3) == 1
        assert call_count == 1
        assert compute(2) == 2  # 不同键
        assert call_count == 2

    def test_async_function_supported(self):
        """异步函数走 async 包装器"""
        import asyncio

        call_count = 0

        @cached(ttl=60)
        async def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        async def run():
            r1 = await compute(5)
            r2 = await compute(5)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 == 10
        assert r2 == 10
        assert call_count == 1


class TestGlobalFunctions:
    """测试全局函数与计时装饰器"""

    def test_timing_decorator_sync(self):
        """同步计时装饰器写入全局监控"""
        from neurova.performance import timing_decorator, get_performance_monitor, reset_performance_monitor

        reset_performance_monitor()

        @timing_decorator
        def work():
            return "done"

        assert work() == "done"
        stats = get_performance_monitor().get_stats("work")
        assert stats["count"] == 1
        reset_performance_monitor()

    def test_timing_decorator_async(self):
        """异步计时装饰器写入全局监控"""
        import asyncio
        from neurova.performance import timing_decorator, get_performance_monitor, reset_performance_monitor

        reset_performance_monitor()

        @timing_decorator
        async def work():
            return "done"

        assert asyncio.run(work()) == "done"
        stats = get_performance_monitor().get_stats("work")
        assert stats["count"] == 1
        reset_performance_monitor()
