"""
Token 估算一致性回归测试

历史上 4 个文件各有一套 token 估算算法（差异可达 1x-8x），统一到
neurova.context.token_estimator.TokenEstimator 后必须保持一致：
1. TokenEstimator（BALANCED 策略，统一定义）
2. context_pool.ContextPoolUtils.estimate_tokens
3. context.compressor.ContextCompressor._estimate_tokens
"""

import pytest
from neurova.context.token_estimator import TokenEstimator, EstimationStrategy
from neurova.context_pool import ContextPoolUtils
from neurova.context.compressor import ContextCompressor


def _tokens(text: str):
    return (
        TokenEstimator(EstimationStrategy.BALANCED).estimate(text),
        ContextPoolUtils.estimate_tokens(text),
        ContextCompressor._estimate_tokens(text),
    )


def _assert_consistent(tokens, label: str):
    max_t, min_t = max(tokens), min(tokens)
    ratio = (max_t / min_t) if min_t > 0 else float("inf")
    assert ratio <= 1.01, f"{label} token 估算不一致，差异倍数: {ratio:.2f}x ({tokens})"


class TestTokenEstimationConsistency:
    def test_chinese_text(self):
        tokens = _tokens("这是一个测试文本，包含中文字符。")
        _assert_consistent(tokens, "中文")

    def test_english_text(self):
        tokens = _tokens("This is a test text with English words.")
        _assert_consistent(tokens, "英文")

    def test_mixed_text(self):
        tokens = _tokens("Hello 你好 World 世界 Test 测试")
        _assert_consistent(tokens, "混合")


class TestBudgetControlPredictability:
    def test_chinese_estimate_positive_and_bounded(self):
        """中文估算应为正数且不超过字符数的 2 倍（BALANCED 策略语义）"""
        text = "你好世界"
        estimate = TokenEstimator(EstimationStrategy.BALANCED).estimate(text)
        assert 0 < estimate <= len(text) * 2

    def test_longer_text_monotonic(self):
        est = TokenEstimator(EstimationStrategy.BALANCED).estimate
        short = est("短文本")
        long = est("这是一段明显更长的文本内容，包含更多的信息量与字符。")
        assert long > short
