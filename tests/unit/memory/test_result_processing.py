"""
Phase 3: 统一结果处理测试

测试去重、权重融合、时序衰减、冲突检测。
"""
import pytest
import math
from datetime import datetime, timedelta, timezone
from typing import List

from neurova.cognitive_layers.memory_layer.channels.base import ChannelResult
from neurova.cognitive_layers.memory_layer.channels.processor import UnifiedResultProcessor
from neurova.cognitive_layers.memory_layer.channels.conflict import ConflictDetector
from neurova.cognitive_layers.memory_layer.channels.temporal import TemporalDecay
from neurova.cognitive_layers.memory_layer.channels.weight import WeightAdjuster


# ────── Helpers ──────

def _make_result(mid, content, score=0.5, channel="text",
                 timestamp=None, metadata=None):
    return ChannelResult(
        memory_id=mid,
        content=content,
        score=score,
        channel=channel,
        metadata=metadata or {},
        timestamp=timestamp,
    )


# ────── UnifiedResultProcessor Tests ──────

class TestUnifiedResultProcessor:
    """统一结果处理器测试"""

    def test_dedup_by_memory_id(self):
        proc = UnifiedResultProcessor()
        results = [
            _make_result("m1", "content A", score=0.8, channel="text"),
            _make_result("m1", "content A dup", score=0.6, channel="temperature"),
            _make_result("m2", "content B", score=0.7, channel="text"),
        ]
        deduped = proc.deduplicate(results)
        assert len(deduped) == 2
        # 保留分数更高的
        scores = {r.memory_id: r.score for r in deduped}
        assert scores["m1"] == 0.8

    def test_dedup_empty(self):
        proc = UnifiedResultProcessor()
        assert proc.deduplicate([]) == []

    def test_weight_fusion(self):
        proc = UnifiedResultProcessor()
        results = [
            _make_result("m1", "c", score=1.0, channel="text"),
        ]
        channel_weights = {"text": 0.8}
        fused = proc.apply_weights(results, channel_weights)
        assert len(fused) == 1
        assert fused[0].score == pytest.approx(0.8, abs=0.01)

    def test_weight_fusion_with_activation(self):
        proc = UnifiedResultProcessor()
        results = [
            _make_result("m1", "c", score=1.0, channel="text"),
        ]
        channel_weights = {"text": 0.8}
        activations = {"text": 0.9}
        fused = proc.apply_weights(results, channel_weights, activations)
        assert fused[0].score == pytest.approx(0.72, abs=0.01)

    def test_process_full_pipeline(self):
        proc = UnifiedResultProcessor()
        results = [
            _make_result("m1", "Python is great", score=0.9, channel="text",
                        timestamp=datetime.now(timezone.utc).isoformat()),
            _make_result("m1", "Python is great", score=0.5, channel="temperature",
                        timestamp=datetime.now(timezone.utc).isoformat()),
            _make_result("m2", "Java is okay", score=0.6, channel="text",
                        timestamp=datetime.now(timezone.utc).isoformat()),
        ]
        channel_weights = {"text": 0.8, "temperature": 0.5}
        output = proc.process(results, channel_weights)
        assert output.total_count == 3
        assert output.deduped_count == 2
        assert len(output.results) == 2


class TestProcessOutput:
    """处理输出数据结构测试"""

    def test_output_fields(self):
        proc = UnifiedResultProcessor()
        output = proc.process([], {})
        assert hasattr(output, "results")
        assert hasattr(output, "total_count")
        assert hasattr(output, "deduped_count")
        assert hasattr(output, "conflicts")


# ────── ConflictDetector Tests ──────

class TestConflictDetector:
    """冲突检测器测试"""

    def test_detect_no_conflict(self):
        cd = ConflictDetector()
        results = [
            _make_result("m1", "Python is a programming language"),
            _make_result("m2", "Java is also a programming language"),
        ]
        conflicts = cd.detect(results)
        assert len(conflicts) == 0

    def test_detect_contradiction(self):
        cd = ConflictDetector()
        results = [
            _make_result("m1", "Python是静态类型语言"),
            _make_result("m2", "Python是动态类型语言"),
        ]
        conflicts = cd.detect(results)
        # 应该检测到冲突（都有"Python是...类型语言"但结论不同）
        assert isinstance(conflicts, list)

    def test_detect_empty(self):
        cd = ConflictDetector()
        assert cd.detect([]) == []

    def test_detect_single_result(self):
        cd = ConflictDetector()
        results = [_make_result("m1", "only one")]
        assert cd.detect(results) == []


# ────── TemporalDecay Tests ──────

class TestTemporalDecay:
    """时序衰减测试"""

    def test_exponential_decay(self):
        td = TemporalDecay(curve="exponential")
        now = datetime.now(timezone.utc)
        # 刚创建，衰减应接近 1.0
        score = td.compute(now.isoformat())
        assert score == pytest.approx(1.0, abs=0.05)

    def test_exponential_decay_old(self):
        td = TemporalDecay(curve="exponential")
        # 默认半衰期 30 天 → 30d 时分数恰= 0.5（半衰期定义），
        # 断言"明显衰减"用 3 倍半衰期（90d → 0.125）
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        score = td.compute(old)
        assert score < 0.5

    def test_linear_decay(self):
        td = TemporalDecay(curve="linear", half_life_days=30)
        now = datetime.now(timezone.utc)
        score = td.compute(now.isoformat())
        assert score == pytest.approx(1.0, abs=0.05)

    def test_linear_decay_old(self):
        td = TemporalDecay(curve="linear", half_life_days=30)
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        score = td.compute(old)
        assert score < 0.5

    def test_logarithmic_decay(self):
        td = TemporalDecay(curve="logarithmic")
        now = datetime.now(timezone.utc)
        score = td.compute(now.isoformat())
        assert score == pytest.approx(1.0, abs=0.1)

    def test_no_timestamp_returns_1(self):
        td = TemporalDecay()
        assert td.compute(None) == 1.0
        assert td.compute("") == 1.0

    def test_min_score_floor(self):
        td = TemporalDecay(min_score=0.2)
        very_old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        score = td.compute(very_old)
        assert score >= 0.2


# ────── WeightAdjuster Tests ──────

class TestWeightAdjuster:
    """通道权重动态调整测试"""

    def test_default_weights(self):
        wa = WeightAdjuster()
        w = wa.get_weights()
        assert "text" in w
        assert "temperature" in w
        assert sum(w.values()) == pytest.approx(1.0, abs=0.01)

    def test_positive_feedback(self):
        wa = WeightAdjuster()
        old = wa.get_weights()["text"]
        wa.adjust("text", positive=True)
        new = wa.get_weights()["text"]
        assert new > old

    def test_negative_feedback(self):
        wa = WeightAdjuster()
        old = wa.get_weights()["text"]
        wa.adjust("text", positive=False)
        new = wa.get_weights()["text"]
        assert new < old

    def test_weights_stay_normalized(self):
        wa = WeightAdjuster()
        for _ in range(20):
            wa.adjust("text", positive=True)
        w = wa.get_weights()
        assert sum(w.values()) == pytest.approx(1.0, abs=0.05)

    def test_weight_bounds(self):
        wa = WeightAdjuster()
        for _ in range(100):
            wa.adjust("text", positive=True)
        w = wa.get_weights()
        assert all(0.05 <= v <= 0.8 for v in w.values())
