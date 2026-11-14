# -*- coding: utf-8 -*-
"""B1/B9（billion-context 对照改进项）：模型可调用的上下文工具面。

- B1 `context_compress`：模型自决触发折叠（与 /compact 同一折叠机构）；
- B1 `context_status`：上下文构成/水位/触发读数盘点（只读）；
- B9 `pool_search`：归档池语义检索（与视图抽屉同一打分面）。

契约：
1. 三工具在 _BUILTIN_SCHEMAS 与 ToolExecutor 分派表双登记（不变量测试兜底）；
2. context_compress 走真折叠机构：超预算历史 → 折叠落地、原文入池、回执带计数；
3. context_status 返回预算/折叠/池三面读数；
4. pool_search 按语义相关性返回归档条目（正交内容不混入）。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer
from neurova.tool_executor import ToolExecutor


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


class ControlledVectorStore:
    """need 向量固定 e0；HIT 前缀同向、其余正交（确定性，非 MagicMock）。"""

    def __init__(self, dim: int = 4):
        self._dim = dim

    def _vec(self, text: str):
        v = [0.0] * self._dim
        if text.startswith("HIT"):
            v[0] = 1.0
        else:
            v[1 % self._dim] = 1.0
        return v

    def encode(self, text: str):
        return self._vec(text)

    def encode_batch(self, texts):
        return [self._vec(t) for t in texts]


def _mk_agent():
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
    agent.user_id = "u-b1-iso"
    agent.agent_id = "a-b1-iso"
    return agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _mk_orchestrator(agent, budget: int = 8000) -> ContextOrchestrator:
    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    return orch


class TestRegistration:
    def test_schemas_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in ("context_compress", "context_status", "pool_search"):
            assert name in _BUILTIN_SCHEMAS, f"{name} 未登记 schema"

    def test_dispatch_registered(self):
        from neurova.tool_executor import ToolExecutor

        for name in ("context_compress", "context_status", "pool_search"):
            assert name in ToolExecutor._builtin_dispatch, f"{name} 未登记执行体"


class TestContextCompressTool:
    @pytest.mark.asyncio
    async def test_compress_folds_overbudget_history(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期讨论主题X。"

        agent.context_orchestrator = orch
        orch._window_summarizer = fake_summarize
        agent.conversation_history = [_long_msg(i) for i in range(30)]

        executor = ToolExecutor(agent)
        receipt = await executor.execute_tool("context_compress", {"reason": "阶段完成"})

        assert receipt.get("compacted") is True, f"应真折叠：{receipt}"
        assert receipt.get("invoked_by") == "model"
        assert receipt.get("reason") == "阶段完成"
        assert receipt.get("tokens_after", 0) < receipt.get("tokens_before", 0)

    @pytest.mark.asyncio
    async def test_compress_without_orchestrator_reports_honestly(self):
        agent = _mk_agent()
        executor = ToolExecutor(agent)  # 未挂 orchestrator
        receipt = await executor.execute_tool("context_compress", {})
        assert "error" in receipt


class TestContextStatusTool:
    @pytest.mark.asyncio
    async def test_status_returns_budget_fold_pool_faces(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent)
        agent.context_orchestrator = orch
        agent.conversation_history = [_long_msg(i) for i in range(5)]

        executor = ToolExecutor(agent)
        status = await executor.execute_tool("context_status", {})

        assert "window" in status and "budget_tokens" in status["window"]
        assert "fold" in status and "last_reason" in status["fold"]
        assert "pool" in status


class TestPoolSearchTool:
    @pytest.mark.asyncio
    async def test_search_returns_semantic_matches(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent)
        agent.context_orchestrator = orch
        pool = orch.context_pool
        pool._drawer._vector_store = ControlledVectorStore()
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="HIT 固件升级失败回滚记录", priority=60, tokens=50))
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="MISS 今天天气不错", priority=60, tokens=50))

        executor = ToolExecutor(agent)
        result = await executor.execute_tool("pool_search", {"query": "HIT 固件升级", "limit": 5})

        hits = result.get("results", [])
        assert hits, "应命中同向归档"
        assert all("天气" not in str(h.get("content", "")) for h in hits), "正交内容不得混入"

    @pytest.mark.asyncio
    async def test_search_requires_query(self):
        agent = _mk_agent()
        agent.context_orchestrator = _mk_orchestrator(agent)
        executor = ToolExecutor(agent)
        result = await executor.execute_tool("pool_search", {})
        assert "error" in result
