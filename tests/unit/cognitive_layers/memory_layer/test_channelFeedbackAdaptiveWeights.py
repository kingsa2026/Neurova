"""反馈自适应通道权重（§6-377）：先补写侧，再接召回读侧。

写侧契约：
- 召回时（带 session_id）记录本轮意图与**真贡献过结果的通道**；
- like/dislike 按该归属调整 `IntentAwareRecallStrategy` 的意图权重，归一化并落盘；
- 读侧仍是 `get_channel_weights`（召回路已用），不另造第二套权重表。
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.agent.retriever_adapters import UnifiedRetrieverAdapter
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    IntentAwareRecallStrategy,
    NeurovaRecallEngine,
    QueryIntent,
    RecallChannel,
)


@pytest.fixture(autouse=True)
def _isolateDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))


def _namespace() -> str:
    return "test_feedback_" + uuid.uuid4().hex[:8]


def test_likeRaisesContributingChannelWeight():
    strategy = IntentAwareRecallStrategy(namespace=_namespace())
    before = strategy.get_channel_weights(QueryIntent.FACTUAL)

    after = strategy.applyFeedback(QueryIntent.FACTUAL, ["text"], True)

    assert after[RecallChannel.TEXT] > before[RecallChannel.TEXT]
    assert sum(after.values()) == pytest.approx(1.0, abs=1e-6)


def test_dislikeLowersContributingChannelWeight():
    strategy = IntentAwareRecallStrategy(namespace=_namespace())
    before = strategy.get_channel_weights(QueryIntent.FACTUAL)

    after = strategy.applyFeedback(QueryIntent.FACTUAL, ["text"], False)

    assert after[RecallChannel.TEXT] < before[RecallChannel.TEXT]
    assert sum(after.values()) == pytest.approx(1.0, abs=1e-6)


def test_weightsPersistAcrossInstances():
    namespace = _namespace()
    first = IntentAwareRecallStrategy(namespace=namespace)
    adjusted = first.applyFeedback(QueryIntent.FACTUAL, ["text"], True)

    second = IntentAwareRecallStrategy(namespace=namespace)
    reloaded = second.get_channel_weights(QueryIntent.FACTUAL)

    assert reloaded[RecallChannel.TEXT] == pytest.approx(adjusted[RecallChannel.TEXT], abs=1e-6)


def test_unknownChannelDoesNotChangeWeights():
    strategy = IntentAwareRecallStrategy(namespace=_namespace())
    before = strategy.get_channel_weights(QueryIntent.FACTUAL)

    after = strategy.applyFeedback(QueryIntent.FACTUAL, ["not-a-channel"], True)

    assert after == before


def test_engineWithoutAttributionDoesNotGuess():
    strategy = IntentAwareRecallStrategy(namespace=_namespace())
    engine = NeurovaRecallEngine(
        memory_manager=None, use_plugins=False, intent_strategy=strategy)

    assert engine.applyChannelFeedback("never-recalled", True) == {}


def test_engineAttributionDrivesFeedback():
    strategy = IntentAwareRecallStrategy(namespace=_namespace())
    engine = NeurovaRecallEngine(
        memory_manager=None, use_plugins=False, intent_strategy=strategy)
    engine._recordRecallAttribution(
        "s1", QueryIntent.FACTUAL, [SimpleNamespace(channel=RecallChannel.TEXT)])

    attribution = engine.getRecallAttribution("s1")
    before = strategy.get_channel_weights(QueryIntent.FACTUAL)
    engine.applyChannelFeedback("s1", True)
    after = strategy.get_channel_weights(QueryIntent.FACTUAL)

    assert attribution == {"intent": "factual", "channels": ["text"]}
    assert after[RecallChannel.TEXT] > before[RecallChannel.TEXT]


def test_recallFlatRecordsAttributionFromRealChannels():
    """正控：归属由真召回路径写入（不是测试手动调私有方法造出来的）。"""
    from neurova.cognitive_layers.memory_layer.channels.base import (
        BaseChannel,
        ChannelMetadata,
        ChannelResult,
    )

    class FakeTextChannel(BaseChannel):
        @property
        def metadata(self):
            return ChannelMetadata(name="text", display_name="文本", description="fake")

        async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
            return [ChannelResult(
                memory_id="m1", content="巴黎是法国首都", score=0.9, channel="text")]

    class FakeRegistry:
        def get_active(self):
            return [FakeTextChannel()]

    strategy = IntentAwareRecallStrategy(namespace=_namespace())
    engine = NeurovaRecallEngine(
        memory_manager=None, use_plugins=True, registry=FakeRegistry(),
        intent_strategy=strategy, timeout_seconds=5.0)

    results = engine.recall_flat(
        "巴黎是法国首都", limit=3, query_intent=QueryIntent.FACTUAL, session_id="s-real")

    assert [m.channel for m in results] == [RecallChannel.TEXT]
    assert engine.getRecallAttribution("s-real") == {"intent": "factual", "channels": ["text"]}

    before = strategy.get_channel_weights(QueryIntent.FACTUAL)
    engine.applyChannelFeedback("s-real", True)
    after = strategy.get_channel_weights(QueryIntent.FACTUAL)
    assert after[RecallChannel.TEXT] > before[RecallChannel.TEXT]


def test_pluginChannelsActivateOnFirstRecall():
    """注册≠可用：生产没有启动钩子，首次召回必须补激活，否则插件召回恒空。"""
    from neurova.cognitive_layers.memory_layer.channels.base import (
        BaseChannel,
        ChannelMetadata,
        ChannelResult,
        ChannelState,
    )

    class FakeTextChannel(BaseChannel):
        @property
        def metadata(self):
            return ChannelMetadata(name="text", display_name="文本", description="fake")

        async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
            return [ChannelResult(
                memory_id="m1", content="巴黎是法国首都", score=0.9, channel="text")]

    class LazyRegistry:
        """只注册不激活——与生产 `get_channel_registry()` 的现状一致。"""

        def __init__(self):
            self.channel = FakeTextChannel()

        def get_active(self):
            return [self.channel] if self.channel.get_state() == ChannelState.ACTIVE else []

        def get_all(self):
            return [self.channel]

        async def initialize_all(self):
            await self.channel.initialize()
            return {"text": True}

    engine = NeurovaRecallEngine(
        memory_manager=None, use_plugins=True, registry=LazyRegistry(),
        intent_strategy=IntentAwareRecallStrategy(namespace=_namespace()),
        timeout_seconds=5.0)

    assert engine._registry.get_active() == [], "前提：注册后尚未激活"
    results = engine.recall_flat("巴黎是法国首都", limit=3, query_intent=QueryIntent.FACTUAL)

    assert [m.memory_id for m in results] == ["m1"]
    assert engine._registry.get_active(), "首次召回后通道必须已激活"


def test_unifiedRetrieverAdapterPassesSessionId():
    class FakeRetriever:
        def __init__(self):
            self.seenSession = None

        def retrieve(self, query, limit=10, session_id=None):
            self.seenSession = session_id
            return [{"id": "m1", "content": "x"}]

    fake = FakeRetriever()
    adapter = UnifiedRetrieverAdapter(fake)

    asyncio.run(adapter.retrieve(RetrievalContext(
        query="q", limit=5, session_id="session-42")))

    assert fake.seenSession == "session-42"


def test_consoleFeedbackHookCallsMemoryAgent(monkeypatch):
    from neurova.api.endpoints import console

    calls = []

    class FakeMemoryAgent:
        def apply_feedback_to_channel_weights(self, session_id, feedback):
            calls.append((session_id, feedback))
            return 1

    class FakeAgent:
        memory_agent = FakeMemoryAgent()

    monkeypatch.setattr(console, "get_agent_instance", lambda agent_id=None: FakeAgent())

    console._apply_feedback_to_channels("agent", "session-42", "like")

    assert calls == [("session-42", "like")]
