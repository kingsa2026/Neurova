"""
记忆检索通道插件化单元测试

TDD Phase 1: BaseChannel + ChannelRegistry + 6个内置通道
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from neurova.cognitive_layers.memory_layer.channels.base import (
    BaseChannel, ChannelMetadata, ChannelResult, ChannelState
)
from neurova.cognitive_layers.memory_layer.channels.registry import (
    ChannelRegistry, get_channel_registry
)


# ────── Mock Channel ──────

class MockChannel(BaseChannel):
    """测试用模拟通道"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="mock",
            display_name="Mock Channel",
            description="A mock channel for testing",
            capabilities=["text", "semantic"],
        )

    async def retrieve(self, query: str, limit: int = 10, weight: float = 1.0, **kwargs):
        return [
            ChannelResult(
                memory_id="mock_mem_1",
                content=f"Mock result for: {query}",
                score=0.8 * weight,
                channel="mock",
                metadata={"source": "mock"},
            )
        ]


class MockChannelB(BaseChannel):
    """第二个测试通道"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="mock_b",
            display_name="Mock Channel B",
            description="Another mock channel",
            capabilities=["graph"],
        )

    async def retrieve(self, query: str, limit: int = 10, weight: float = 1.0, **kwargs):
        return [
            ChannelResult(
                memory_id="mock_b_mem_1",
                content=f"Mock B result for: {query}",
                score=0.6 * weight,
                channel="mock_b",
            )
        ]


# ────── BaseChannel Tests ──────

class TestBaseChannel:
    """BaseChannel 接口测试"""

    def test_metadata_property(self):
        ch = MockChannel()
        assert ch.metadata.name == "mock"
        assert ch.metadata.display_name == "Mock Channel"
        assert "text" in ch.metadata.capabilities

    def test_initial_state(self):
        ch = MockChannel()
        assert ch.get_state() == ChannelState.INACTIVE

    @pytest.mark.asyncio
    async def test_initialize(self):
        ch = MockChannel()
        result = await ch.initialize()
        assert result is True
        assert ch.get_state() == ChannelState.ACTIVE

    @pytest.mark.asyncio
    async def test_shutdown(self):
        ch = MockChannel()
        await ch.initialize()
        assert ch.get_state() == ChannelState.ACTIVE
        await ch.shutdown()
        assert ch.get_state() == ChannelState.INACTIVE

    @pytest.mark.asyncio
    async def test_retrieve_returns_list(self):
        ch = MockChannel()
        results = await ch.retrieve("test query", limit=5)
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0].memory_id == "mock_mem_1"

    @pytest.mark.asyncio
    async def test_retrieve_weight_affects_score(self):
        ch = MockChannel()
        r1 = await ch.retrieve("q", weight=1.0)
        r2 = await ch.retrieve("q", weight=0.5)
        assert r2[0].score < r1[0].score

    def test_update_config(self):
        ch = MockChannel()
        ch.update_config({"key": "value"})
        assert ch._config["key"] == "value"


class TestChannelMetadata:
    """ChannelMetadata 测试"""

    def test_defaults(self):
        m = ChannelMetadata(name="t", display_name="T", description="d")
        assert m.version == "1.0.0"
        assert m.author == "system"
        assert m.semantic_centroid is None
        assert m.capabilities == []


class TestChannelResult:
    """ChannelResult 测试"""

    def test_defaults(self):
        r = ChannelResult(memory_id="m1", content="c", score=0.5, channel="test")
        assert r.metadata == {}
        assert r.timestamp is None

    def test_with_metadata(self):
        r = ChannelResult(
            memory_id="m1", content="c", score=0.5, channel="test",
            metadata={"key": "val"}
        )
        assert r.metadata["key"] == "val"


# ────── ChannelRegistry Tests ──────

@pytest.fixture
def fresh_registry():
    """创建全新的注册表（避免单例污染）"""
    reg = ChannelRegistry()
    reg._channels.clear()
    reg._metadata.clear()
    return reg


class TestChannelRegistry:
    """ChannelRegistry 注册表测试"""

    def test_register(self, fresh_registry):
        ch = MockChannel()
        assert fresh_registry.register(ch) is True
        assert fresh_registry.get("mock") is ch

    def test_register_overwrite(self, fresh_registry):
        ch1 = MockChannel()
        ch2 = MockChannel()
        fresh_registry.register(ch1)
        fresh_registry.register(ch2)
        assert fresh_registry.get("mock") is ch2

    def test_unregister(self, fresh_registry):
        ch = MockChannel()
        fresh_registry.register(ch)
        assert fresh_registry.unregister("mock") is True
        assert fresh_registry.get("mock") is None

    def test_unregister_nonexistent(self, fresh_registry):
        assert fresh_registry.unregister("nonexistent") is False

    def test_get_all(self, fresh_registry):
        fresh_registry.register(MockChannel())
        fresh_registry.register(MockChannelB())
        all_ch = fresh_registry.get_all()
        assert len(all_ch) == 2

    @pytest.mark.asyncio
    async def test_get_active(self, fresh_registry):
        ch = MockChannel()
        fresh_registry.register(ch)
        # 新注册的通道默认 INACTIVE
        assert len(fresh_registry.get_active()) == 0
        # initialize 后变为 ACTIVE
        await ch.initialize()
        active = fresh_registry.get_active()
        assert len(active) == 1
        assert active[0] is ch

    def test_get_by_capability(self, fresh_registry):
        fresh_registry.register(MockChannel())  # has "text", "semantic"
        fresh_registry.register(MockChannelB())  # has "graph"
        result = fresh_registry.get_by_capability("text")
        assert len(result) == 1
        assert result[0].metadata.name == "mock"

    def test_get_metadata(self, fresh_registry):
        ch = MockChannel()
        fresh_registry.register(ch)
        meta = fresh_registry.get_metadata("mock")
        assert meta is not None
        assert meta.name == "mock"

    def test_get_all_metadata(self, fresh_registry):
        fresh_registry.register(MockChannel())
        fresh_registry.register(MockChannelB())
        all_meta = fresh_registry.get_all_metadata()
        assert "mock" in all_meta
        assert "mock_b" in all_meta

    @pytest.mark.asyncio
    async def test_initialize_all(self, fresh_registry):
        fresh_registry.register(MockChannel())
        fresh_registry.register(MockChannelB())
        results = await fresh_registry.initialize_all()
        assert results["mock"] is True
        assert results["mock_b"] is True
        assert fresh_registry.get("mock").get_state() == ChannelState.ACTIVE

    @pytest.mark.asyncio
    async def test_shutdown_all(self, fresh_registry):
        fresh_registry.register(MockChannel())
        fresh_registry.register(MockChannelB())
        await fresh_registry.initialize_all()
        await fresh_registry.shutdown_all()
        for ch in fresh_registry.get_all():
            assert ch.get_state() == ChannelState.INACTIVE


class TestGetChannelRegistry:
    """get_channel_registry 工厂函数测试"""

    def test_returns_singleton(self):
        r1 = get_channel_registry()
        r2 = get_channel_registry()
        assert r1 is r2


# ────── Builtin Channel Tests ──────

from neurova.cognitive_layers.memory_layer.channels.builtin import (
    TemperatureChannel, TextChannel, CategoryChannel,
    GraphChannel, EmotionChannel, VoiceChannel,
)


class MockMemoryManager:
    """模拟记忆管理器"""

    def __init__(self):
        self._memories = {}

    def get_all_memories(self):
        return list(self._memories.values())


def _make_memory(mid, content, temperature=50.0, category="general",
                 memory_type="text", metadata=None):
    """构造模拟记忆"""
    return {
        "id": mid,
        "content": content,
        "temperature": temperature,
        "category": category,
        "memory_type": memory_type,
        "metadata": metadata or {},
    }


class TestTemperatureChannel:
    """温度通道测试"""

    @pytest.mark.asyncio
    async def test_returns_hot_memories_first(self):
        ch = TemperatureChannel()
        mm = MockMemoryManager()
        mm._memories = {
            "m1": _make_memory("m1", "hot memory", temperature=90),
            "m2": _make_memory("m2", "cold memory", temperature=20),
            "m3": _make_memory("m3", "warm memory", temperature=55),
        }
        results = await ch.retrieve("query", limit=10, memory_manager=mm)
        assert len(results) == 3
        assert results[0].memory_id == "m1"
        # 按温度降序排列
        assert results[0].score > results[1].score > results[2].score

    @pytest.mark.asyncio
    async def test_empty_without_manager(self):
        ch = TemperatureChannel()
        results = await ch.retrieve("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_weight_affects_score(self):
        ch = TemperatureChannel()
        mm = MockMemoryManager()
        mm._memories = {"m1": _make_memory("m1", "content", temperature=80)}
        r1 = await ch.retrieve("q", weight=1.0, memory_manager=mm)
        r2 = await ch.retrieve("q", weight=0.5, memory_manager=mm)
        assert r2[0].score < r1[0].score

    @pytest.mark.asyncio
    async def test_limit_respected(self):
        ch = TemperatureChannel()
        mm = MockMemoryManager()
        for i in range(20):
            mm._memories[f"m{i}"] = _make_memory(
                f"m{i}", f"mem {i}", temperature=90 - i * 10
            )
        results = await ch.retrieve("q", limit=5, memory_manager=mm)
        assert len(results) == 5

    def test_metadata(self):
        ch = TemperatureChannel()
        assert ch.metadata.name == "temperature"
        assert "temperature" in ch.metadata.capabilities


class TestTextChannel:
    """文本通道测试"""

    @pytest.mark.asyncio
    async def test_keyword_matching(self):
        ch = TextChannel()
        mm = MockMemoryManager()
        mm._memories = {
            "m1": _make_memory("m1", "python programming tutorial"),
            "m2": _make_memory("m2", "java cooking recipe"),
        }
        results = await ch.retrieve("python", limit=10, memory_manager=mm)
        assert len(results) == 2
        assert results[0].memory_id == "m1"
        assert results[0].score > results[1].score

    @pytest.mark.asyncio
    async def test_empty_without_manager(self):
        ch = TextChannel()
        results = await ch.retrieve("query")
        assert results == []

    def test_metadata(self):
        ch = TextChannel()
        assert ch.metadata.name == "text"
        assert "keyword" in ch.metadata.capabilities


class TestCategoryChannel:
    """分类通道测试"""

    @pytest.mark.asyncio
    async def test_non_general_higher_score(self):
        ch = CategoryChannel()
        mm = MockMemoryManager()
        mm._memories = {
            "m1": _make_memory("m1", "c1", category="knowledge"),
            "m2": _make_memory("m2", "c2", category="general"),
        }
        results = await ch.retrieve("q", limit=10, memory_manager=mm)
        assert results[0].score > results[1].score

    @pytest.mark.asyncio
    async def test_empty_without_manager(self):
        ch = CategoryChannel()
        results = await ch.retrieve("query")
        assert results == []

    def test_metadata(self):
        ch = CategoryChannel()
        assert ch.metadata.name == "category"


class TestGraphChannel:
    """图通道测试"""

    @pytest.mark.asyncio
    async def test_more_relations_higher_score(self):
        ch = GraphChannel()
        mm = MockMemoryManager()
        mm._memories = {
            "m1": _make_memory("m1", "c1", metadata={"relations": ["r1", "r2", "r3"]}),
            "m2": _make_memory("m2", "c2", metadata={"relations": []}),
        }
        results = await ch.retrieve("q", limit=10, memory_manager=mm)
        assert results[0].score > results[1].score

    @pytest.mark.asyncio
    async def test_empty_without_manager(self):
        ch = GraphChannel()
        results = await ch.retrieve("query")
        assert results == []

    def test_metadata(self):
        ch = GraphChannel()
        assert ch.metadata.name == "graph"
        assert "relation" in ch.metadata.capabilities


class TestEmotionChannel:
    """情感通道测试"""

    @pytest.mark.asyncio
    async def test_empty_without_manager(self):
        ch = EmotionChannel()
        results = await ch.retrieve("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_without_emotion_module(self):
        ch = EmotionChannel()
        mm = MockMemoryManager()
        results = await ch.retrieve("query", memory_manager=mm)
        assert results == []

    def test_metadata(self):
        ch = EmotionChannel()
        assert ch.metadata.name == "emotion"
        assert "emotion" in ch.metadata.capabilities


class TestVoiceChannel:
    """语音通道测试"""

    @pytest.mark.asyncio
    async def test_filters_voice_memories(self):
        ch = VoiceChannel()
        mm = MockMemoryManager()
        mm._memories = {
            "m1": _make_memory("m1", "hello world", memory_type="asr_transcription",
                               metadata={"record": {"confidence": 0.9, "engine": "whisper"}}),
            "m2": _make_memory("m2", "plain text"),
        }
        results = await ch.retrieve("hello", limit=10, memory_manager=mm)
        assert len(results) == 1
        assert results[0].memory_id == "m1"

    @pytest.mark.asyncio
    async def test_empty_query_returns_all_voice(self):
        ch = VoiceChannel()
        mm = MockMemoryManager()
        mm._memories = {
            "m1": _make_memory("m1", "voice 1", memory_type="asr_transcription",
                               metadata={"record": {"confidence": 0.8}}),
            "m2": _make_memory("m2", "text only"),
        }
        results = await ch.retrieve("", limit=10, memory_manager=mm)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_empty_without_manager(self):
        ch = VoiceChannel()
        results = await ch.retrieve("query")
        assert results == []

    def test_metadata(self):
        ch = VoiceChannel()
        assert ch.metadata.name == "voice"
        assert "asr" in ch.metadata.capabilities


class TestBuiltinChannelImports:
    """验证所有内置通道可正确导入"""

    def test_all_importable(self):
        from neurova.cognitive_layers.memory_layer.channels.builtin import BUILTIN_CHANNELS
        assert len(BUILTIN_CHANNELS) == 6
        names = [cls.__name__ for cls in BUILTIN_CHANNELS]
        assert "TemperatureChannel" in names
        assert "TextChannel" in names
        assert "CategoryChannel" in names
        assert "GraphChannel" in names
        assert "EmotionChannel" in names
        assert "VoiceChannel" in names
