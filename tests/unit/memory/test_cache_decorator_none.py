"""
单元测试 - cached 装饰器对合法 None 的处理

TDD RED 阶段: 验证 cached() 装饰器能正确缓存返回 None 的函数结果。
对应断点 M-6: cached() 装饰器合法 None 永不缓存。

测试目标:
1. 返回 None 的函数被装饰后,第二次调用应命中缓存(不重新执行)。
2. 装饰器能区分"键不存在(miss)"与"键存在但值是 None"。
3. 非 None 结果的缓存行为不被破坏(回归测试)。
"""
import pytest

from neurova.memory.core.cache import cached, reset_global_cache, get_global_cache


@pytest.fixture(autouse=True)
def _isolate_global_cache():
    """每个测试前后重置全局缓存,确保统计与状态隔离。"""
    reset_global_cache()
    yield
    reset_global_cache()


class TestCachedDecoratorHandlesNone:
    """验证 cached 装饰器对 None 返回值的处理。"""

    def test_cached_none_result_is_cached(self):
        """返回 None 的函数,第二次调用不应重新执行(应命中缓存)。"""
        call_count = [0]  # 用 list 实现可变闭包计数器

        @cached()
        def returns_none():
            call_count[0] += 1
            return None

        # 第一次调用:miss,执行函数,结果(None)应被缓存
        result1 = returns_none()
        assert result1 is None
        assert call_count[0] == 1, "首次调用应执行函数一次"

        # 第二次调用:应命中缓存,不再执行函数
        result2 = returns_none()
        assert result2 is None
        assert call_count[0] == 1, "None 结果应被缓存,第二次调用不应重新执行函数"

    def test_cached_distinguishes_miss_from_cached_none(self):
        """装饰器应能区分'未缓存'与'已缓存 None'。

        通过缓存统计验证:
        - 首次调用产生一次 miss(键不存在)
        - 第二次调用产生一次 hit(键存在,值为 None)
        """
        call_count = [0]

        @cached()
        def returns_none():
            call_count[0] += 1
            return None

        cache = get_global_cache()

        # 首次调用:应为 miss
        returns_none()
        stats_after_first = cache.get_stats()
        assert stats_after_first["misses"] >= 1, "首次调用应记为 miss"
        assert stats_after_first["hits"] == 0, "首次调用不应有 hit"

        # 第二次调用:应为 hit(已缓存 None)
        returns_none()
        stats_after_second = cache.get_stats()
        assert stats_after_second["hits"] >= 1, "第二次调用应命中缓存(已缓存 None)"
        assert call_count[0] == 1, "函数不应被重复执行"

    def test_cached_non_none_still_works(self):
        """回归测试: 非 None 结果的缓存行为不被破坏。"""
        call_count = [0]

        @cached()
        def returns_value():
            call_count[0] += 1
            return {"data": "value"}

        # 第一次调用:miss,执行函数
        result1 = returns_value()
        assert result1 == {"data": "value"}
        assert call_count[0] == 1

        # 第二次调用:hit,不执行函数,返回缓存对象
        result2 = returns_value()
        assert result2 == {"data": "value"}
        assert result2 is result1, "第二次调用应返回同一缓存对象"
        assert call_count[0] == 1, "非 None 结果也应只执行一次"
