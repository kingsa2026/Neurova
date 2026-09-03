"""
单元测试 - MemoryCache 对合法 None 的区分(get_or_set / get_many)

TDD RED 阶段: 验证 MemoryCache 的 get_or_set 与 get_many 能正确处理"合法 None"。
对应遗留问题 L-2: M-6 已修复 @cached 装饰器(用 _MISSING 哨兵区分 miss 与
cached None),但同源的 get_or_set / get_many 仍用 `if value is None` 判断,
导致合法 None 永不缓存、get_many 漏掉合法 None 的键。

测试目标:
1. get_or_set 缓存合法 None(factory 只调用一次)。
2. get_or_set 通过 stats 区分"键不存在(miss)"与"键存在但值为 None"。
3. get_many 返回包含合法 None 的键值对。
4. get_many 不包含真正 miss 的键。
5. 非 None 值仍正常工作(回归测试)。

说明:
- 直接实例化 MemoryCache(不走全局缓存),保证每个测试状态隔离。
- 复用模块级 _MISSING 哨兵做 miss 判定,与 @cached 装饰器(M-6)保持一致。
"""
import pytest

from neurova.memory.core.cache import MemoryCache, _MISSING


class TestGetOrSetHandlesNone:
    """验证 get_or_set 对合法 None 的处理。"""

    def test_get_or_set_caches_legitimate_none(self):
        """get_or_set 应缓存合法 None:第二次调用不应再次执行 factory。"""
        cache = MemoryCache()
        call_count = [0]

        def factory_returns_none():
            call_count[0] += 1
            return None

        # 首次:miss,执行 factory,结果 None 应被缓存
        result1 = cache.get_or_set("k_none", factory_returns_none)
        assert result1 is None, "首次调用应返回 factory 的结果 None"
        assert call_count[0] == 1, "首次调用应执行 factory 一次"

        # 再次:应命中缓存(合法 None 已被缓存),不再执行 factory
        result2 = cache.get_or_set("k_none", factory_returns_none)
        assert result2 is None, "再次调用应返回已缓存的 None"
        assert call_count[0] == 1, "合法 None 已缓存,factory 不应被再次调用"

    def test_get_or_set_distinguishes_miss_from_cached_none(self):
        """get_or_set 应通过 stats 区分"未缓存"与"已缓存 None"。

        - 首次调用产生一次 miss(键不存在)
        - 再次调用产生一次 hit(键存在,值为 None)
        """
        cache = MemoryCache()

        def factory_returns_none():
            return None

        # 首次:miss
        cache.get_or_set("k_none", factory_returns_none)
        stats_after_first = cache.get_stats()
        assert stats_after_first["misses"] == 1, "首次调用应记为 miss"
        assert stats_after_first["hits"] == 0, "首次调用不应有 hit"

        # 再次:应为 hit(已缓存 None)
        cache.get_or_set("k_none", factory_returns_none)
        stats_after_second = cache.get_stats()
        assert stats_after_second["hits"] == 1, "再次调用应命中缓存(已缓存 None)"
        assert stats_after_second["misses"] == 1, "misses 不应增长"


class TestGetManyHandlesNone:
    """验证 get_many 对合法 None 的处理。"""

    def test_get_many_includes_legitimate_none(self):
        """get_many 返回的字典应包含值为合法 None 的键。"""
        cache = MemoryCache()

        # 预置一个合法 None 与一个非 None 值
        cache.set("k_none", None)
        cache.set("k_str", "hello")

        result = cache.get_many(["k_none", "k_str"])

        # 关键断言:k_none 必须出现在结果中,且值为 None
        assert "k_none" in result, "合法 None 的键不应被 get_many 漏掉"
        assert result["k_none"] is None, "k_none 的值应为 None"
        assert result["k_str"] == "hello", "非 None 值应正常返回"

    def test_get_many_excludes_real_misses(self):
        """get_many 不应包含真正不存在的键。"""
        cache = MemoryCache()

        cache.set("k_exists", 42)

        result = cache.get_many(["k_exists", "k_missing"])

        assert "k_exists" in result, "存在的键应在结果中"
        assert result["k_exists"] == 42
        assert "k_missing" not in result, "不存在的键不应出现在结果中"


class TestNonNoneRegression:
    """回归测试: 非 None 值的既有行为不应被破坏。"""

    def test_get_or_set_non_none_value(self):
        """get_or_set 对非 None 值应保持原有缓存语义(factory 仅调用一次)。"""
        cache = MemoryCache()
        call_count = [0]

        def factory_returns_dict():
            call_count[0] += 1
            return {"data": "value"}

        result1 = cache.get_or_set("k_dict", factory_returns_dict)
        assert result1 == {"data": "value"}
        assert call_count[0] == 1

        result2 = cache.get_or_set("k_dict", factory_returns_dict)
        assert result2 == {"data": "value"}
        assert result2 is result1, "应返回同一缓存对象"
        assert call_count[0] == 1, "非 None 值也应只执行一次 factory"
