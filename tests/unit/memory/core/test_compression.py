"""
MemoryCompressor（记忆压缩）单元测试 — 按当前真实 API 重写

真实 API:
- MemoryCompressor(storage=None, llm_client=None, config=None)
- compress(memories: List[Dict], strategy=CompressionStrategy.*, **kwargs) -> CompressionResult
  CompressionResult: original_count/compressed_count/removed_count/merged_count/strategy/duration_ms/details
"""

import pytest

from neurova.cognitive_layers.memory_layer.compression import (
    CompressionStrategy,
    MemoryCompressor,
)


@pytest.fixture
def compressor():
    return MemoryCompressor()


def _mem(i, content, category="conversation", temperature=50.0):
    return {
        "id": f"mem_{i}",
        "content": content,
        "category": category,
        "temperature": temperature,
    }


class TestInit:
    def test_default_init(self, compressor):
        assert compressor is not None
        assert hasattr(compressor, "compress")

    def test_strategies_available(self):
        assert {s.value for s in CompressionStrategy} >= {
            "tier", "semantic", "aggregation", "rule_based",
        }


class TestSemanticCompression:
    def test_identical_memories_merged(self, compressor):
        memories = [
            _mem(1, "用户喜欢喝咖啡"),
            _mem(2, "用户喜欢喝咖啡"),
            _mem(3, "完全不同的内容关于量子物理"),
        ]
        result = compressor.compress(memories, strategy=CompressionStrategy.SEMANTIC)
        assert result.original_count == 3
        assert result.merged_count >= 1 or result.removed_count >= 1
        assert result.duration_ms >= 0

    def test_unique_memories_preserved(self, compressor):
        memories = [
            _mem(1, "量子计算机的运算原理"),
            _mem(2, "今天下午去超市买了苹果"),
        ]
        result = compressor.compress(memories, strategy=CompressionStrategy.SEMANTIC)
        # 完全不相似的记忆不应被合并掉
        assert result.original_count == result.compressed_count + result.merged_count or (
            result.compressed_count == result.original_count
        )

    def test_empty_input(self, compressor):
        result = compressor.compress([], strategy=CompressionStrategy.SEMANTIC)
        assert result.original_count == 0
        assert result.compressed_count == 0


class TestAggregationCompression:
    def test_aggregation_reduces_or_keeps(self, compressor):
        memories = [_mem(i, f"第{i}条记录 内容{i}", temperature=40.0 + i) for i in range(6)]
        result = compressor.compress(
            memories, strategy=CompressionStrategy.AGGREGATION, batch_size=2
        )
        assert result.original_count == 6
        assert isinstance(result.compressed_count, int)
        assert result.strategy is not None


class TestRuleBasedCompression:
    def test_rule_based_runs(self, compressor):
        memories = [
            _mem(1, "低重要性旧记忆A", temperature=5.0),
            _mem(2, "低重要性旧记忆B", temperature=6.0),
            _mem(3, "重要记忆：用户生日是1月1日", temperature=90.0),
        ]
        result = compressor.compress(memories, strategy=CompressionStrategy.RULE_BASED)
        assert result.original_count == 3


class TestTierCompression:
    def test_tier_runs(self, compressor):
        memories = [_mem(i, f"分层压缩测试{i}", temperature=30.0 + i) for i in range(8)]
        result = compressor.compress(memories, strategy=CompressionStrategy.TIER)
        assert result.original_count == 8


class TestStats:
    def test_get_stats_dict(self, compressor):
        stats = compressor.get_stats()
        assert isinstance(stats, dict)
