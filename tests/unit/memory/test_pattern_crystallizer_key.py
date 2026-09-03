"""
PatternCrystallizer._extract_pattern_key 模式键提取测试

复现 P1.2 BUG:
  _extract_pattern_key 仅取 context[:50].strip(),
  导致不同语义但前 50 字符相同的上下文被错误合并为同一模式。

  例如:
    "请帮我搜索 Python 编程相关的资料，我需要了解异步编程" (前50字符)
    "请帮我搜索 Python 编程相关的资料，我需要了解机器学习" (前50字符)
  这两个不同意图会被合并为同一模式键。

修复目标:
  _extract_pattern_key 应基于语义关键词而非位置前缀,
  能区分前缀相同但语义不同的上下文。
"""

import pytest
from unittest.mock import MagicMock

from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer


class TestExtractPatternKey:
    """验证 _extract_pattern_key 的语义区分能力"""

    def _make_crystallizer(self):
        """创建测试用 PatternCrystallizer"""
        mock_engine = MagicMock()
        return PatternCrystallizer(engine=mock_engine)

    def test_different_semantics_different_keys(self):
        """前 50 字符相同但语义不同的上下文必须产生不同的模式键"""
        c = self._make_crystallizer()

        ctx1 = "请帮我搜索 Python 编程相关的资料，我需要了解异步编程的最佳实践"
        ctx2 = "请帮我搜索 Python 编程相关的资料，我需要了解机器学习的算法原理"

        key1 = c._extract_pattern_key(ctx1)
        key2 = c._extract_pattern_key(ctx2)

        # BUG: 当前实现两者前 50 字符相同, 会返回相同 key
        assert key1 != key2, (
            f"语义不同的上下文必须产生不同模式键\n"
            f"  ctx1: {ctx1}\n"
            f"  ctx2: {ctx2}\n"
            f"  key1: {key1}\n"
            f"  key2: {key2}"
        )

    def test_similar_semantics_similar_keys(self):
        """语义相似的上下文应产生相同或相似的模式键 (避免过度碎片化)"""
        c = self._make_crystallizer()

        # 仅标点/空白差异, 语义相同
        ctx1 = "搜索 Python 异步编程资料"
        ctx2 = "搜索Python异步编程资料"

        key1 = c._extract_pattern_key(ctx1)
        key2 = c._extract_pattern_key(ctx2)

        assert key1 == key2, (
            "仅空白差异的语义相同上下文应产生相同模式键\n"
            f"  key1: {key1}\n  key2: {key2}"
        )

    def test_empty_context(self):
        """空上下文不应崩溃"""
        c = self._make_crystallizer()
        key = c._extract_pattern_key("")
        assert isinstance(key, str)
        assert len(key) >= 0  # 不崩溃即可

    def test_short_context(self):
        """短上下文 (少于关键词阈值) 不应崩溃"""
        c = self._make_crystallizer()
        key = c._extract_pattern_key("搜索")
        assert isinstance(key, str)

    def test_key_is_deterministic(self):
        """相同上下文必须产生相同模式键 (确定性)"""
        c = self._make_crystallizer()
        ctx = "帮我查询北京今天的天气情况"
        key1 = c._extract_pattern_key(ctx)
        key2 = c._extract_pattern_key(ctx)
        assert key1 == key2

    def test_key_not_just_prefix(self):
        """模式键不应是简单的前缀截取 (必须有语义提取)"""
        c = self._make_crystallizer()
        ctx = "请帮我搜索 Python 编程相关的资料，我需要了解异步编程" * 3
        key = c._extract_pattern_key(ctx)

        # 模式键不应等于 context[:50]
        assert key != ctx[:50].strip(), (
            "模式键不应是简单前缀截取, 必须有语义提取逻辑"
        )

    def test_chinese_and_english_mixed(self):
        """中英文混合上下文应正确处理"""
        c = self._make_crystallizer()

        ctx1 = "search Python 异步编程"
        ctx2 = "search Python 机器学习"

        key1 = c._extract_pattern_key(ctx1)
        key2 = c._extract_pattern_key(ctx2)

        assert key1 != key2, "中英文混合的不同语义必须产生不同模式键"


class TestPatternCrystallizerObserve:
    """验证 observe 行为不被错误合并"""

    def _make_crystallizer(self):
        mock_engine = MagicMock()
        return PatternCrystallizer(engine=mock_engine)

    def test_different_semantics_not_merged(self):
        """不同语义的观察不应被合并到同一 buffer key"""
        c = self._make_crystallizer()

        # 两个语义不同但前 50 字符相同的上下文
        ctx1 = "请帮我搜索 Python 编程相关的资料，我需要了解异步编程的最佳实践和技巧"
        ctx2 = "请帮我搜索 Python 编程相关的资料，我需要了解机器学习的算法原理和应用"

        c.observe(tool_name="search", context=ctx1, success=True)
        c.observe(tool_name="search", context=ctx2, success=True)

        # buffer 应有 2 个不同的 key
        assert len(c._buffer) == 2, (
            f"不同语义的观察应分开存储, 实际 buffer 大小: {len(c._buffer)}\n"
            f"buffer keys: {list(c._buffer.keys())}"
        )
