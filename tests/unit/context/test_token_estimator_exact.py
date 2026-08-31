"""
P1-1② 期② slice A — TokenEstimator EXACT 策略测试

EXACT：tiktoken 精确计数（o200k_base），替代字符比例估算；
tiktoken 不可用时回退 BALANCED 语义（比例估算），不抛异常。
"""

import pytest

from neurova.context.token_estimator import EstimationStrategy, TokenEstimator


class TestExactStrategy:
    def test_strategy_enum_has_exact(self):
        assert EstimationStrategy.EXACT.value == "exact"

    def test_exact_matches_tiktoken_for_english(self):
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        text = "The quick brown fox jumps over the lazy dog."
        estimator = TokenEstimator(EstimationStrategy.EXACT)
        assert estimator.estimate(text) == len(enc.encode(text))

    def test_exact_matches_tiktoken_for_chinese(self):
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        text = "今天天气怎么样？帮我查一下北京的天气预报。"
        estimator = TokenEstimator(EstimationStrategy.EXACT)
        assert estimator.estimate(text) == len(enc.encode(text))

    def test_exact_empty_text_zero(self):
        estimator = TokenEstimator(EstimationStrategy.EXACT)
        assert estimator.estimate("") == 0

    def test_exact_fallback_on_tiktoken_failure(self, monkeypatch):
        """tiktoken 缺失/失败 → 回退 BALANCED 语义（比例估算），不抛异常。"""
        import builtins

        estimator = TokenEstimator(EstimationStrategy.EXACT)

        real_import = builtins.__import__

        def blocked_import(name, *a, **kw):
            if name == "tiktoken" or name.startswith("tiktoken."):
                raise ImportError("tiktoken blocked for test")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        # 强制重新探测（清掉懒加载缓存）
        estimator._tiktoken_encoder = None
        estimator._tiktoken_failed = False
        value = estimator.estimate("hello world")
        assert value > 0  # BALANCED 语义：英文按词比例估算
        assert estimator._tiktoken_failed is True

    def test_exact_more_accurate_than_balanced_for_code(self):
        """代码/符号密集文本：EXACT 与 BALANCED 差异显著（EXACT 的意义所在）。"""
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        code = "def foo(x): return [i**2 for i in range(x)] if x else {'k': None}\n" * 3
        exact = TokenEstimator(EstimationStrategy.EXACT).estimate(code)
        balanced = TokenEstimator(EstimationStrategy.BALANCED).estimate(code)
        assert exact == len(enc.encode(code))
        # 两者不该完全相等（否则 EXACT 没有区分度）
        assert exact != balanced

    def test_batch_estimate_exact(self):
        estimator = TokenEstimator(EstimationStrategy.EXACT)
        assert estimator.estimate_batch(["a b c", "你好世界"]) == [
            estimator.estimate("a b c"),
            estimator.estimate("你好世界"),
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
