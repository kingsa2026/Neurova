"""
P1-1③ 余项 — recall_history 工具注册红测

把驱逐台账召回暴露为 LLM 可调用的内置工具（三件套契约）：
- BuiltinToolRegistry 有 recall_history schema
- tool_executor._builtin_dispatch 有分派入口
- executor 方法经 agent.context_orchestrator.context_pool 召回
"""

import time
from pathlib import Path

import pytest

from neurova.builtin_tools import BuiltinToolRegistry
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool
from types import SimpleNamespace


class TestSchemaAndDispatch:
    def test_schema_registered(self):
        registry = BuiltinToolRegistry()
        assert registry.has_tool("recall_history")
        schema = registry.get_tool("recall_history")
        assert "query" in schema.parameters.get("properties", {})
        assert "被折叠" in schema.description or "召回" in schema.description

    def test_dispatch_entry_exists(self):
        from neurova.tool_executor import ToolExecutor

        assert "recall_history" in ToolExecutor._builtin_dispatch


class TestExecutor:
    def _make_executor_with_pool(self):
        from neurova.tool_executor import ToolExecutor

        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        orchestrator = SimpleNamespace(context_pool=pool)
        agent = SimpleNamespace(
            _current_user_id="u1",
            config=SimpleNamespace(user_id="u1", agent_id="a1"),
            context_orchestrator=orchestrator,
        )
        return ToolExecutor(agent), pool

    @pytest.mark.asyncio
    async def test_recalls_evicted_content(self):
        executor, pool = self._make_executor_with_pool()
        chunk = ContextInput(
            source=ContextSource.CONVERSATION,
            content="早期讨论了 PostgreSQL 索引优化",
            metadata={"turn_id": "turn_1"},
        )
        pool._archive_evicted(chunk)

        result = await executor._execute_recall_history({"query": "PostgreSQL 索引"})
        assert result.get("success") is True
        assert result.get("count") == 1
        assert "PostgreSQL 索引优化" in result["recalled"][0]["content"]

    @pytest.mark.asyncio
    async def test_no_query_returns_recent(self):
        executor, pool = self._make_executor_with_pool()
        pool._archive_evicted(
            ContextInput(source=ContextSource.CONVERSATION, content="最近被折叠的内容")
        )
        result = await executor._execute_recall_history({})
        assert result.get("success") is True and result.get("count") == 1

    @pytest.mark.asyncio
    async def test_pool_unavailable_returns_error(self):
        from neurova.tool_executor import ToolExecutor

        agent = SimpleNamespace(
            config=SimpleNamespace(user_id="u1", agent_id="a1"),
            context_orchestrator=None,
        )
        executor = ToolExecutor(agent)
        result = await executor._execute_recall_history({"query": "x"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_end_to_end_eviction_then_recall(self, tmp_path):
        """端到端：TTL 驱逐 → 台账 → recall_history 召回（验收口径链路）"""
        from neurova.context.eviction_ledger_db import EvictionLedgerDB

        ledger = EvictionLedgerDB(
            db_path=Path(tmp_path) / "l.db", user_id="u1", agent_id="a1"
        )
        executor, pool = self._make_executor_with_pool()
        pool._ledger_db = ledger
        pool.ttl_seconds = 0.05
        pool.add_context(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content="重启前的上海天气讨论",
                metadata={"turn_id": "turn_1"},
            )
        )
        time.sleep(0.08)
        pool.cleanup_expired()

        result = await executor._execute_recall_history({"query": "上海天气"})
        assert result.get("success") is True
        assert result.get("count") == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
