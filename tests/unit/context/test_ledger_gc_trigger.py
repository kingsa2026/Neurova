"""
增强② — ledger GC 定期触发测试

方案：EvictionLedgerDB.gc_stale(参数默认) + pool.cleanup_expired 联动节流
（每 N 次驱逐归档触发一次 GC，复用 P1-1 台账写穿点，不新增定时器基础设施）。
"""

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


def _chunk(content):
    return ContextInput(source=ContextSource.CONVERSATION, content=content)


class TestGcStale:
    def test_gc_stale_defaults_no_error(self, tmp_path):
        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        for i in range(5):
            ledger.record(content=f"chunk {i}", session_id="s1")
        removed = ledger.gc_stale()
        assert isinstance(removed, int)

    def test_gc_stale_respects_retention(self, tmp_path):
        ledger = EvictionLedgerDB(
            db_path=tmp_path / "l.db", user_id="u", agent_id="a",
            keep_count=3, keep_days=30,
        )
        for i in range(10):
            ledger.record(content=f"chunk {i}", session_id="s1")
        ledger.gc_stale()
        assert ledger.count() == 3


class TestPoolGcThrottle:
    def test_cleanup_triggers_throttled_gc(self, tmp_path, monkeypatch):
        import neurova.context_pool as cp_module

        gc_calls = []

        class _TrackingLedger(EvictionLedgerDB):
            def gc_stale(self):
                gc_calls.append(1)
                return 0

        ledger = _TrackingLedger(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        pool = ContextPool(
            user_id="u", agent_id="a", session_id="s1",
            ttl_seconds=0.05, ledger_db=ledger,
        )
        monkeypatch.setattr(cp_module, "_LEDGER_GC_EVERY", 2)  # 每 2 次驱逐 GC 一次

        for i in range(4):
            pool.add_context(_chunk(f"c{i}"))
            import time
            time.sleep(0.06)
            pool.cleanup_expired()

        assert len(gc_calls) >= 2  # 4 次驱逐触发 ≥2 次 GC（节流生效）

    def test_gc_error_never_breaks_archival(self, tmp_path, monkeypatch):
        """GC 异常不影响驱逐归档主流程"""
        import neurova.context_pool as cp_module

        class _BoomLedger(EvictionLedgerDB):
            def gc_stale(self):
                raise RuntimeError("gc down")

        ledger = _BoomLedger(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        pool = ContextPool(
            user_id="u", agent_id="a", session_id="s1",
            ttl_seconds=0.05, ledger_db=ledger,
        )
        monkeypatch.setattr(cp_module, "_LEDGER_GC_EVERY", 1)

        pool.add_context(_chunk("内容"))
        import time
        time.sleep(0.06)
        assert pool.cleanup_expired() == 1  # 归档照常
        assert pool.recall_evicted() != []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
