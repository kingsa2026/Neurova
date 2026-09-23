"""
Token 估算单一事实源回归测试

历史上 4 个文件各有一套 token 估算算法（差异可达 1x-8x）。统一到
neurova.context.token_estimator 后，所有现存的委托点必须给出**完全相同的数**：
1. TokenEstimator（默认档：tiktoken o200k 精确计数）
2. estimate_tokens（全仓统一入口）
3. context.collector.ContextCollector._estimate_tokens
4. context.semantic_drawer.SemanticMatchDrawer._estimate_tokens

注：本文件旧版以 `BALANCED` 为"统一定义"比对——那是会低估 20 倍的口径
（见 test_token_estimator_calibration.py），现已降为无 tokenizer 时的回退档，
不再是判据口径。比对基准改为默认档。

B6-10 批次 C：旧版第三个探针指向 `context.compressor.ContextCompressor._estimate_tokens`
（已随压缩面收口整模块退役）。**探针不删、改指存活委托点**——被锁的契约是
「全仓只有一把 token 尺子」，它不因某一个委托点退役而失效；反之，只删探针
会让这条契约在剩余委托点之间失去守卫。
"""

import pytest
from neurova.context.token_estimator import TokenEstimator, estimate_tokens
from neurova.context.collector import ContextCollector
from neurova.context.semantic_drawer import SemanticMatchDrawer


def _tokens(text: str):
    return (
        TokenEstimator().estimate(text),
        estimate_tokens(text),
        ContextCollector._estimate_tokens(text),
        SemanticMatchDrawer._estimate_tokens(text),
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
