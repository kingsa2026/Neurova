# -*- coding: utf-8 -*-
"""第四批（billion-context 对照改进项）：B7 单条巨结果封顶＋B10 召回需求锚＋B11 向量缓存。

- B7：单条超限工具结果即便在保留窗（最新）也被换占位指针（CCR 同语义）；
- B10：召回需求锚 = 当前输入 + 近轮要点（短输入不再退化成"最近优先"）；
- B11：抽屉向量实例级 LRU 缓存——同文本跨轮不重复编码。
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _mk_agent(agent_id="a-b4-iso"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-b4-iso"
    agent.agent_id = agent_id
    return agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


class CountingVectorStore:
    """计数编码次数（真契约替身，确定性向量）。"""

    def __init__(self, dim: int = 4):
        self._dim = dim
        self.encode_calls = {}

    def _vec(self, text: str):
        v = [0.0] * self._dim
        if text.startswith("HIT"):
            v[0] = 1.0
        else:
            v[1 % self._dim] = 1.0
        return v

    def encode(self, text: str):
        self.encode_calls[text] = self.encode_calls.get(text, 0) + 1
        return self._vec(text)

    def encode_batch(self, texts):
        return [self.encode(t) for t in texts]


class TestB7SingleResultCeiling:
    def _mk_orchestrator(self, budget=8000):
        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        orch._window_token_budget = budget
        return orch

    async def _build(self, orch, session_context, user_input="继续"):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            return await orch.build_context(
                user_input=user_input, session_context=session_context, relevant_memories=[]
            )

    @pytest.mark.asyncio
    async def test_single_huge_recent_tool_result_capped(self):
        """最新一条工具结果超单条封顶：也换占位指针（CCR 同语义）。"""
        orch = self._mk_orchestrator(budget=100000)  # 预算给足：不触发整窗折叠
        orch._window_hard_limit = 1000000
        huge = "测" * 48000  # ≈48k token（CJK 近 1 token/字），稳超单条封顶 6000
        ctx = [
            {"role": "user", "content": "查一下"},
            {"role": "assistant", "content": "好的", "tool_calls": [
                {"id": "tc-huge", "type": "function", "function": {"name": "web_fetch", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc-huge", "name": "web_fetch", "content": huge},
        ]
        view = await self._build(orch, ctx)
        tool_rows = [m for m in view if m.get("role") == "tool"]
        assert tool_rows, "工具结果行应保留（换成指针）"
        assert all("已移出上下文" in str(m.get("content", "")) for m in tool_rows), (
            "超限巨结果应被占位指针替换"
        )
        joined = "".join(str(m.get("content", "")) for m in view)
        assert "call=tc-huge" in joined, "占位指针必须带 call= 硬地址"
        # 原文零丢失：池里能按 hash 找到该结果
        hashes = orch._last_archived_window_hashes
        assert hashes, "折叠前应完成归档"

    @pytest.mark.asyncio
    async def test_small_recent_tool_result_stays(self):
        """小工具结果不受封顶影响。"""
        orch = self._mk_orchestrator(budget=100000)
        orch._window_hard_limit = 1000000
        ctx = [
            {"role": "user", "content": "查一下"},
            {"role": "assistant", "content": "好的", "tool_calls": [
                {"id": "tc-small", "type": "function", "function": {"name": "web_fetch", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc-small", "name": "web_fetch", "content": "结果：200 OK"},
        ]
        view = await self._build(orch, ctx)
        tool_rows = [m for m in view if m.get("role") == "tool"]
        assert tool_rows and "200 OK" in str(tool_rows[0].get("content", ""))


class TestB10NeedAnchor:
    def test_anchor_contains_recent_turns_when_enabled(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RECALL_NEED_ENRICH", "1")
        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        window = [
            {"role": "user", "content": "先看看缓存淘汰策略的代码"},
            {"role": "assistant", "content": "已定位到 LRU 实现"},
        ]
        anchor = orch._buildRecallNeedAnchor("继续", window)
        assert "继续" in anchor
        assert "缓存淘汰策略" in anchor and "LRU" in anchor

    def test_anchor_default_off_returns_input_only(self, monkeypatch):
        """默认关：0.65 门槛按纯输入锚校准，复合锚未校准前不得默认启用。"""
        monkeypatch.delenv("NEUROVA_RECALL_NEED_ENRICH", raising=False)
        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        window = [{"role": "user", "content": "先看看缓存淘汰策略的代码"}]
        assert orch._buildRecallNeedAnchor("继续", window) == "继续"

    def test_anchor_off_returns_input_only(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RECALL_NEED_ENRICH", "0")
        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        window = [{"role": "user", "content": "先看看缓存淘汰策略的代码"}]
        assert orch._buildRecallNeedAnchor("继续", window) == "继续"

    @pytest.mark.asyncio
    async def test_draw_receives_enriched_anchor(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RECALL_NEED_ENRICH", "1")
        agent = _mk_agent()
        orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
        agent.context_orchestrator = orch
        captured = {}
        real_draw = orch.context_pool.draw

        def spying_draw(need=None, budget_tokens=None):
            captured["need"] = need
            return real_draw(need=need, budget_tokens=budget_tokens)

        orch.context_pool.draw = spying_draw
        window = [{"role": "user", "content": "先看看缓存淘汰策略的代码"}]
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            await orch.build_context(user_input="继续", session_context=window, relevant_memories=[])
        assert "缓存淘汰策略" in captured["need"], "draw 应收到增强后的需求锚"


class TestB11VectorCache:
    def test_second_draw_skips_reencode(self):
        drawer = SemanticMatchDrawer(max_tokens=10 ** 9)
        store = CountingVectorStore()
        drawer._vector_store = store
        drops = [
            ContextInput(source=ContextSource.MEMORY, content="HIT 固件升级失败回滚记录", priority=60, tokens=10),
            ContextInput(source=ContextSource.MEMORY, content="MISS 今天天气不错", priority=60, tokens=10),
        ]
        drawer.draw(drops, need="HIT 固件升级")
        first = dict(store.encode_calls)
        drawer.draw(drops, need="HIT 固件升级")
        second = dict(store.encode_calls)
        assert first, "首轮应真实编码"
        assert second == first, f"第二轮同文本不得重编码：{first} -> {second}"
        assert len(drawer._vectorCache) >= 3, "need+两条候选都应入缓存"

    def test_cache_bounded_lru(self):
        drawer = SemanticMatchDrawer(max_tokens=10 ** 9)
        drawer._VECTOR_CACHE_CAPACITY = 4
        store = CountingVectorStore()
        drawer._vector_store = store
        for i in range(10):
            drawer._cachedEncode(store, f"文本{i}")
        assert len(drawer._vectorCache) <= 4, "缓存必须按容量截断"
