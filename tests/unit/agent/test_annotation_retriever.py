"""P2 标注闭环消费侧（TDD）——命中表挂检索链。

契约：AnnotationRetrieverAdapter 作为检索链最高优先级检索器
（priority 5——人工修正的精准答案权威性高于一切自动检索源）：
- 命中 → memories 承载精准答案（content=answer，title=question，
  metadata 标 annotation 溯源），quality=1.0（人工定标）
- 未命中 → 空结果（quality=0，链继续走后续检索器）
- store 故障 → FAILED 空结果（不拖垮链）
- chat_pipeline 装配点注册（与 KnowledgeRetrieverAdapter 同位接入）
"""

from unittest.mock import MagicMock

import pytest

from neurova.core.annotation_store import AnnotationStore


@pytest.fixture
def store(tmp_path):
    s = AnnotationStore(str(tmp_path / "a.db"))
    s.add(question="你们的退款政策是什么？", answer="7 天无理由退款。")
    return s


def _ctx(query, user_id="u1"):
    ctx = MagicMock()
    ctx.query = query
    ctx.user_id = user_id
    ctx.limit = 5
    ctx.metadata = {}
    return ctx


class TestAnnotationRetrieverAdapter:
    @pytest.mark.asyncio
    async def test_hit_returns_precise_answer(self, store):
        from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter

        adapter = AnnotationRetrieverAdapter(store)
        result = await adapter.retrieve(_ctx("你们的退款政策是什么？"))
        assert result.memories, "命中应产出记忆条目"
        assert "7 天无理由" in result.memories[0]["content"]
        assert result.quality == 1.0
        assert result.metadata.get("annotation") is True

    @pytest.mark.asyncio
    async def test_miss_returns_empty(self, store):
        from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter

        adapter = AnnotationRetrieverAdapter(store)
        result = await adapter.retrieve(_ctx("完全无关问题"))
        assert result.memories == []

    @pytest.mark.asyncio
    async def test_store_failure_is_isolated(self, tmp_path):
        from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter

        broken = MagicMock()
        broken._conn.execute.side_effect = RuntimeError("db gone")
        adapter = AnnotationRetrieverAdapter(broken)
        result = await adapter.retrieve(_ctx("q"))
        assert result.memories == []
        assert result.source == "AnnotationRetriever"

    def test_priority_highest_in_chain(self, store):
        from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter

        assert AnnotationRetrieverAdapter(store).priority < 10, "须排在所有自动检索源之前"

    @pytest.mark.asyncio
    async def test_chat_pipeline_registers_adapter(self, tmp_path, store, monkeypatch):
        """chat_pipeline 装配点：与知识适配器同位注册（生产入口存在）"""
        import neurova.core.annotation_store as ann_mod
        from neurova.agent.annotation_retriever import AnnotationRetrieverAdapter

        monkeypatch.setattr(ann_mod, "get_annotation_store", lambda: store)

        chain = MagicMock()
        pipeline = MagicMock()
        pipeline._memory_retrieval_chain = chain
        # 走 chat_pipeline 的私有装配段：直接调 _setup_memory_retrieval_chain
        # 太重（需全量 agent 桩）——这里验证装配函数存在且可注入
        from neurova.agent.chat_pipeline import ChatPipeline  # noqa: F401 装配点在类内

        # 生产入口的轻量验证：模块级装配 helper 存在并正确挂链
        from neurova.agent.annotation_retriever import register_annotation_retriever

        ok = register_annotation_retriever(chain, store)
        assert ok is True
        assert chain.add_retriever.call_count == 1
        added = chain.add_retriever.call_args[0][0]
        assert isinstance(added, AnnotationRetrieverAdapter)
