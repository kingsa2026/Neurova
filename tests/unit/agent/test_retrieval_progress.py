"""检索进度回调测试（UI 聊天界面实时显示检索过程）

通路：ChatPipeline._retrieve_memories → RetrievalContext.progress_callback
→ MemoryRetrievalChain 逐级发射（retriever_start/done/error）
→ MoERetrieverAdapter 透传 → MoEMemoryRouter 层事件（moe_gate/expert/done）
→ console/chat event_emitter → SSE `memory_progress`（前端临时显示，不落盘）
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.agent.memory_retrieval_chain import (
    MemoryRetrievalChain,
    RetrievalContext,
    RetrievalResult,
    RetrievalQuality,
    Retriever,
)


def _ctx(**kw):
    return RetrievalContext(query="测试查询", **kw)


def _result(n=2, quality=0.8):
    return RetrievalResult(
        memories=[{"id": f"m{i}", "content": f"记忆{i}"} for i in range(n)],
        source="test",
        quality=quality,
        quality_level=RetrievalQuality.GOOD if quality >= 0.5 else RetrievalQuality.FAIR,
        retrieval_time=0.0,
    )


class _FakeRetriever(Retriever):
    def __init__(self, name, result=None, error=None, priority=10):
        self._name = name
        self._result = result
        self._error = error
        self._priority = priority

    @property
    def name(self):
        return self._name

    @property
    def priority(self):
        return self._priority

    async def retrieve(self, context):
        if self._error:
            raise self._error
        return self._result


class TestChainProgressEvents:
    @pytest.mark.asyncio
    async def test_start_and_done_sequence(self):
        """每个检索器发射 start + done(含命中数/耗时/accepted)"""
        chain = MemoryRetrievalChain()
        chain.add_retriever(_FakeRetriever("A_low", result=_result(1, quality=0.1)))
        chain.add_retriever(_FakeRetriever("B_good", result=_result(3, quality=0.8)))

        events = []
        result = await chain.retrieve(_ctx(progress_callback=events.append))

        stages = [(e["stage"], e["retriever"]) for e in events]
        assert ("retriever_start", "A_low") in stages
        assert ("retriever_start", "B_good") in stages
        assert ("retriever_done", "B_good") in stages

        done_b = next(e for e in events if e["stage"] == "retriever_done" and e["retriever"] == "B_good")
        assert done_b["count"] == 3
        assert done_b["accepted"] is True

    @pytest.mark.asyncio
    async def test_error_emits_retriever_error(self):
        chain = MemoryRetrievalChain()
        chain.add_retriever(_FakeRetriever("bad", error=RuntimeError("boom")))
        chain.add_retriever(_FakeRetriever("good", result=_result(1)))

        events = []
        await chain.retrieve(_ctx(progress_callback=events.append))

        assert any(e["stage"] == "retriever_error" and e["retriever"] == "bad" for e in events)

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break_retrieval(self):
        """进度回调自身抛异常不得阻断检索"""
        chain = MemoryRetrievalChain()
        chain.add_retriever(_FakeRetriever("good", result=_result(2)))

        def bad_cb(event):
            raise ValueError("cb boom")

        result = await chain.retrieve(_ctx(progress_callback=bad_cb))
        assert len(result.memories) == 2


class TestMoEAdapterPassthrough:
    @pytest.mark.asyncio
    async def test_progress_cb_passed_to_router(self):
        from neurova.agent.retriever_adapters import MoERetrieverAdapter

        router = MagicMock()
        router.retrieve = AsyncMock(return_value=[{"id": "m1", "score": 0.9}])
        adapter = MoERetrieverAdapter(router)

        ctx = _ctx(progress_callback=events.append if (events := []) is not None else None)
        await adapter.retrieve(ctx)

        _, kwargs = router.retrieve.call_args
        assert "progress_cb" in kwargs, "adapter 必须把 progress_callback 透传给 MoE 路由器"


class TestMoERouterLayerEvents:
    @pytest.mark.asyncio
    async def test_layer_events_emitted(self):
        """MoE 检索过程发射 moe_gate/moe_expert/moe_done 层级事件"""
        from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter

        router = MoEMemoryRouter(
            experts={"expert_1": {"name": "对话情景记忆", "category": "conversation"}},
            storage=MagicMock(),
            vector_store=MagicMock(),
        )
        # L0/L1 下钻的 store 查询链返回空（MagicMock 链式桩）
        router.storage.execute.return_value.fetchall.return_value = []
        # 真实 onnx encode 返回 numpy 数组（L0 缓存键用 query_vec[:10].tolist()）
        import numpy as np

        router.vector_store.encode = MagicMock(return_value=np.array([0.1, 0.2, 0.3]))
        router.gating_network.route = AsyncMock(return_value={"expert_1": 0.9})
        router.vector_store.search = MagicMock(return_value=[])

        events = []
        results = await router.retrieve("测试", progress_cb=events.append)

        stages = [e["stage"] for e in events]
        assert stages[0] == "moe_gate"
        assert "moe_expert" in stages
        assert stages[-1] == "moe_done"
        gate = events[0]
        assert gate["experts"] == ["expert_1"]
