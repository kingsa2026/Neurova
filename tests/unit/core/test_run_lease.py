"""资源治理 P2-4：run 槽租约板契约。

- acquire/renew/release 全部带属主校验（错主一律拒绝）；
- 过期租约可回收（reclaimExpired 返回 (key, owner)）；
- ttl<=0 恒 False（租约关闭语义）；
- 多线程并发 acquire 同一 key 不越权。
"""

import threading

from neurova.core.run_lease import LeaseBoard, leaseTtlSeconds


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestLeaseBoard:
    def test_acquire_then_release_by_owner(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        assert board.acquire("run1", "owner-a", 60) is True
        assert board.holds("run1", "owner-a") is True
        assert board.release("run1", "owner-a") is True
        assert board.holds("run1", "owner-a") is False

    def test_acquire_refused_while_held_by_other(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        assert board.acquire("run1", "owner-a", 60) is True
        assert board.acquire("run1", "owner-b", 60) is False

    def test_same_owner_reacquire_reenters(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        assert board.acquire("run1", "owner-a", 60) is True
        assert board.acquire("run1", "owner-a", 60) is True

    def test_release_by_wrong_owner_refused(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        board.acquire("run1", "owner-a", 60)
        assert board.release("run1", "owner-b") is False
        assert board.holds("run1", "owner-a") is True

    def test_renew_by_owner_only_and_only_before_expiry(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        board.acquire("run1", "owner-a", 60)
        clock.now = 1030
        assert board.renew("run1", "owner-a", 60) is True
        clock.now = 1200  # 已过期：续租拒绝，须重新 acquire
        assert board.renew("run1", "owner-a", 60) is False
        assert board.acquire("run1", "owner-a", 60) is True

    def test_expired_lease_reclaimed_with_owner(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        board.acquire("run1", "owner-a", 60)
        board.acquire("run2", "owner-b", 600)
        clock.now = 1100
        reclaimed = board.reclaimExpired()
        assert ("run1", "owner-a") in reclaimed
        assert ("run2", "owner-b") not in reclaimed
        assert board.holds("run1", "owner-a") is False
        assert board.holds("run2", "owner-b") is True

    def test_ttl_nonpositive_disables(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        assert board.acquire("run1", "owner-a", 0) is False
        assert board.acquire("run1", "owner-a", -1) is False

    def test_concurrent_acquire_single_winner(self):
        clock = _FakeClock()
        board = LeaseBoard(clock=clock)
        results = []
        lock = threading.Lock()

        def worker(i):
            ok = board.acquire("run1", f"owner-{i}", 60)
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(1 for x in results if x) == 1


class TestLeaseTtlFromEnv:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_RUN_LEASE_TTL_S", raising=False)
        assert leaseTtlSeconds() == 0.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RUN_LEASE_TTL_S", "60")
        assert leaseTtlSeconds() == 60.0

    def test_garbage_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RUN_LEASE_TTL_S", "abc")
        assert leaseTtlSeconds() == 0.0
