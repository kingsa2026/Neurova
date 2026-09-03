"""
记忆检索链模块 Bug 修复 TDD 测试 (RED → GREEN)

针对 7 个 bug 编写失败测试,修复后应全部通过。

Bug 列表:
    BUG#1 MoERetrieverAdapter.retrieve 未 await async 方法 (HIGH)
    BUG#2 _retrieve_best / _retrieve_fallback 缺超时控制 (MEDIUM)
    BUG#3 cache_hits 统计不一致 (MEDIUM)
    BUG#4 CacheRetrieverAdapter._simple_cache 死代码 (MEDIUM)
    BUG#5 _retrieve_fallback 不检查 quality (MEDIUM)
    BUG#6 asyncio.get_event_loop().time() 弃用 (LOW)
    BUG#7 MoERetrieverAdapter.routing_score 硬编码 (LOW)
"""
import asyncio
import inspect
import pytest

from neurova.agent.memory_retrieval_chain import (
    MemoryRetrievalChain,
    RetrievalResult,
    RetrievalContext,
    RetrievalQuality,
    RetrievalStrategy,
)
from neurova.agent.retriever_adapters import (
    UnifiedRetrieverAdapter,
    MoERetrieverAdapter,
    CacheRetrieverAdapter,
    FallbackRetrieverAdapter,
)


# ============================================================
# 共用辅助对象
# ============================================================


def _make_result(memories, source="mock", quality=0.8, quality_level=None):
    """构造 RetrievalResult 工厂。"""
    if quality_level is None:
        if quality >= 0.9:
            quality_level = RetrievalQuality.EXCELLENT
        elif quality >= 0.7:
            quality_level = RetrievalQuality.GOOD
        elif quality >= 0.5:
            quality_level = RetrievalQuality.FAIR
        elif quality >= 0.3:
            quality_level = RetrievalQuality.POOR
        else:
            quality_level = RetrievalQuality.FAILED
    return RetrievalResult(
        memories=memories,
        source=source,
        quality=quality,
        quality_level=quality_level,
        retrieval_time=0.01,
    )


class _SlowAsyncRetriever:
    """模拟一个会长时间阻塞的 async 检索器,用于超时测试。

    通过 tracker 列表记录 retrieve 是否真正执行完毕。
    修复前 retrieve 会被完整 await(tracker 追加 'completed'),
    修复后 wait_for 超时会取消 sleep,tracker 保持为空。
    """

    def __init__(self, name, priority, delay, tracker, memories=None, quality=0.8):
        self._name = name
        self._priority = priority
        self._delay = delay
        self._tracker = tracker
        self._memories = memories if memories is not None else [{"content": "slow"}]
        self._quality = quality

    @property
    def name(self):
        return self._name

    @property
    def priority(self):
        return self._priority

    async def retrieve(self, context):
        await asyncio.sleep(self._delay)
        self._tracker.append("completed")
        return _make_result(self._memories, source=self._name, quality=self._quality)

    def get_quality_score(self, memories, query):
        return self._quality


class _SyncFailRetriever:
    """retrieve 抛异常的检索器。"""

    def __init__(self, name, priority):
        self._name = name
        self._priority = priority

    @property
    def name(self):
        return self._name

    @property
    def priority(self):
        return self._priority

    async def retrieve(self, context):
        raise RuntimeError(f"{self._name} boom")

    def get_quality_score(self, memories, query):
        return 0.0


# ============================================================
# BUG#1 — MoERetrieverAdapter 未 await async 方法
# ============================================================


class TestBug1MoEAdapterMissingAwait:
    """BUG#1: MoERetrieverAdapter.retrieve 同步调用 async 的 router.retrieve,
    返回 coroutine,后续 len(coroutine) 抛 TypeError。"""

    @pytest.mark.asyncio
    async def test_moe_adapter_awaits_async_router(self):
        """router.retrieve 是 async,adapter 必须 await。"""

        class AsyncRouter:
            async def retrieve(self, query, limit):
                # 故意返回非空,触发 get_quality_score 的 len() 调用
                return [{"content": query}, {"content": "m2"}]

        adapter = MoERetrieverAdapter(AsyncRouter())
        context = RetrievalContext(query="hello world", limit=5)

        # 修复前:memories 是 coroutine,get_quality_score 里 len(coroutine) 抛 TypeError
        result = await adapter.retrieve(context)

        assert isinstance(result, RetrievalResult)
        assert len(result.memories) == 2
        assert result.source == "MoERetriever"

    @pytest.mark.asyncio
    async def test_moe_adapter_quality_nonzero_when_memories_present(self):
        """有结果时质量分应 > 0,而非 TypeError。"""

        class AsyncRouter:
            async def retrieve(self, query, limit):
                return [{"content": "a"}, {"content": "b"}, {"content": "c"}]

        adapter = MoERetrieverAdapter(AsyncRouter())
        context = RetrievalContext(query="q", limit=5)

        result = await adapter.retrieve(context)
        assert result.quality > 0.0


# ============================================================
# BUG#2 — _retrieve_best / _retrieve_fallback 缺超时控制
# ============================================================


class TestBug2MissingTimeoutInBestAndFallback:
    """BUG#2: _retrieve_best 与 _retrieve_fallback 直接 await,不尊重 context.timeout。"""

    @pytest.mark.asyncio
    async def test_retrieve_best_respects_timeout(self):
        """BEST 策略:慢检索器超过 timeout 应被取消,返回 best_all_failed。"""
        tracker = []
        slow = _SlowAsyncRetriever(
            name="slow",
            priority=10,
            delay=1.0,
            tracker=tracker,
            memories=[{"content": "slow"}],
            quality=0.9,
        )
        chain = MemoryRetrievalChain()
        chain.add_retriever(slow)

        context = RetrievalContext(
            query="q",
            strategy=RetrievalStrategy.BEST,
            timeout=0.05,
            min_quality=0.3,
        )

        # 修复前:会等 1s 直到 slow.retrieve 完整返回 → tracker 含 'completed'
        # 修复后:wait_for 超时 → continue → 无结果 → best_all_failed
        result = await asyncio.wait_for(chain.retrieve(context), timeout=3.0)

        assert result.source == "best_all_failed"
        assert result.memories == []
        assert tracker == []  # 慢检索器不应完整完成

    @pytest.mark.asyncio
    async def test_retrieve_fallback_respects_timeout(self):
        """FALLBACK 策略:主检索器超时应跳过,降级到备用。"""
        tracker = []
        slow_primary = _SlowAsyncRetriever(
            name="slow_primary",
            priority=10,
            delay=1.0,
            tracker=tracker,
            memories=[{"content": "slow"}],
            quality=0.9,
        )

        # 备用检索器立即返回,但质量较低(仍 >= min_quality)
        class FastBackup:
            @property
            def name(self):
                return "fast_backup"

            @property
            def priority(self):
                return 20

            async def retrieve(self, context):
                return _make_result(
                    [{"content": "backup"}], source="fast_backup", quality=0.5
                )

            def get_quality_score(self, memories, query):
                return 0.5

        chain = MemoryRetrievalChain()
        chain.add_retriever(slow_primary)
        chain.add_retriever(FastBackup())

        context = RetrievalContext(
            query="q",
            strategy=RetrievalStrategy.FALLBACK,
            timeout=0.05,
            min_quality=0.4,
        )

        result = await asyncio.wait_for(chain.retrieve(context), timeout=3.0)

        # 应降级到 fast_backup
        assert result.source == "fast_backup"
        # 主检索器超时被取消,不应完整完成
        assert tracker == []

    @pytest.mark.asyncio
    async def test_retrieve_best_timeout_falls_through_to_other_retriever(self):
        """BEST 策略:第一个超时,第二个正常,应返回第二个的结果。"""
        tracker = []
        slow = _SlowAsyncRetriever(
            name="slow",
            priority=10,
            delay=1.0,
            tracker=tracker,
            quality=0.95,
        )

        class FastGood:
            @property
            def name(self):
                return "fast_good"

            @property
            def priority(self):
                return 20

            async def retrieve(self, context):
                return _make_result(
                    [{"content": "fast"}], source="fast_good", quality=0.7
                )

            def get_quality_score(self, memories, query):
                return 0.7

        chain = MemoryRetrievalChain()
        chain.add_retriever(slow)
        chain.add_retriever(FastGood())

        context = RetrievalContext(
            query="q",
            strategy=RetrievalStrategy.BEST,
            timeout=0.05,
            min_quality=0.3,
        )

        result = await asyncio.wait_for(chain.retrieve(context), timeout=3.0)

        # 应选 fast_good(质量 0.7)
        assert result.source == "fast_good"
        assert tracker == []


# ============================================================
# BUG#3 — cache_hits 统计不一致
# ============================================================


class TestBug3CacheHitsInconsistent:
    """BUG#3: 质量不达标路径使用 cache_result 但不加 cache_hits,
    导致统计不一致。"""

    @pytest.mark.asyncio
    async def test_cache_hits_incremented_on_quality_fallback(self):
        """检索质量低于 min_quality 但缓存命中且达标,cache_hits 应 +1。"""

        class HighQualityRetriever:
            """第一次检索:返回高质量结果,写入缓存。"""

            @property
            def name(self):
                return "hq"

            @property
            def priority(self):
                return 10

            async def retrieve(self, context):
                return _make_result(
                    [{"content": "good"}], source="hq", quality=0.8
                )

            def get_quality_score(self, memories, query):
                return 0.8

        class LowQualityRetriever:
            """第二次检索:返回低质量结果,触发缓存降级。"""

            @property
            def name(self):
                return "lq"

            @property
            def priority(self):
                return 10

            async def retrieve(self, context):
                return _make_result(
                    [{"content": "bad"}], source="lq", quality=0.1
                )

            def get_quality_score(self, memories, query):
                return 0.1

        chain = MemoryRetrievalChain()

        # 第一次:高质量结果,写入缓存
        chain.add_retriever(HighQualityRetriever())
        ctx1 = RetrievalContext(query="shared query", min_quality=0.3)
        r1 = await chain.retrieve(ctx1)
        assert r1.quality == 0.8

        # 移除高质量 retriever,加入低质量 retriever
        chain.remove_retriever("hq")
        chain.add_retriever(LowQualityRetriever())

        stats_before = chain.get_statistics()
        hits_before = stats_before["cache_hits"]

        # 第二次:同一 query,低质量结果 < min_quality,触发缓存降级
        ctx2 = RetrievalContext(query="shared query", min_quality=0.3)
        r2 = await chain.retrieve(ctx2)

        # 应使用缓存结果(高质量)
        assert r2.quality >= 0.3

        stats_after = chain.get_statistics()
        hits_after = stats_after["cache_hits"]

        # BUG#3 修复前:cache_hits 不增加(质量不达标路径不加)
        # 修复后:cache_hits += 1
        assert hits_after == hits_before + 1, (
            f"cache_hits 应增加 1,但 before={hits_before}, after={hits_after}"
        )


# ============================================================
# BUG#4 — CacheRetrieverAdapter._simple_cache 死代码
# ============================================================


class TestBug4SimpleCacheDeadCode:
    """BUG#4: _simple_cache 从不初始化也不写入,getattr 永远返回新 {}。"""

    def test_simple_cache_initialized_in_init(self):
        """__init__ 应初始化 _simple_cache 为 dict。"""
        adapter = CacheRetrieverAdapter(cache_manager=None)
        # 修复前:_simple_cache 属性不存在,只能 getattr 返回临时 {}
        assert hasattr(adapter, "_simple_cache")
        assert isinstance(adapter._simple_cache, dict)
        assert adapter._simple_cache == {}

    @pytest.mark.asyncio
    async def test_simple_cache_writes_after_retrieve(self):
        """retrieve 后应把结果写入 _simple_cache(即使空列表也写入)。"""
        adapter = CacheRetrieverAdapter(cache_manager=None)
        context = RetrievalContext(query="hello world")

        await adapter.retrieve(context)

        cache_key = "hello world"[:100].strip().lower()
        # 修复前:_simple_cache 不存在,无法写入
        # 修复后:_simple_cache[cache_key] = memories
        assert hasattr(adapter, "_simple_cache")
        assert cache_key in adapter._simple_cache

    @pytest.mark.asyncio
    async def test_simple_cache_hit_returns_cached(self):
        """手动注入 _simple_cache 后,retrieve 应命中返回缓存内容。"""
        adapter = CacheRetrieverAdapter(cache_manager=None)
        cache_key = "cached query"[:100].strip().lower()
        cached_memories = [{"content": "cached memory"}]
        adapter._simple_cache[cache_key] = cached_memories

        context = RetrievalContext(query="cached query")
        result = await adapter.retrieve(context)

        assert result.memories == cached_memories
        assert result.source == "CacheRetriever"


# ============================================================
# BUG#5 — _retrieve_fallback 不检查 quality
# ============================================================


class TestBug5FallbackNoQualityCheck:
    """BUG#5: _retrieve_fallback 第 471 行只检查 memories 非空,
    不检查 quality >= min_quality,会返回低质量结果。"""

    @pytest.mark.asyncio
    async def test_fallback_rejects_low_quality_backup(self):
        """主检索器失败,备用返回 memories 但 quality < min_quality,
        应继续尝试或返回 fallback_exhausted,而非返回低质量结果。"""

        class LowQualityBackup:
            """备用:有 memories 但 quality=0.1 < min_quality=0.5。"""

            @property
            def name(self):
                return "low_q_backup"

            @property
            def priority(self):
                return 20

            async def retrieve(self, context):
                return _make_result(
                    [{"content": "low quality"}],
                    source="low_q_backup",
                    quality=0.1,
                )

            def get_quality_score(self, memories, query):
                return 0.1

        chain = MemoryRetrievalChain()
        chain.add_retriever(_SyncFailRetriever("failing_primary", 10))
        chain.add_retriever(LowQualityBackup())

        context = RetrievalContext(
            query="q",
            strategy=RetrievalStrategy.FALLBACK,
            min_quality=0.5,
        )

        result = await chain.retrieve(context)

        # 修复前:result.source == "low_q_backup", result.memories 非空(BUG)
        # 修复后:跳过低质量备用,返回 fallback_exhausted
        assert result.source == "fallback_exhausted"
        assert result.memories == []


# ============================================================
# BUG#6 — asyncio.get_event_loop() 弃用
# ============================================================


class TestBug6AsyncioGetEventLoopDeprecated:
    """BUG#6: 用 asyncio.get_event_loop().time() 计时,Python 3.12+ 弃用,
    应改用 time.monotonic()。"""

    def test_no_asyncio_get_event_loop_time_in_chain_module(self):
        import neurova.agent.memory_retrieval_chain as mod

        src = inspect.getsource(mod)
        assert "asyncio.get_event_loop().time()" not in src, (
            "memory_retrieval_chain.py 仍使用 asyncio.get_event_loop().time(),"
            "应改用 time.monotonic()"
        )

    def test_no_asyncio_get_event_loop_time_in_adapters_module(self):
        import neurova.agent.retriever_adapters as mod

        src = inspect.getsource(mod)
        assert "asyncio.get_event_loop().time()" not in src, (
            "retriever_adapters.py 仍使用 asyncio.get_event_loop().time(),"
            "应改用 time.monotonic()"
        )

    def test_chain_module_imports_time(self):
        """memory_retrieval_chain 应导入 time 模块。"""
        import neurova.agent.memory_retrieval_chain as mod

        src = inspect.getsource(mod)
        assert "import time" in src

    def test_adapters_module_imports_time(self):
        """retriever_adapters 应导入 time 模块。"""
        import neurova.agent.retriever_adapters as mod

        src = inspect.getsource(mod)
        assert "import time" in src


# ============================================================
# BUG#7 — MoERetrieverAdapter.routing_score 硬编码
# ============================================================


class TestBug7RoutingScoreHardcoded:
    """BUG#7: routing_score = 0.8 硬编码,应提取为类常量
    DEFAULT_ROUTING_SCORE。"""

    def test_default_routing_score_class_constant_exists(self):
        assert hasattr(MoERetrieverAdapter, "DEFAULT_ROUTING_SCORE")
        assert MoERetrieverAdapter.DEFAULT_ROUTING_SCORE == 0.8

    def test_get_quality_score_uses_constant(self):
        """get_quality_score 应引用类常量,而非字面量 0.8。"""
        src = inspect.getsource(MoERetrieverAdapter.get_quality_score)
        # 不应再出现裸的字面量 0.8 作为 routing_score
        assert "routing_score = 0.8" not in src
        # 应使用类常量
        assert "DEFAULT_ROUTING_SCORE" in src

    def test_get_quality_score_value_unchanged(self):
        """质量分公式：数量 50% + 路由 20% + 相关性 30%。

        修复前：0.7 * count + 0.3 * routing（数量多即虚高 0.94，无视相关性）；
        修复后：相关性 0 时不再虚高（0.66），相关命中可获更高分。
        """
        adapter = MoERetrieverAdapter.__new__(MoERetrieverAdapter)
        # 5 条结果 → count_score = 1.0；内容与 query 无关键词重叠 → relevance = 0
        memories = [{"content": f"m{i}"} for i in range(5)]
        quality = adapter.get_quality_score(memories, "query")
        # 0.5 * 1.0 + 0.2 * 0.8 + 0.3 * 0.0 = 0.66
        assert abs(quality - 0.66) < 1e-9
