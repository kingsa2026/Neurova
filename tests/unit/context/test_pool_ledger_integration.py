"""
P1-1③ 池集成测试 — 台账写穿/重启召回/SUMMARY 回写

验收口径（升级计划 §4.1 期③）：
- 重启后 recall_evicted 可召回重启前被驱逐内容（FTS 检索命中）
- SUMMARY 源 chunk 进池且视图可调取
"""

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextSource
from neurova.context_pool import ContextPool


class TestLedgerWriteThrough:
    def test_eviction_persists_to_ledger(self, tmp_path):
        """TTL 驱逐 → 台账持久层有记录"""
        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        pool = ContextPool(
            user_id="u", agent_id="a", session_id="s1",
            ttl_seconds=0.05, ledger_db=ledger,  # 极短 TTL 触发驱逐
        )
        pool.add_context(_chunk("会话里讨论了上海天气"))

        import time
        time.sleep(0.08)
        removed = pool.cleanup_expired()
        assert removed == 1
        assert ledger.count() == 1

    def test_recall_evicted_reads_persistent_ledger(self, tmp_path):
        """驱逐 → 同库新实例（模拟重启）→ recall_evicted 仍可召回"""
        db_path = tmp_path / "l.db"
        ledger = EvictionLedgerDB(db_path=db_path, user_id="u", agent_id="a")
        pool = ContextPool(
            user_id="u", agent_id="a", session_id="s1",
            ttl_seconds=0.05, ledger_db=ledger,
        )
        pool.add_context(_chunk("重启前讨论了 PostgreSQL 索引优化"))
        import time
        time.sleep(0.08)
        pool.cleanup_expired()

        # 模拟重启：全新 pool 实例挂同一 ledger；内存台账为空
        pool2 = ContextPool(
            user_id="u", agent_id="a", session_id="s1",
            ledger_db=EvictionLedgerDB(db_path=db_path, user_id="u", agent_id="a"),
        )
        recalled = pool2.recall_evicted("PostgreSQL 索引")
        assert len(recalled) == 1
        assert "PostgreSQL 索引优化" in recalled[0].content
        assert recalled[0].metadata.get("recalled_from") == "ledger_db"

    def test_pool_without_ledger_unchanged(self):
        """未注入 ledger_db：行为与旧版一致（内存台账），不报错"""
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1", ttl_seconds=0.05)
        pool.add_context(_chunk("内容"))
        import time
        time.sleep(0.08)
        assert pool.cleanup_expired() == 1
        assert pool.recall_evicted() != []  # 内存台账兜底


class TestSummaryWriteBack:
    def test_archive_summary_creates_summary_chunk(self):
        pool = ContextPool(user_id="u", agent_id="a")
        pool.archive_summary("部署讨论摘要：数据库迁移待执行")
        summaries = [
            c for c in pool.get_contexts()
            if c.source == ContextSource.SUMMARY
        ]
        assert len(summaries) == 1
        assert summaries[0].content == "部署讨论摘要：数据库迁移待执行"
        assert summaries[0].priority == 90

    def test_archive_summary_empty_noop(self):
        pool = ContextPool(user_id="u", agent_id="a")
        pool.archive_summary("")
        assert pool.get_contexts() == []

    def test_summary_visible_in_draw(self):
        pool = ContextPool(user_id="u", agent_id="a", max_tokens=100)
        pool.archive_summary("摘要：用户偏好 PostgreSQL")
        view = pool.draw()
        assert any(c.source == ContextSource.SUMMARY for c in view)


def _chunk(content):
    from neurova.context.pool_models import ContextInput, ContextSource

    return ContextInput(source=ContextSource.CONVERSATION, content=content)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
