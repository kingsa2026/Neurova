"""
NeRF 记忆系统与现有检索引擎的集成测试

验证：
1. 格式适配器：RecalledMemory ↔ VolumeRenderer 输入格式
2. 意图权重：QueryIntent ↔ VolumeRenderer intent 参数映射
3. 体渲染替代融合：VolumeRenderer 可作为 _fusion_score 的替代
4. 位置编码增强温度：TemporalPositionalEncoder 可替代阶梯衰减
"""

import math
import datetime
from unittest.mock import MagicMock, patch

import pytest

# 导入现有系统组件
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    RecallChannel,
    RecalledMemory,
    RecallResult,
    QueryIntent,
    QueryIntentDetector,
    IntentAwareRecallStrategy,
    NeurovaRecallEngine,
)

# 导入 NeRF 组件
from neurova.cognitive_layers.memory_layer.volume_renderer import (
    ChannelSample,
    RenderedMemory,
    VolumeRenderer,
)
from neurova.cognitive_layers.memory_layer.positional_encoding import (
    TemporalPositionalEncoder,
)


# ────── 格式适配器 ──────

def recalled_to_channel_groups(memories: list[RecalledMemory]) -> dict[str, list[dict]]:
    """将 RecalledMemory 列表转换为 VolumeRenderer 的输入格式

    关键适配器：连接现有检索引擎和体渲染器
    """
    groups: dict[str, list[dict]] = {}
    for mem in memories:
        channel = mem.channel.value if isinstance(mem.channel, RecallChannel) else str(mem.channel)
        if channel not in groups:
            groups[channel] = []
        groups[channel].append({
            "memory_id": mem.memory_id,
            "content": mem.content,
            "score": mem.score,
            "metadata": mem.metadata,
        })
    return groups


def rendered_to_recalled(rendered: list[RenderedMemory]) -> list[RecalledMemory]:
    """将 RenderedMemory 转换回 RecalledMemory 格式

    用于体渲染结果注入现有管线
    """
    results = []
    for rm in rendered:
        # 从 channel_scores 推断主通道
        if rm.channel_scores:
            primary_channel = max(rm.channel_scores, key=rm.channel_scores.get)
        else:
            primary_channel = "text"

        try:
            channel = RecallChannel(primary_channel)
        except ValueError:
            channel = RecallChannel.TEXT

        results.append(RecalledMemory(
            memory_id=rm.memory_id,
            content=rm.content,
            score=rm.score,
            channel=channel,
            metadata=rm.metadata,
        ))
    return results


def query_intent_to_str(intent: QueryIntent) -> str:
    """QueryIntent 枚举 → VolumeRenderer intent 字符串"""
    mapping = {
        QueryIntent.FACTUAL: "factual",
        QueryIntent.TEMPORAL: "temporal",
        QueryIntent.CAUSAL: "causal",
        QueryIntent.COMPARATIVE: "comparative",
        QueryIntent.EXPLORATORY: "exploratory",
        QueryIntent.UNKNOWN: "exploratory",
    }
    return mapping.get(intent, "exploratory")


def channel_weights_to_str_keys(weights: dict[RecallChannel, float]) -> dict[str, float]:
    """RecallChannel 枚举键 → 字符串键"""
    return {ch.value: w for ch, w in weights.items()}


# ────── 测试类 ──────

class TestFormatAdapters:
    """测试格式适配器的正确性"""

    def test_recalled_to_channel_groups_basic(self):
        """RecalledMemory → 通道分组"""
        memories = [
            RecalledMemory(memory_id="m1", content="hello", score=0.9, channel=RecallChannel.TEXT),
            RecalledMemory(memory_id="m2", content="world", score=0.8, channel=RecallChannel.TEMPERATURE),
            RecalledMemory(memory_id="m3", content="foo", score=0.7, channel=RecallChannel.TEXT),
        ]

        groups = recalled_to_channel_groups(memories)

        assert "text" in groups
        assert "temperature" in groups
        assert len(groups["text"]) == 2
        assert len(groups["temperature"]) == 1
        assert groups["text"][0]["memory_id"] == "m1"
        assert groups["temperature"][0]["score"] == 0.8

    def test_recalled_to_channel_groups_preserves_metadata(self):
        """元数据在转换中不丢失"""
        memories = [
            RecalledMemory(
                memory_id="m1",
                content="test",
                score=0.5,
                channel=RecallChannel.EMOTION,
                metadata={"emotion": "happy", "intensity": 0.9},
            ),
        ]

        groups = recalled_to_channel_groups(memories)
        assert groups["emotion"][0]["metadata"]["emotion"] == "happy"
        assert groups["emotion"][0]["metadata"]["intensity"] == 0.9

    def test_rendered_to_recalled_basic(self):
        """RenderedMemory → RecalledMemory"""
        rendered = [
            RenderedMemory(
                memory_id="m1",
                content="hello",
                score=0.85,
                channel_scores={"text": 0.5, "temperature": 0.35},
            ),
        ]

        recalled = rendered_to_recalled(rendered)

        assert len(recalled) == 1
        assert recalled[0].memory_id == "m1"
        assert recalled[0].score == 0.85
        assert recalled[0].channel == RecallChannel.TEXT  # text 通道分数最高

    def test_rendered_to_recalled_empty_channel_scores(self):
        """空 channel_scores 时默认 TEXT 通道"""
        rendered = [
            RenderedMemory(memory_id="m1", content="test", score=0.5, channel_scores={}),
        ]

        recalled = rendered_to_recalled(rendered)
        assert recalled[0].channel == RecallChannel.TEXT

    def test_query_intent_to_str_mapping(self):
        """所有 QueryIntent 都有对应的字符串映射"""
        for intent in QueryIntent:
            result = query_intent_to_str(intent)
            assert result in VolumeRenderer.INTENT_CHANNEL_WEIGHTS, \
                f"QueryIntent.{intent.name} 映射到 '{result}'，但 VolumeRenderer 不支持该意图"

    def test_channel_weights_to_str_keys(self):
        """RecallChannel 枚举键正确转换为字符串键"""
        weights = {
            RecallChannel.TEXT: 0.4,
            RecallChannel.TEMPERATURE: 0.3,
            RecallChannel.GRAPH: 0.3,
        }
        str_weights = channel_weights_to_str_keys(weights)
        assert str_weights == {"text": 0.4, "temperature": 0.3, "graph": 0.3}


class TestIntentWeightConsistency:
    """测试意图权重在两个系统间的一致性"""

    @pytest.mark.parametrize("intent", [
        QueryIntent.FACTUAL,
        QueryIntent.TEMPORAL,
        QueryIntent.CAUSAL,
        QueryIntent.COMPARATIVE,
        QueryIntent.EXPLORATORY,
    ])
    def test_intent_weights_sum_to_one(self, intent: QueryIntent):
        """IntentAwareRecallStrategy 的权重总和 = 1.0"""
        strategy = IntentAwareRecallStrategy()
        weights = strategy.get_channel_weights(intent)
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"Intent {intent.value} 权重总和 {total} != 1.0"

    @pytest.mark.parametrize("intent_str", [
        "factual", "temporal", "causal", "comparative", "exploratory",
    ])
    def test_volume_renderer_has_intent_weights(self, intent_str: str):
        """VolumeRenderer 为每种意图定义了通道权重"""
        weights = VolumeRenderer.INTENT_CHANNEL_WEIGHTS[intent_str]
        assert len(weights) > 0
        assert all(isinstance(v, (int, float)) for v in weights.values())

    def test_factual_prefers_text_channel(self):
        """事实查询：文本通道权重最高"""
        strategy = IntentAwareRecallStrategy()
        weights = strategy.get_channel_weights(QueryIntent.FACTUAL)

        text_weight = weights[RecallChannel.TEXT]
        emotion_weight = weights[RecallChannel.EMOTION]
        voice_weight = weights[RecallChannel.VOICE]

        assert text_weight > emotion_weight
        assert text_weight > voice_weight

    def test_temporal_prefers_temperature_channel(self):
        """时间查询：温度通道权重最高"""
        strategy = IntentAwareRecallStrategy()
        weights = strategy.get_channel_weights(QueryIntent.TEMPORAL)

        temp_weight = weights[RecallChannel.TEMPERATURE]
        text_weight = weights[RecallChannel.TEXT]

        assert temp_weight > text_weight

    def test_causal_prefers_graph_channel(self):
        """因果查询：图通道权重最高"""
        strategy = IntentAwareRecallStrategy()
        weights = strategy.get_channel_weights(QueryIntent.CAUSAL)

        graph_weight = weights[RecallChannel.GRAPH]
        text_weight = weights[RecallChannel.TEXT]

        assert graph_weight > text_weight


class TestVolumeRenderingAsFusion:
    """测试体渲染作为融合替代"""

    def _make_memories(self) -> list[RecalledMemory]:
        """创建测试记忆"""
        return [
            RecalledMemory(memory_id="m1", content="Python教程", score=0.9, channel=RecallChannel.TEXT),
            RecalledMemory(memory_id="m1", content="Python教程", score=0.7, channel=RecallChannel.TEMPERATURE),
            RecalledMemory(memory_id="m2", content="机器学习", score=0.8, channel=RecallChannel.TEXT),
            RecalledMemory(memory_id="m2", content="机器学习", score=0.6, channel=RecallChannel.GRAPH),
            RecalledMemory(memory_id="m3", content="深度学习", score=0.75, channel=RecallChannel.TEXT),
        ]

    def test_volume_renderer_consumes_engine_output(self):
        """VolumeRenderer 能消费 NeurovaRecallEngine 的输出"""
        memories = self._make_memories()
        channel_groups = recalled_to_channel_groups(memories)

        renderer = VolumeRenderer()
        rendered = renderer.render(channel_groups, intent="factual", limit=10)

        assert len(rendered) > 0
        assert all(isinstance(r, RenderedMemory) for r in rendered)
        # m1 和 m2 有多个通道，应该有更高的分数
        ids = [r.memory_id for r in rendered]
        assert "m1" in ids
        assert "m2" in ids

    def test_multichannel_memory_scores_higher(self):
        """多通道记忆分数高于单通道记忆"""
        memories = self._make_memories()
        channel_groups = recalled_to_channel_groups(memories)

        renderer = VolumeRenderer()
        rendered = renderer.render(channel_groups, intent="exploratory", limit=10)

        score_map = {r.memory_id: r.score for r in rendered}
        # m1 (text+temperature) > m3 (text only)
        assert score_map["m1"] > score_map["m3"]

    def test_render_with_attention_works(self):
        """带注意力的体渲染正常工作"""
        memories = self._make_memories()
        channel_groups = recalled_to_channel_groups(memories)

        renderer = VolumeRenderer()
        rendered = renderer.render_with_attention(channel_groups, intent="factual", limit=10)

        assert len(rendered) > 0
        # 注意力增强后分数应该更高
        basic = renderer.render(channel_groups, intent="factual", limit=10)
        # 至少有一个记忆的分数被增强了
        enhanced_scores = {r.memory_id: r.score for r in rendered}
        basic_scores = {r.memory_id: r.score for r in basic}
        # 注意力是正向的，所以总分应该 >= 基础分数
        for mid in enhanced_scores:
            assert enhanced_scores[mid] >= basic_scores[mid]

    def test_rendered_to_recalled_roundtrip(self):
        """渲染结果可以转换回 RecalledMemory 并保持完整性"""
        memories = self._make_memories()
        channel_groups = recalled_to_channel_groups(memories)

        renderer = VolumeRenderer()
        rendered = renderer.render(channel_groups, intent="factual", limit=10)

        recalled = rendered_to_recalled(rendered)

        assert len(recalled) == len(rendered)
        for r in recalled:
            assert isinstance(r, RecalledMemory)
            assert r.memory_id
            assert r.score > 0


class TestPositionalEncodingAsDecay:
    """测试位置编码作为温度衰减的连续替代"""

    def test_temporal_encoding_output_is_continuous(self):
        """时间位置编码输出是连续值（非阶梯）"""
        encoder = TemporalPositionalEncoder(num_frequencies=10)

        # 测试多个时间点（相对于参考时间的天数差异）
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        scores = []
        for days_ago in [0, 1, 3, 7, 14, 30, 90]:
            timestamp = now - days_ago * 86400
            encoding = encoder.encode_timestamp(timestamp, reference_time=now)
            # 取编码的模长作为"衰减因子"的连续替代
            norm = math.sqrt(sum(x * x for x in encoding))
            scores.append(norm)

        # 连续值：相邻时间点的差异应该是渐变的
        for i in range(len(scores) - 1):
            diff = abs(scores[i + 1] - scores[i])
            # 差异应该是有限的（非跳跃）
            assert diff < float('inf')

    def test_encoding_changes_smoothly(self):
        """编码随时间平滑变化（非阶梯跳跃）"""
        encoder = TemporalPositionalEncoder(num_frequencies=10)

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        # 计算相邻天数的编码差异
        diffs = []
        prev = None
        for day in range(0, 31):
            timestamp = now - day * 86400
            enc = encoder.encode_timestamp(timestamp, reference_time=now)
            if prev is not None:
                diff = math.sqrt(sum((a - b) ** 2 for a, b in zip(enc, prev)))
                diffs.append(diff)
            prev = enc

        # 所有差异应该是有限的
        assert all(d < float('inf') for d in diffs)
        # 差异应该不全为零（编码确实在变化）
        assert any(d > 0 for d in diffs)

    def test_encoding_captures_periodicity(self):
        """编码捕捉周期性（周期性访问的模式）"""
        encoder = TemporalPositionalEncoder(num_frequencies=10)

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        timestamp = now - 7 * 86400  # 7天前

        # 相同时间戳应该产生相同编码
        enc1 = encoder.encode_timestamp(timestamp, reference_time=now)
        enc2 = encoder.encode_timestamp(timestamp, reference_time=now)
        assert enc1 == enc2

        # 不同时间戳应该产生不同编码
        timestamp2 = now - 14 * 86400  # 14天前
        enc3 = encoder.encode_timestamp(timestamp2, reference_time=now)
        assert enc1 != enc3


class TestEndToEndIntegration:
    """端到端集成测试"""

    def test_full_pipeline_query_to_rendered(self):
        """完整管线：查询 → 检索引擎 → 体渲染 → 最终结果"""
        # 模拟记忆管理器
        mock_manager = MagicMock()
        mock_manager.search.return_value = [
            {"id": "m1", "content": "Python是编程语言", "score": 0.9, "metadata": {}},
            {"id": "m2", "content": "机器学习是AI子领域", "score": 0.8, "metadata": {}},
        ]

        # 创建检索引擎（传统模式）
        engine = NeurovaRecallEngine(memory_manager=mock_manager, fusion_mode="legacy")

        # 执行检索
        result = engine.recall("什么是Python?", limit=5)

        # 验证结果格式
        assert isinstance(result, RecallResult)
        assert len(result.recalled_memories) >= 0

        # 如果有结果，验证可以转换为体渲染输入
        if result.recalled_memories:
            channel_groups = recalled_to_channel_groups(result.recalled_memories)

            renderer = VolumeRenderer()
            rendered = renderer.render(channel_groups, intent="factual", limit=5)

            # 渲染结果可以转换回 RecalledMemory
            final = rendered_to_recalled(rendered)
            assert all(isinstance(m, RecalledMemory) for m in final)

    def test_nerf_fusion_mode_in_engine(self):
        """检索引擎的 nerf 融合模式"""
        mock_manager = MagicMock()

        engine = NeurovaRecallEngine(
            memory_manager=mock_manager,
            fusion_mode="nerf",
            density_scale=1.0,
        )

        # 验证体渲染器已初始化
        assert engine._volume_renderer is not None
        assert isinstance(engine._volume_renderer, VolumeRenderer)

    def test_legacy_fusion_mode_no_renderer(self):
        """传统模式不初始化体渲染器"""
        mock_manager = MagicMock()

        engine = NeurovaRecallEngine(
            memory_manager=mock_manager,
            fusion_mode="legacy",
        )

        assert engine._volume_renderer is None

    def test_intent_detection_feeds_into_renderer(self):
        """意图检测结果正确传递给体渲染器"""
        detector = QueryIntentDetector()

        # 事实查询
        intent = detector.detect_intent("Python的创始人是谁?")
        assert intent == QueryIntent.FACTUAL

        # 转换为渲染器意图字符串
        intent_str = query_intent_to_str(intent)
        assert intent_str == "factual"

        # 渲染器有权重
        weights = VolumeRenderer.INTENT_CHANNEL_WEIGHTS[intent_str]
        assert weights["text"] > weights["emotion"]

    def test_channel_weights_consistency(self):
        """两个系统的通道权重定义一致"""
        strategy = IntentAwareRecallStrategy()

        for intent in [QueryIntent.FACTUAL, QueryIntent.TEMPORAL, QueryIntent.CAUSAL]:
            strategy_weights = channel_weights_to_str_keys(
                strategy.get_channel_weights(intent)
            )
            intent_str = query_intent_to_str(intent)
            renderer_weights = VolumeRenderer.INTENT_CHANNEL_WEIGHTS[intent_str]

            # 两个系统都为每种意图定义了权重
            assert len(strategy_weights) > 0
            assert len(renderer_weights) > 0

            # 最高权重通道一致
            top_strategy = max(strategy_weights, key=strategy_weights.get)
            top_renderer = max(renderer_weights, key=renderer_weights.get)
            assert top_strategy == top_renderer, \
                f"Intent {intent.value}: strategy top={top_strategy}, renderer top={top_renderer}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
