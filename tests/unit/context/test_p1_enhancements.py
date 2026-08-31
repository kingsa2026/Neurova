"""
P1-1③ 增强（收尾批）：folded_messages 产出 + GC piggyback + rollup 串联
"""

import asyncio

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.recovery import compact_messages_for_overflow
from neurova.context_pool import ContextPool


def _turn(i):
    return [
        {"role": "user", "content": f"question {i}"},
        {"role": "assistant", "content": f"answer {i}"},
    ]


class TestFoldedMessagesInfo:
    def test_info_contains_folded_messages(self):
        msgs = [{"role": "system", "content": "sys"}] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        compact, info = compact_messages_for_overflow(msgs, recent_keep=6)
        assert info["folded_count"] > 0
        assert info["folded_messages"] == [m for m in msgs if m not in compact]
        # 锚点（首条 user）保留 → 折叠从中段开始（answer 1 起）
        assert info["folded_messages"][0]["content"] == "answer 1"
        assert "question 1" not in [m["content"] for m in info["folded_messages"]]

    def test_no_fold_empty_list(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
        _, info = compact_messages_for_overflow(msgs, recent_keep=6)
        assert info["folded_messages"] == []


class TestGCPiggyback:
    def test_gc_triggers_every_n_evictions(self, tmp_path):
        from neurova.context.eviction_ledger_db import EvictionLedgerDB

        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        pool = ContextPool(user_id="u", agent_id="a", session_id="s", ttl_seconds=0.01, ledger_db=ledger)

        gc_calls = {"n": 0}
        original_gc = ledger.gc

        def counting_gc(**kw):
            gc_calls["n"] += 1
            return original_gc(**kw)

        ledger.gc = counting_gc
        # 超过默认阈值（20）的驱逐次数
        for i in range(25):
            pool.add_context(_chunk(f"c{i}"))
            import time
            time.sleep(0.012)
            pool.cleanup_expired()

        assert gc_calls["n"] >= 1  # 25 次驱逐至少触发一次 piggyback GC

    def test_gc_never_breaks_archival(self, tmp_path):
        """ledger.gc 抛异常不破坏驱逐归档主流程"""
        from neurova.context.eviction_ledger_db import EvictionLedgerDB

        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        pool = ContextPool(user_id="u", agent_id="a", session_id="s", ttl_seconds=0.01, ledger_db=ledger)
        pool._ledger_gc_counter = 19  # 下一次驱逐即触发 GC

        def boom(**kw):
            raise RuntimeError("gc down")

        ledger.gc = boom
        pool.add_context(_chunk("内容"))
        import time
        time.sleep(0.012)
        removed = pool.cleanup_expired()  # 不抛

        assert removed == 1
        assert ledger.count() == 1  # 归档仍落库


def _chunk(content):
    return ContextInput(source=ContextSource.CONVERSATION, content=content)


class TestRollupLinkage:
    @pytest.mark.asyncio
    async def test_rollup_via_recovery_info(self, tmp_path, monkeypatch):
        """恢复路径串联：recovery.info.folded_messages → pool.rollup_overflow_digest"""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from neurova.context.orchestrator import ContextOrchestrator

        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "t"
        mock_agent.config.llm_model = "m"
        mock_agent.conversation_history = []

        async def fake_chat(messages, **kw):
            return {"content": "折叠摘要"}

        mock_agent.llm_client = SimpleNamespace(chat=fake_chat)

        import neurova.context.eviction_ledger_db as lm
        monkeypatch.setattr(
            lm, "EvictionLedgerDB",
            lambda **kw: SimpleNamespace(record=lambda **k: None, search=lambda *a, **k: [], count=lambda: 0, gc=lambda **k: 0),
        )
        monkeypatch.chdir(tmp_path)

        orch = ContextOrchestrator(mock_agent)
        msgs = [{"role": "system", "content": "s"}] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        _, info = compact_messages_for_overflow(msgs, recent_keep=6)

        await orch.context_pool.rollup_overflow_digest(info["folded_messages"])
        summaries = [c for c in orch.context_pool.get_contexts() if c.source == ContextSource.SUMMARY]
        assert len(summaries) == 1 and summaries[0].content == "折叠摘要"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
