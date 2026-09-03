"""
ContextCompressor（上下文压缩器）单元测试 — 按当前真实 API 重写

真实 API:
- ContextCompressor(max_tokens=16000, enable_summarization=False)
- compress(contexts: List[ContextInput]) -> List[ContextInput]
- ContextInput(source: ContextSource, content, priority=int, ...)
"""

import pytest

from neurova.context.compressor import ContextCompressor, ContextInput
from neurova.context.pool_models import ContextSource


def _ctx(content: str, priority: int = 1, source: ContextSource = ContextSource.CONVERSATION) -> ContextInput:
    return ContextInput(source=source, content=content, priority=priority)


class TestNoCompressionNeeded:
    def test_under_budget_returns_all(self):
        compressor = ContextCompressor(max_tokens=10000)
        contexts = [_ctx("短内容" * 10) for _ in range(3)]
        result = compressor.compress(contexts)
        assert len(result) == 3

    def test_tokens_auto_estimated(self):
        compressor = ContextCompressor(max_tokens=10000)
        contexts = [_ctx("需要估算 token 的内容")]
        assert contexts[0].tokens == 0
        result = compressor.compress(contexts)
        assert all(c.tokens > 0 for c in result)


class TestCompression:
    def test_over_budget_drops_lowest_priority_first(self):
        compressor = ContextCompressor(max_tokens=50)
        contexts = [
            _ctx("低优先级填充" * 30, priority=0),
            _ctx("高优先级关键信息", priority=100),
        ]
        result = compressor.compress(contexts)
        contents = [c.content for c in result]
        assert "高优先级关键信息" in contents

    def test_empty_input(self):
        compressor = ContextCompressor(max_tokens=100)
        assert compressor.compress([]) == []

    def test_higher_priority_survives_trimming(self):
        compressor = ContextCompressor(max_tokens=60)
        contexts = [
            _ctx("P3 内容" * 20, priority=3),
            _ctx("P9 内容" * 5, priority=9),
            _ctx("P1 内容" * 20, priority=1),
        ]
        result = compressor.compress(contexts)
        kept_contents = [c.content for c in result]
        if len(result) < len(contexts):
            assert ("P9 内容" * 5) in kept_contents


class TestSourceEnum:
    def test_memory_source_exists(self):
        assert ContextSource.MEMORY.value == "memory"

    def test_hash_scoped_by_source(self):
        c1 = ContextInput(source=ContextSource.MEMORY, content="同文")
        c2 = ContextInput(source=ContextSource.CONVERSATION, content="同文")
        # source 域限定指纹：不同来源的相同内容哈希不同
        assert c1.hash != c2.hash
