# -*- coding: utf-8 -*-
"""P2-2 记忆提炼租约认领（PendingMemoryStore.claim/release）。"""
import pytest


@pytest.fixture()
def store(tmp_path):
    from neurova.memory.pending_memory import PendingMemoryStore

    s = PendingMemoryStore(str(tmp_path / "pending.db"))
    yield s
    s.close()


class TestLeaseClaim:
    def test_claim_and_release(self, store):
        first = store.claim("用户偏好深色主题", holder="worker-1")
        assert first["claimed"] is True
        # 租约期内重复认领被拒
        second = store.claim("用户偏好深色主题", holder="worker-2")
        assert second["claimed"] is False
        assert second["reason"] == "lease_held"
        # 释放后可重新认领
        assert store.release_lease(first["lease_id"]) is True
        again = store.claim("用户偏好深色主题", holder="worker-2")
        assert again["claimed"] is True

    def test_pending_exists_blocks_claim(self, store):
        store.propose("重要事实：项目用 Python", proposed_by="u1")
        result = store.claim("重要事实：项目用 Python", holder="w1")
        assert result["claimed"] is False
        assert result["reason"] == "pending_exists"

    def test_expired_lease_reclaimed(self, store):
        first = store.claim("过期内容", holder="w1", lease_seconds=0.01)
        import time

        time.sleep(0.05)
        again = store.claim("过期内容", holder="w2")
        assert again["claimed"] is True
        assert again["lease_id"] != first["lease_id"]

    def test_lease_does_not_create_pending(self, store):
        store.claim("仅认领不落待审", holder="w1")
        assert store.list_pending() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
