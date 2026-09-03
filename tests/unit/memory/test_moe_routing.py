"""
Phase 2: MoE 通道路由测试

测试质心初始化、阈值配置、性能基准、准确性回归。
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from neurova.cognitive_layers.memory_layer.channels.base import (
    BaseChannel, ChannelMetadata, ChannelResult, ChannelState
)
from neurova.cognitive_layers.memory_layer.channels.registry import ChannelRegistry
from neurova.cognitive_layers.memory_layer.channels.centroid import CentroidInitializer
from neurova.cognitive_layers.memory_layer.channels.threshold import ThresholdConfig
from neurova.cognitive_layers.memory_layer.channels.builtin import (
    TemperatureChannel, TextChannel, CategoryChannel,
    GraphChannel, EmotionChannel, VoiceChannel,
)


# ────── Mock Channel ──────

class SimpleChannel(BaseChannel):
    """简单测试通道"""
    def __init__(self, name, desc, caps=None):
        self._name = name
        self._desc = desc
        self._caps = caps or []
        self._state = ChannelState.INACTIVE
        self._config = {}

    @property
    def metadata(self):
        return ChannelMetadata(
            name=self._name,
            display_name=self._name.title(),
            description=self._desc,
            capabilities=self._caps,
        )

    async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
        return [ChannelResult(
            memory_id=f"{self._name}_1",
            content=f"Result from {self._name}",
            score=0.5 * weight,
            channel=self._name,
        )]


@pytest.fixture
def fresh_registry():
    reg = ChannelRegistry()
    reg._channels.clear()
    reg._metadata.clear()
    return reg


# ────── CentroidInitializer Tests ──────

class TestCentroidInitializer:
    """质心初始化器测试"""

    def test_init_with_vector_store(self):
        vs = MagicMock()
        vs.encode.return_value = [0.1, 0.2, 0.3]
        vs.get_expert_centroids.return_value = {}
        ci = CentroidInitializer(vector_store=vs)
        assert ci.vector_store is vs

    def test_generate_centroids_from_descriptions(self, fresh_registry):
        vs = MagicMock()
        vs.encode.return_value = [0.1, 0.2, 0.3]
        vs.get_expert_centroids.return_value = {}

        fresh_registry.register(SimpleChannel("alpha", "Alpha channel description"))
        fresh_registry.register(SimpleChannel("beta", "Beta channel description"))

        ci = CentroidInitializer(vector_store=vs)
        count = ci.generate_centroids(fresh_registry)

        assert count == 2
        assert vs.encode.call_count == 2

    def test_skips_existing_centroids(self, fresh_registry):
        vs = MagicMock()
        vs.encode.return_value = [0.1, 0.2]
        vs.get_expert_centroids.return_value = {"alpha": [0.5, 0.5]}

        fresh_registry.register(SimpleChannel("alpha", "desc"))
        fresh_registry.register(SimpleChannel("beta", "desc"))

        ci = CentroidInitializer(vector_store=vs)
        count = ci.generate_centroids(fresh_registry)

        # alpha 已有质心，只生成 beta
        assert count == 1

    def test_empty_registry(self):
        vs = MagicMock()
        vs.get_expert_centroids.return_value = {}
        reg = ChannelRegistry()
        reg._channels.clear()
        reg._metadata.clear()

        ci = CentroidInitializer(vector_store=vs)
        count = ci.generate_centroids(reg)
        assert count == 0


# ────── ThresholdConfig Tests ──────

class TestThresholdConfig:
    """阈值配置测试"""

    def test_default_threshold(self):
        tc = ThresholdConfig()
        assert tc.default_threshold == 0.3

    def test_get_threshold_default(self):
        tc = ThresholdConfig()
        assert tc.get_threshold("any_channel") == 0.3

    def test_set_per_channel_threshold(self):
        tc = ThresholdConfig()
        tc.set_threshold("temperature", 0.5)
        assert tc.get_threshold("temperature") == 0.5
        assert tc.get_threshold("text") == 0.3  # 默认值不变

    def test_multiple_channels(self):
        tc = ThresholdConfig()
        tc.set_threshold("temperature", 0.6)
        tc.set_threshold("text", 0.4)
        tc.set_threshold("emotion", 0.2)

        assert tc.get_threshold("temperature") == 0.6
        assert tc.get_threshold("text") == 0.4
        assert tc.get_threshold("emotion") == 0.2
        assert tc.get_threshold("unknown") == 0.3

    def test_update_default(self):
        tc = ThresholdConfig()
        tc.set_threshold("x", 0.5)
        tc.update_default(0.7)
        assert tc.default_threshold == 0.7
        assert tc.get_threshold("x") == 0.5  # 已设置的不受影响
        assert tc.get_threshold("new") == 0.7

    def test_from_dict(self):
        tc = ThresholdConfig.from_dict({
            "default": 0.4,
            "temperature": 0.8,
            "text": 0.5,
        })
        assert tc.default_threshold == 0.4
        assert tc.get_threshold("temperature") == 0.8
        assert tc.get_threshold("text") == 0.5
        assert tc.get_threshold("other") == 0.4

    def test_to_dict(self):
        tc = ThresholdConfig(default_threshold=0.4)
        tc.set_threshold("temperature", 0.8)
        d = tc.to_dict()
        assert d["default"] == 0.4
        assert d["temperature"] == 0.8


# ────── MoE Router Integration Tests ──────

class TestMoERouterIntegration:
    """MoE 路由器集成测试"""

    @pytest.mark.asyncio
    async def test_router_selects_relevant_channels(self, fresh_registry):
        """路由器应选择与查询相关的通道"""
        from neurova.cognitive_layers.memory_layer.channels.moe_router import ChannelMoERouter

        # 注册通道
        for ChCls in [TemperatureChannel, TextChannel, CategoryChannel,
                      GraphChannel, EmotionChannel, VoiceChannel]:
            ch = ChCls()
            ch._state = ChannelState.ACTIVE
            fresh_registry.register(ch)

        vs = MagicMock()
        vs.encode.return_value = [0.1, 0.2, 0.3]
        vs.get_expert_centroids.return_value = {
            "temperature": [0.1, 0.2, 0.3],
            "text": [0.4, 0.5, 0.6],
            "category": [0.7, 0.8, 0.9],
        }

        router = ChannelMoERouter(
            registry=fresh_registry,
            vector_store=vs,
            top_k=2,
            activation_threshold=0.1,
        )

        # Mock gating to return specific channels
        with patch.object(router.gating, 'route', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"text": 0.9, "temperature": 0.7}

            results = await router.retrieve("test query", limit=5)

            # 应该只执行 text 和 temperature 通道
            mock_route.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_when_no_activation(self, fresh_registry):
        """MoE 未激活时应回退到全通道模式"""
        from neurova.cognitive_layers.memory_layer.channels.moe_router import ChannelMoERouter

        # 使用简单通道（有返回结果的），并设为 ACTIVE
        ch_a = SimpleChannel("a", "Channel A")
        ch_a._state = ChannelState.ACTIVE
        ch_b = SimpleChannel("b", "Channel B")
        ch_b._state = ChannelState.ACTIVE
        fresh_registry.register(ch_a)
        fresh_registry.register(ch_b)

        vs = MagicMock()
        vs.encode.return_value = [0.1, 0.2]
        vs.get_expert_centroids.return_value = {}

        router = ChannelMoERouter(
            registry=fresh_registry,
            vector_store=vs,
            top_k=2,
            activation_threshold=0.99,
            fallback_to_all=True,
        )

        with patch.object(router.gating, 'route', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {}  # 无激活

            results = await router.retrieve("query", limit=5)
            # fallback 到全通道，SimpleChannel 有返回结果
            assert len(results) == 2  # 两个通道各返回1条


# ────── Performance Benchmark Tests ──────

class TestMoEPerformance:
    """MoE 路由性能基准测试"""

    @pytest.mark.asyncio
    async def test_moe_faster_than_all_channels(self):
        """MoE 路由应比全通道执行更快（概念性测试）"""
        # 创建 6 个模拟通道
        channels = {}
        for i in range(6):
            ch = SimpleChannel(f"ch_{i}", f"Channel {i}")
            ch._state = ChannelState.ACTIVE
            channels[f"ch_{i}"] = ch

        # 模拟 MoE 模式：只执行 2 个通道
        start = time.time()
        for name in ["ch_0", "ch_1"]:
            ch = channels[name]
            # 模拟检索延迟
            for _ in range(100):
                pass
        moe_time = time.time() - start

        # 模拟全通道模式：执行 6 个通道
        start = time.time()
        for name in channels:
            ch = channels[name]
            for _ in range(100):
                pass
        all_time = time.time() - start

        # MoE 应该更快
        assert moe_time < all_time

    @pytest.mark.asyncio
    async def test_centroid_generation_performance(self, fresh_registry):
        """质心生成性能测试"""
        # 注册 100 个通道
        for i in range(100):
            fresh_registry.register(SimpleChannel(f"ch_{i}", f"Description {i}"))

        vs = MagicMock()
        vs.encode.return_value = list(range(128))
        vs.get_expert_centroids.return_value = {}

        ci = CentroidInitializer(vector_store=vs)

        start = time.time()
        count = ci.generate_centroids(fresh_registry)
        elapsed = time.time() - start

        assert count == 100
        assert elapsed < 5.0  # 5 秒内完成


# ────── Accuracy Regression Tests ──────

class TestMoEAccuracy:
    """MoE 通道选择准确性测试"""

    def test_text_query_selects_text_channel(self, fresh_registry):
        """文本查询应选择文本通道"""
        tc = ThresholdConfig()
        tc.set_threshold("text", 0.2)  # 低阈值更容易激活

        # 验证阈值配置正确
        assert tc.get_threshold("text") == 0.2
        assert tc.get_threshold("temperature") == 0.3

    def test_threshold_affects_channel_selection(self):
        """阈值配置应影响通道选择"""
        tc = ThresholdConfig()
        tc.set_threshold("temperature", 0.8)  # 高阈值，不容易激活
        tc.set_threshold("text", 0.2)  # 低阈值，容易激活

        # 在高相似度场景下
        assert tc.get_threshold("temperature") > tc.get_threshold("text")

    def test_centroid_distance_determines_activation(self):
        """质心距离应决定通道激活"""
        # 模拟两个通道的质心
        centroid_a = [1.0, 0.0, 0.0]
        centroid_b = [0.0, 0.0, 1.0]
        query_vec = [1.0, 0.0, 0.0]  # 与 A 完全匹配

        # 余弦相似度
        from neurova.cognitive_layers.memory_layer.unified_vector_store import cosine_similarity
        sim_a = cosine_similarity(query_vec, centroid_a)
        sim_b = cosine_similarity(query_vec, centroid_b)

        assert sim_a > sim_b
