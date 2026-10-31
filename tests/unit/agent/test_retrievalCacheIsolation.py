# -*- coding: utf-8 -*-
"""S4 检索结果缓存隔离（specs/2026-10-31-full-repo-defect-sweep-fixplan.md）。

缺陷：缓存键只有 query 文本（无 user/agent 维度）且无 TTL——同一 agent 服务
多用户时，用户 B 的检索异常/低质会整包命中用户 A 留下的缓存（跨用户记忆
泄漏），陈旧结果永不过期。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.agent.memory_retrieval_chain import (
    MemoryRetrievalChain,
    RetrievalContext,
    RetrievalQuality,
    RetrievalResult,
)


class _FakeRetriever:
    name = "FakeRetriever"
    priority = 99

    def __init__(self):
        self.calls = []

    def get_quality_score(self, results, query):
        return 0.9

    async def retrieve(self, context):
        self.calls.append(context.user_id)
        return RetrievalResult(
            memories=[{"id": f"mem-{context.user_id}",
                       "content": f"result-for-{context.user_id}"}],
            source=self.name,
            quality=0.9,
            quality_level=RetrievalQuality.EXCELLENT,
            retrieval_time=0.0,
        )


@pytest.fixture()
def chain():
    c = MemoryRetrievalChain()
    fake = _FakeRetriever()
    c.add_retriever(fake)
    return c, fake


def _ctx(user_id: str) -> RetrievalContext:
    return RetrievalContext(
        query="同一句话", limit=5, user_id=user_id,
        metadata={"agent_id": "agentA", "tenant_id": "default"},
    )


def test_s4_same_query_different_users_must_not_share_cache(chain):
    """跨用户同查询不得命中他人缓存（修前第二次直接吃缓存，检索器只跑一次）。"""
    chain, fake = chain
    first = asyncio.run(chain.retrieve(_ctx("u1")))
    second = asyncio.run(chain.retrieve(_ctx("u2")))

    assert fake.calls == ["u1", "u2"], (
        f"不同用户的同查询必须各跑各的检索，实得调用序列 {fake.calls}"
    )
    assert second.memories[0]["id"] == "mem-u2"


def test_s4_cache_entry_expires(chain, monkeypatch):
    """缓存条目带 TTL：过期后重新检索（不再永不过期）。"""
    import time

    chain, fake = chain
    asyncio.run(chain.retrieve(_ctx("u1")))
    assert fake.calls == ["u1"]

    # 把唯一条目的落缓存时刻拨回 TTL 之外
    assert len(chain._cache) == 1
    key = next(iter(chain._cache))
    result, _ = chain._cache[key]
    chain._cache[key] = (result, time.monotonic() - chain._cache_ttl_seconds - 1)

    asyncio.run(chain.retrieve(_ctx("u1")))
    assert fake.calls == ["u1", "u1"], "过期条目必须失效重检"


def test_s4_cache_key_includes_user_scope(chain):
    """键含 user/agent/tenant 维度（同查询不同用户 → 不同键）。"""
    chain, _ = chain
    assert chain._get_cache_key(_ctx("u1")) != chain._get_cache_key(_ctx("u2"))
