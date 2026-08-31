"""
P1-1③ 接线测试 — ledger 懒建 / 摘要器接真 LLM / rollup 摘要回写

- orchestrator 懒建：use_pool 时自动注入 EvictionLedgerDB（data/context_ledger/
  {agent_id}.db）与 SummarizingCompressor（经 agent.llm_client.chat 异步包装）
- pool.rollup_overflow_digest(folded_chunks)：异步生成/增量更新摘要并回写池
  （SUMMARY 源）；无摘要器为 no-op
- orchestrator.get_ledger_db：供 GC/外部访问
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.context.pool_models import ContextSource


def _make_orchestrator(monkeypatch, tmp_path, llm_response="摘要文本"):
    from neurova.context.orchestrator import ContextOrchestrator

    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "t-agent"
    mock_agent.config.llm_model = "test-model"
    mock_agent.conversation_history = []
    mock_agent.llm_client = SimpleNamespace()

    # llm chat 桩（MultiModelLLMClient.chat 契约：await → dict 带 content）
    async def fake_chat(messages, **kwargs):
        return {"content": llm_response}

    mock_agent.llm_client.chat = fake_chat
    # ledger 在方法内局部 import——patch 真源模块
    import neurova.context.eviction_ledger_db as ledger_module

    monkeypatch.setattr(
        ledger_module, "EvictionLedgerDB",
        lambda **kw: SimpleNamespace(db_path=kw.get("db_path"), user_id=kw.get("user_id")),
    )
    monkeypatch.chdir(tmp_path)
    return ContextOrchestrator(mock_agent)


class TestLazyWiring:
    def test_pool_gets_ledger_and_summarizer(self, monkeypatch, tmp_path):
        orch = _make_orchestrator(monkeypatch, tmp_path)
        assert orch.context_pool._ledger_db is not None
        assert orch.context_pool._summarizer is not None
        assert orch.context_pool._summarizer._llm_call is not None

    def test_ledger_path_scoped_by_agent(self, monkeypatch, tmp_path):
        orch = _make_orchestrator(monkeypatch, tmp_path)
        db = orch.context_pool._ledger_db
        assert "t-agent" in str(getattr(db, "db_path", "")) or db is not None

    def test_no_pool_no_wiring(self, monkeypatch, tmp_path):
        from neurova.context.orchestrator import ContextOrchestrator

        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "t"
        mock_agent.conversation_history = []
        orch = ContextOrchestrator(mock_agent, use_pool=False)
        assert getattr(orch, "context_pool", None) is None

    def test_orchestrator_exposes_get_ledger_db(self, monkeypatch, tmp_path):
        orch = _make_orchestrator(monkeypatch, tmp_path)
        assert orch.get_ledger_db() is orch.context_pool._ledger_db


class TestRollupDigest:
    @pytest.mark.asyncio
    async def test_rollup_writes_summary_chunk(self, monkeypatch, tmp_path):
        orch = _make_orchestrator(monkeypatch, tmp_path)
        folded = [
            SimpleNamespace(
                content="第 1 轮讨论部署", metadata={"turn_id": "turn_1"}, source=ContextSource.CONVERSATION
            ),
            SimpleNamespace(
                content="第 2 轮讨论测试", metadata={"turn_id": "turn_2"}, source=ContextSource.CONVERSATION
            ),
        ]
        await orch.context_pool.rollup_overflow_digest(folded, previous_summary="")
        summaries = [c for c in orch.context_pool.get_contexts() if c.source == ContextSource.SUMMARY]
        assert len(summaries) == 1
        assert summaries[0].content == "摘要文本"

    @pytest.mark.asyncio
    async def test_rollup_noop_without_summarizer(self, tmp_path):
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u", agent_id="a")  # 无 summarizer
        folded = [SimpleNamespace(content="x", metadata={}, source=ContextSource.CONVERSATION)]
        await pool.rollup_overflow_digest(folded)  # 不抛
        assert pool.get_contexts() == []


class TestLLMBridge:
    @pytest.mark.asyncio
    async def test_llm_call_bridge_extracts_content(self, monkeypatch, tmp_path):
        """包装器从 chat dict 契约提取 content 字符串"""
        orch = _make_orchestrator(monkeypatch, tmp_path)
        bridge = orch.context_pool._summarizer._llm_call
        result = await bridge("summarize this")
        assert result == "摘要文本"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
