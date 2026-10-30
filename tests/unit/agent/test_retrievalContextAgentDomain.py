# -*- coding: utf-8 -*-
"""检索上下文必须带本 agent 的域与租户/角色（specs/2026-10-30 W1–W4 的前置接线）。

W1 别名归一、W2 脱靶登记、W3 图锚都按 `metadata["agent_id"]` 取作用域：
缺了它，归一与登记整段静默跳过，图锚 `subjectsMentionedIn(agentId=None)`
反而**不加 agent 过滤**——从别人的主体表里挑起点。三条检索路径（主路、
Active Memory 升级、Adaptive 二次检索）必须同源带同一份身份域。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.memory_retrieval_chain import RetrievalQuality, RetrievalResult
from neurova.collaboration.memory_scope import turnScopeContext


class CapturingChain:
    """只记录传进来的 RetrievalContext，按次返回预置结果。"""

    def __init__(self, results):
        self.contexts = []
        self._results = list(results)

    async def retrieve(self, context):
        self.contexts.append(context)
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


def _result(quality: float, memories=None) -> RetrievalResult:
    level = RetrievalQuality.EXCELLENT if quality >= 0.9 else RetrievalQuality.FAILED
    return RetrievalResult(
        memories=list(memories or []),
        source="stub",
        quality=quality,
        quality_level=level,
        retrieval_time=0.0,
        metadata={},
    )


def _pipeline(chain) -> ChatPipeline:
    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="agentX", user_id="u1", llm_config=None),
        llm_client=None,
    )
    pipeline = object.__new__(ChatPipeline)
    pipeline._agent = agent
    pipeline._memory_retrieval_chain = chain
    return pipeline


def _ctx(userInput: str, **metadata) -> ChatContext:
    ctx = ChatContext(user_input=userInput)
    ctx.metadata = {"role": "admin", "tenant_id": "tenant-7", **metadata}
    ctx.reasoning_trace_id = None
    return ctx


def _assertDomain(meta, *, extraKey=None):
    assert meta.get("agent_id") == "agentX", "检索上下文缺本 agent 的域"
    assert meta.get("tenant_id") == "tenant-7", "租户必须随同一份身份下发"
    assert meta.get("role") == "admin", "角色透传缺失会让 admin 的可见面缩水"
    if extraKey:
        assert meta.get(extraKey) is True


@pytest.mark.asyncio
async def test_mainRetrievalContext_carriesAgentDomain():
    chain = CapturingChain([_result(0.9, [{"content": "命中", "score": 0.9}])])
    pipeline = _pipeline(chain)
    ctx = _ctx("阿尔法指标是什么")

    await pipeline._retrieve_memories(ctx, turnScopeContext(ctx.metadata, ctx.session_id))

    assert len(chain.contexts) == 1
    _assertDomain(chain.contexts[0].metadata)


@pytest.mark.asyncio
async def test_activeMemoryEscalationContext_carriesAgentDomain(monkeypatch):
    monkeypatch.setenv("NEUROVA_ACTIVE_MEMORY", "1")
    chain = CapturingChain([
        _result(0.1),
        _result(0.8, [{"content": "深检索补充", "score": 0.8}]),
    ])
    pipeline = _pipeline(chain)
    ctx = _ctx("上次我们聊过的阿尔法指标是什么")

    await pipeline._retrieve_memories(ctx, turnScopeContext(ctx.metadata, ctx.session_id))

    assert len(chain.contexts) == 2, "回溯型提问 + 低质首查应触发深检索"
    _assertDomain(chain.contexts[1].metadata, extraKey="active_memory_escalation")


@pytest.mark.asyncio
async def test_adaptiveSecondRetrievalContext_carriesAgentDomain(monkeypatch):
    monkeypatch.setenv("NEUROVA_ADAPTIVE_RETRIEVAL", "1")
    chain = CapturingChain([
        _result(0.1),
        _result(0.8, [{"content": "拆解子问题命中", "score": 0.8}]),
    ])
    pipeline = _pipeline(chain)
    ctx = _ctx("阿尔法指标是什么")

    async def _fakeDecompose(query):
        return ["阿尔法指标口径"]

    monkeypatch.setattr(pipeline, "_decompose_query", _fakeDecompose)

    await pipeline._retrieve_memories(ctx, turnScopeContext(ctx.metadata, ctx.session_id))

    assert len(chain.contexts) == 2, "低质首查应触发 Adaptive 二次检索"
    _assertDomain(chain.contexts[1].metadata, extraKey="adaptive")
