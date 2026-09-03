"""
记忆检索通道插件化集成测试

验证插件模式与传统模式行为一致。
"""
import pytest
from unittest.mock import MagicMock

from neurova.cognitive_layers.memory_layer.channels.base import (
    ChannelMetadata, ChannelResult, ChannelState
)
from neurova.cognitive_layers.memory_layer.channels.registry import (
    ChannelRegistry, get_channel_registry
)
from neurova.cognitive_layers.memory_layer.channels.builtin import (
    TemperatureChannel, TextChannel, CategoryChannel,
    GraphChannel, EmotionChannel, VoiceChannel,
)
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    NeurovaRecallEngine, RecallChannel, RecalledMemory
)


def _make_memory(mid, content, temperature=50.0, category="general",
                 memory_type="text", metadata=None):
    return {
        "id": mid,
        "content": content,
        "temperature": temperature,
        "category": category,
        "memory_type": memory_type,
        "metadata": metadata or {},
    }


class MockMemoryManager:
    def __init__(self):
        self._memories = {}
        self.emotion_module = None

    def get_all_memories(self):
        return list(self._memories.values())


@pytest.fixture
def fresh_registry():
    reg = ChannelRegistry()
    reg._channels.clear()
    reg._metadata.clear()
    return reg


@pytest.fixture
def memory_manager():
    mm = MockMemoryManager()
    mm._memories = {
        "m1": _make_memory("m1", "python编程教程", temperature=90,
                           category="knowledge"),
        "m2": _make_memory("m2", "java烹饪食谱", temperature=20,
                           category="general"),
        "m3": _make_memory("m3", "机器学习入门", temperature=60,
                           category="knowledge",
                           metadata={"relations": ["r1", "r2"]}),
    }
    return mm


class TestPluginModeIntegration:
    """插件模式集成测试"""

    def _setup_registry(self, registry):
        """注册所有内置通道"""
        for ChCls in [TemperatureChannel, TextChannel, CategoryChannel,
                      GraphChannel, EmotionChannel, VoiceChannel]:
            registry.register(ChCls())

    @pytest.mark.asyncio
    async def test_registry_has_all_channels(self, fresh_registry):
        self._setup_registry(fresh_registry)
        assert len(fresh_registry.get_all()) == 6
        names = {ch.metadata.name for ch in fresh_registry.get_all()}
        assert names == {"temperature", "text", "category",
                         "graph", "emotion", "voice"}

    def test_plugin_engine_init(self, fresh_registry):
        self._setup_registry(fresh_registry)
        engine = NeurovaRecallEngine(
            use_plugins=True,
            registry=fresh_registry,
        )
        assert engine.use_plugins is True
        assert engine._registry is fresh_registry

    def test_legacy_engine_unchanged(self):
        engine = NeurovaRecallEngine(use_plugins=False)
        assert engine.use_plugins is False
        assert engine._registry is None

    def test_plugin_recall_returns_results(self, fresh_registry, memory_manager):
        self._setup_registry(fresh_registry)
        # 初始化所有通道
        for ch in fresh_registry.get_all():
            ch._state = ChannelState.ACTIVE

        engine = NeurovaRecallEngine(
            memory_manager=memory_manager,
            use_plugins=True,
            registry=fresh_registry,
        )
        result = engine.recall("python")
        assert result is not None
        assert hasattr(result, "recalled_memories")

    def test_legacy_recall_returns_results(self, memory_manager):
        engine = NeurovaRecallEngine(
            memory_manager=memory_manager,
            use_plugins=False,
        )
        result = engine.recall("python")
        assert result is not None
        assert hasattr(result, "recalled_memories")

    def test_plugin_and_legacy_same_structure(self, fresh_registry, memory_manager):
        """两种模式返回相同的数据结构"""
        self._setup_registry(fresh_registry)
        for ch in fresh_registry.get_all():
            ch._state = ChannelState.ACTIVE

        engine_plugin = NeurovaRecallEngine(
            memory_manager=memory_manager,
            use_plugins=True,
            registry=fresh_registry,
        )
        engine_legacy = NeurovaRecallEngine(
            memory_manager=memory_manager,
            use_plugins=False,
        )

        r1 = engine_plugin.recall("python编程")
        r2 = engine_legacy.recall("python编程")

        assert type(r1) == type(r2)
        assert hasattr(r1, "recalled_memories")
        assert hasattr(r2, "recalled_memories")

    def test_custom_channel_registration(self, fresh_registry):
        """支持自定义通道注册"""

        class CustomChannel:
            @property
            def metadata(self):
                return ChannelMetadata(
                    name="custom", display_name="Custom",
                    description="Custom test channel",
                )
            async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
                return [ChannelResult(
                    memory_id="custom_1",
                    content=f"Custom: {query}",
                    score=0.9 * weight,
                    channel="custom",
                )]
            def get_state(self):
                return ChannelState.ACTIVE
            async def initialize(self):
                return True
            async def shutdown(self):
                pass

        # 需要继承 BaseChannel 才能注册
        from neurova.cognitive_layers.memory_layer.channels.base import BaseChannel

        class TestChannel(BaseChannel):
            @property
            def metadata(self):
                return ChannelMetadata(
                    name="test_custom", display_name="Test Custom",
                    description="Test custom channel",
                )
            async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
                return [ChannelResult(
                    memory_id="tc_1",
                    content=f"Test: {query}",
                    score=0.85 * weight,
                    channel="test_custom",
                )]

        ch = TestChannel()
        fresh_registry.register(ch)
        assert fresh_registry.get("test_custom") is ch
        assert len(fresh_registry.get_all()) == 1
