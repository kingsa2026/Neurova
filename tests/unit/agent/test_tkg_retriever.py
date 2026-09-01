# -*- coding: utf-8 -*-
"""TKGRetrieverAdapter 测试（补课 5.2：TKG 孤岛接入检索链）。"""
import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def tkg():
    """Mock TKG：query_tkg_for_context 返回 dict 事实列表。"""
    tkg = MagicMock()

    def fake_query(query, max_facts=10, time_window_days=30):
        return [
            {
                "id": "f1",
                "subject": "用户",
                "predicate": "喜欢",
                "object": "Python",
                "confidence": 0.9,
                "valid_from": "2026-09-01T00:00:00Z",
            }
        ]

    tkg.query_tkg_for_context.side_effect = fake_query
    return tkg


def test_protocol_shape(tkg):
    from neurova.agent.tkg_retriever_adapter import TKGRetrieverAdapter
    from neurova.agent.memory_retrieval_chain import Retriever

    adapter = TKGRetrieverAdapter(tkg)
    # Retriever 是 runtime_checkable Protocol——isinstance 校验属性存在
    assert isinstance(adapter, Retriever)
    assert adapter.name == "TKGRetriever"
    assert adapter.priority == 26


def test_retrieve_maps_fact_to_memory_dict(tkg):
    from neurova.agent.tkg_retriever_adapter import TKGRetrieverAdapter

    adapter = TKGRetrieverAdapter(tkg)
    ctx = MagicMock()
    ctx.query = "用户喜欢什么"
    ctx.limit = 5

    result = asyncio.run(adapter.retrieve(ctx))
    assert result.source == "TKGRetriever"
    assert len(result.memories) == 1
    mem = result.memories[0]
    assert mem["id"] == "f1"
    assert mem["type"] == "tkg_fact"
    assert "用户" in mem["content"] and "Python" in mem["content"]
    assert result.quality > 0


def test_retrieve_empty_returns_failed(tkg):
    from neurova.agent.tkg_retriever_adapter import TKGRetrieverAdapter
    from neurova.agent.memory_retrieval_chain import RetrievalQuality

    tkg.query_tkg_for_context.side_effect = lambda *a, **k: []
    adapter = TKGRetrieverAdapter(tkg)
    ctx = MagicMock()
    ctx.query = "nothing"
    ctx.limit = 5

    result = asyncio.run(adapter.retrieve(ctx))
    assert result.memories == []
    assert result.quality_level == RetrievalQuality.FAILED


def test_registers_into_chain(tkg):
    from neurova.agent.tkg_retriever_adapter import TKGRetrieverAdapter
    from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain

    chain = MemoryRetrievalChain()
    adapter = TKGRetrieverAdapter(tkg)
    chain.add_retriever(adapter)
    names = [r.name for r in chain.get_retrievers()]
    assert "TKGRetriever" in names
