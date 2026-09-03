"""
NeRF 记忆系统升级测试

覆盖：
- Phase 1: 位置编码器 (temporal, emotion, importance)
- Phase 2: 记忆场神经网络 (MemoryField) — 可选，需 torch
- Phase 3: 体渲染器 (VolumeRenderer)

纯 Python 实现，不依赖 numpy/torch。
"""

import math
import time
import pytest


# ────── Phase 1: 位置编码器测试 ──────

class TestPositionalEncoder:
    """基础位置编码器测试"""
    
    def test_basic_encoding(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import PositionalEncoder
        enc = PositionalEncoder()
        vec = enc.encode(0.5)
        assert isinstance(vec, list)
        assert len(vec) == enc.config.output_dim
    
    def test_output_dim(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import (
            PositionalEncoder, PositionalEncodingConfig)
        config = PositionalEncodingConfig(num_frequencies=10, include_input=True)
        enc = PositionalEncoder(config)
        assert enc.config.output_dim == 21  # 10*2 + 1
    
    def test_output_dim_no_input(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import (
            PositionalEncoder, PositionalEncodingConfig)
        config = PositionalEncodingConfig(num_frequencies=10, include_input=False)
        enc = PositionalEncoder(config)
        assert enc.config.output_dim == 20
    
    def test_batch_encoding(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import PositionalEncoder
        enc = PositionalEncoder()
        batch = [0.1, 0.5, 0.9]
        result = enc.encode_batch(batch)
        assert len(result) == 3
        assert all(len(v) == enc.config.output_dim for v in result)
    
    def test_different_values_different_encoding(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import PositionalEncoder
        enc = PositionalEncoder()
        v1 = enc.encode(0.1)
        v2 = enc.encode(0.9)
        assert v1 != v2
    
    def test_same_value_same_encoding(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import PositionalEncoder
        enc = PositionalEncoder()
        v1 = enc.encode(0.5)
        v2 = enc.encode(0.5)
        assert v1 == v2
    
    def test_encoding_contains_sin_cos(self):
        """编码应包含 sin 和 cos 值"""
        from neurova.cognitive_layers.memory_layer.positional_encoding import (
            PositionalEncoder, PositionalEncodingConfig)
        enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=3, include_input=False))
        vec = enc.encode(0.5)
        # 3 频率 * 2 (sin+cos) = 6
        assert len(vec) == 6
        # 所有值应在 [-1, 1] 范围内
        assert all(-1 <= v <= 1 for v in vec)


class TestTemporalPositionalEncoder:
    """时间位置编码器测试"""
    
    def test_encode_timestamp(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import TemporalPositionalEncoder
        enc = TemporalPositionalEncoder()
        ts = 1700000000  # 2023-11-14
        vec = enc.encode_timestamp(ts)
        assert isinstance(vec, list)
        assert len(vec) == enc.output_dim
    
    def test_recent_vs_old(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import TemporalPositionalEncoder
        enc = TemporalPositionalEncoder()
        now = time.time()
        recent = enc.encode_timestamp(now - 3600)  # 1小时前
        old = enc.encode_timestamp(now - 86400 * 365)  # 1年前
        assert recent != old
    
    def test_output_dim_consistent(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import TemporalPositionalEncoder
        enc = TemporalPositionalEncoder(num_frequencies=8)
        vec = enc.encode_timestamp(1700000000)
        assert len(vec) == enc.output_dim
    
    def test_different_frequencies(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import TemporalPositionalEncoder
        enc10 = TemporalPositionalEncoder(num_frequencies=10)
        enc5 = TemporalPositionalEncoder(num_frequencies=5)
        assert enc10.output_dim > enc5.output_dim


class TestEmotionPositionalEncoder:
    """情感位置编码器测试"""
    
    def test_encode_emotion(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        enc = EmotionPositionalEncoder()
        vec = enc.encode_emotion("joy", 0.8)
        assert isinstance(vec, list)
        assert len(vec) == enc.output_dim
    
    def test_different_emotions_different_encoding(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        enc = EmotionPositionalEncoder()
        joy = enc.encode_emotion("joy", 0.5)
        sadness = enc.encode_emotion("sadness", 0.5)
        assert joy != sadness
    
    def test_intensity_difference(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        enc = EmotionPositionalEncoder()
        low = enc.encode_emotion("joy", 0.2)
        high = enc.encode_emotion("joy", 0.9)
        assert low != high
    
    def test_with_valence_arousal(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        enc = EmotionPositionalEncoder()
        vec = enc.encode_emotion("joy", 0.8, valence=0.9, arousal=0.7)
        assert len(vec) == enc.output_dim
    
    def test_unknown_emotion_defaults_to_neutral(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        enc = EmotionPositionalEncoder()
        unknown = enc.encode_emotion("unknown_emotion", 0.5)
        neutral = enc.encode_emotion("neutral", 0.5)
        # 类型部分(前9维)应该相同
        assert unknown[:9] == neutral[:9]
    
    def test_one_hot_correct(self):
        """每种情感的 one-hot 应该不同"""
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        enc = EmotionPositionalEncoder()
        emotions = ["neutral", "joy", "sadness", "anger", "fear"]
        bases = [enc.encode_emotion(e, 0.5)[:9] for e in emotions]
        # 任意两个应该不同
        for i in range(len(bases)):
            for j in range(i + 1, len(bases)):
                assert bases[i] != bases[j]


class TestImportancePositionalEncoder:
    """重要性位置编码器测试"""
    
    def test_encode_importance(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import ImportancePositionalEncoder
        enc = ImportancePositionalEncoder()
        vec = enc.encode_importance(0.7)
        assert isinstance(vec, list)
        assert len(vec) == enc.output_dim
    
    def test_with_lifecycle_stage(self):
        from neurova.cognitive_layers.memory_layer.positional_encoding import ImportancePositionalEncoder
        enc = ImportancePositionalEncoder()
        active = enc.encode_importance(0.7, lifecycle_stage="active")
        archived = enc.encode_importance(0.7, lifecycle_stage="archived")
        assert active != archived


# ────── Phase 3: 体渲染器测试 ──────

class TestVolumeRenderer:
    """体渲染器测试"""
    
    def test_basic_render(self):
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [
                {"memory_id": "m1", "content": "hello", "score": 0.9},
                {"memory_id": "m2", "content": "world", "score": 0.7},
            ],
            "temperature": [
                {"memory_id": "m1", "content": "hello", "score": 0.8},
                {"memory_id": "m3", "content": "foo", "score": 0.6},
            ],
        }
        result = renderer.render(channel_results, intent="factual", limit=5)
        assert len(result) > 0
        assert all(hasattr(r, 'score') for r in result)
        assert all(hasattr(r, 'memory_id') for r in result)
    
    def test_multi_channel_boost(self):
        """多通道出现的记忆应该分数更高"""
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [{"memory_id": "m1", "content": "a", "score": 0.8}],
            "temperature": [{"memory_id": "m1", "content": "a", "score": 0.8}],
            "emotion": [{"memory_id": "m2", "content": "b", "score": 0.8}],
        }
        result = renderer.render(channel_results, intent="factual")
        scores = {r.memory_id: r.score for r in result}
        assert scores.get("m1", 0) > scores.get("m2", 0)
    
    def test_intent_changes_weights(self):
        """不同意图应该产生不同分数"""
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [{"memory_id": "m1", "content": "a", "score": 0.9}],
            "graph": [{"memory_id": "m2", "content": "b", "score": 0.9}],
        }
        factual = renderer.render(channel_results, intent="factual")
        causal = renderer.render(channel_results, intent="causal")
        # 两个意图下，m1 的分数应该不同（text 在 factual 中权重 1.0，causal 中 0.8）
        factual_m1_score = next(r.score for r in factual if r.memory_id == "m1")
        causal_m1_score = next(r.score for r in causal if r.memory_id == "m1")
        assert factual_m1_score != causal_m1_score
    
    def test_empty_results(self):
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        result = renderer.render({}, intent="factual")
        assert result == []
    
    def test_with_attention(self):
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [
                {"memory_id": "m1", "content": "a", "score": 0.9},
                {"memory_id": "m2", "content": "b", "score": 0.8},
            ],
        }
        result = renderer.render_with_attention(channel_results, intent="factual")
        assert len(result) > 0
    
    def test_channel_scores_detail(self):
        """每个记忆应该记录各通道的贡献"""
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [{"memory_id": "m1", "content": "a", "score": 0.9}],
            "emotion": [{"memory_id": "m1", "content": "a", "score": 0.7}],
        }
        result = renderer.render(channel_results, intent="factual")
        assert len(result) == 1
        assert "text" in result[0].channel_scores
        assert "emotion" in result[0].channel_scores
    
    def test_density_ordering(self):
        """高密度通道应该排在前面"""
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        # m1 只在低密度通道，m2 只在高密度通道
        channel_results = {
            "voice": [{"memory_id": "m1", "content": "a", "score": 0.9}],  # density 0.4
            "text": [{"memory_id": "m2", "content": "b", "score": 0.9}],   # density 0.9
        }
        result = renderer.render(channel_results, intent="factual")
        assert result[0].memory_id == "m2"
    
    def test_score_is_positive(self):
        """分数应该为正数"""
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [{"memory_id": "m1", "content": "a", "score": 0.5}],
        }
        result = renderer.render(channel_results, intent="factual")
        assert all(r.score >= 0 for r in result)
    
    def test_limit_works(self):
        """limit 参数应该限制返回数量"""
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        renderer = VolumeRenderer()
        channel_results = {
            "text": [{"memory_id": f"m{i}", "content": f"c{i}", "score": 0.5} for i in range(20)],
        }
        result = renderer.render(channel_results, intent="factual", limit=3)
        assert len(result) == 3


# ────── 集成测试 ──────

class TestIntegration:
    """端到端集成测试"""
    
    def test_full_pipeline(self):
        """测试完整流程：编码 → 渲染"""
        from neurova.cognitive_layers.memory_layer.positional_encoding import (
            TemporalPositionalEncoder, EmotionPositionalEncoder)
        from neurova.cognitive_layers.memory_layer.volume_renderer import VolumeRenderer
        
        # 1. 位置编码
        time_enc = TemporalPositionalEncoder()
        emotion_enc = EmotionPositionalEncoder()
        
        now = time.time()
        time_vec = time_enc.encode_timestamp(now)
        emotion_vec = emotion_enc.encode_emotion("joy", 0.8)
        
        assert len(time_vec) == time_enc.output_dim
        assert len(emotion_vec) == emotion_enc.output_dim
        
        # 2. 模拟多通道检索结果
        channel_results = {
            "text": [
                {"memory_id": "m1", "content": "今天很开心", "score": 0.9},
                {"memory_id": "m2", "content": "项目进展顺利", "score": 0.7},
            ],
            "emotion": [
                {"memory_id": "m1", "content": "今天很开心", "score": 0.85},
                {"memory_id": "m3", "content": "收到好消息", "score": 0.8},
            ],
            "temperature": [
                {"memory_id": "m1", "content": "今天很开心", "score": 0.95},
            ],
        }
        
        # 3. 体渲染融合
        renderer = VolumeRenderer()
        result = renderer.render(channel_results, intent="factual", limit=5)
        
        assert len(result) == 3
        # m1 出现在 3 个通道，应该排第一
        assert result[0].memory_id == "m1"
        assert result[0].score > result[1].score
    
    def test_positional_encoding_replaces_decay(self):
        """验证位置编码可以替代原有分段衰减"""
        from neurova.cognitive_layers.memory_layer.positional_encoding import TemporalPositionalEncoder
        
        enc = TemporalPositionalEncoder()
        now = time.time()
        
        # 不同时间点的编码应该不同
        t1 = enc.encode_timestamp(now - 60)       # 1分钟前
        t2 = enc.encode_timestamp(now - 3600)     # 1小时前
        t3 = enc.encode_timestamp(now - 86400)    # 1天前
        t4 = enc.encode_timestamp(now - 86400*30) # 30天前
        
        # 所有编码应该不同
        assert t1 != t2
        assert t2 != t3
        assert t3 != t4
    
    def test_emotion_encoding_granularity(self):
        """验证情感编码的连续性（比枚举更细粒度）"""
        from neurova.cognitive_layers.memory_layer.positional_encoding import EmotionPositionalEncoder
        
        enc = EmotionPositionalEncoder()
        
        # 同一情感类型，不同强度
        joy_low = enc.encode_emotion("joy", 0.3)
        joy_mid = enc.encode_emotion("joy", 0.5)
        joy_high = enc.encode_emotion("joy", 0.9)
        
        # 三个应该都不同
        assert joy_low != joy_mid
        assert joy_mid != joy_high
        assert joy_low != joy_high
        
        # 但类型部分(前9维)应该相同
        assert joy_low[:9] == joy_mid[:9] == joy_high[:9]
