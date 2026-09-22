"""
Token 估算单一事实源回归测试

历史上 4 个文件各有一套 token 估算算法（差异可达 1x-8x）。统一到
neurova.context.token_estimator 后，三处入口必须给出**完全相同的数**：
1. TokenEstimator（默认档：tiktoken o200k 精确计数）
2. context_pool.ContextPoolUtils.estimate_tokens
3. context.compressor.ContextCompressor._estimate_tokens

注：本文件旧版以 `BALANCED` 为"统一定义"比对——那是会低估 20 倍的口径
（见 test_token_estimator_calibration.py），现已降为无 tokenizer 时的回退档，
不再是判据口径。比对基准改为默认档。
"""

import pytest
from neurova.context.token_estimator import TokenEstimator, estimate_tokens
from neurova.context.compressor import ContextCompressor


def _tokens(text: str):
    return (
        TokenEstimator().estimate(text),
        estimate_tokens(text),
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
        """中文估算应为正数且不超过字符数的 2 倍（精确计数的上界语义）"""
        text = "你好世界"
        estimate = TokenEstimator().estimate(text)
        assert 0 < estimate <= len(text) * 2

    def test_longer_text_monotonic(self):
        est = TokenEstimator().estimate
        short = est("短文本")
        long = est("这是一段明显更长的文本内容，包含更多的信息量与字符。")
        assert long > short
