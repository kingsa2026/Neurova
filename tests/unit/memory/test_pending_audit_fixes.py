# -*- coding: utf-8 -*-
"""2026-09-08 审计修复：记忆待审批。

- ⑤ forget 提议判重键缺 target_memory_id/proposed_action → 同摘要不同目标
  返回同一 review_id，confirm 删错记忆；store/forget 同指纹互相顶替
- ⑩ confirm 端点先真删/真写后标记状态 → 动作必须经 remember_fn 在
  store.confirm 内执行（失败保持 pending 的设计契约）
"""

import pytest

from neurova.memory.pending_memory import PendingMemoryStore


class TestForgetProposalFingerprintIsolation:
    """forget 提议按 (action, target) 隔离判重。"""

    def test_same_summary_different_targets_get_distinct_reviews(self, tmp_path):
        store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        r1 = store.propose(
            content="用户不喜欢长回复",
            proposed_action="forget",
            target_memory_id="mem_A",
            proposed_by="u1",
        )
        r2 = store.propose(
            content="用户不喜欢长回复",
            proposed_action="forget",
            target_memory_id="mem_B",
            proposed_by="u1",
        )
        assert r1["id"] != r2["id"], "同摘要不同目标的 forget 提议撞车 → confirm 删错记忆"
        assert r2.get("target_memory_id") == "mem_B"

    def test_same_target_same_action_idempotent(self, tmp_path):
        store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        r1 = store.propose(
            content="摘要X", proposed_action="forget", target_memory_id="mem_A", proposed_by="u1"
        )
        r2 = store.propose(
            content="摘要X", proposed_action="forget", target_memory_id="mem_A", proposed_by="u1"
        )
        assert r1["id"] == r2["id"], "同目标同内容应幂等回指"

    def test_store_and_forget_same_content_not_cross_blocked(self, tmp_path):
        """store 提议 pending 中，同内容的 forget 提议不得被顶替成 store 提议。"""
        store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        r_store = store.propose(content="我住在上海", proposed_by="u1")
        r_forget = store.propose(
            content="我住在上海", proposed_action="forget", target_memory_id="mem_A", proposed_by="u1"
        )
        assert r_forget.get("proposed_action") == "forget", (
            "forget 提议被同指纹 store 提议顶替 → confirm 语义反转（删变存）"
        )


# ── ⑩ confirm 动作须在 remember_fn 内执行（失败保持 pending） ─────

class TestConfirmActionInsideRememberFn:
    """forget/写库动作在 store.confirm 的 remember_fn 内执行（锁内顺序契约）。"""

    def test_forget_failure_keeps_pending(self, tmp_path):
        store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        rec = store.propose(
            content="摘", proposed_action="forget", target_memory_id="m1", proposed_by="u"
        )

        class Boom(Exception):
            pass

        def fail_forget(content, category, memory_type):
            raise Boom("目标不存在")

        with pytest.raises(Boom):
            store.confirm(rec["id"], fail_forget)
        assert store.get(rec["id"])["status"] == "pending", "动作失败后记录必须保持 pending"

    def test_action_and_status_marking_ordered(self, tmp_path):
        """动作发生在 confirm 内部（先于状态落库），而非端点先行执行。"""
        calls: list[str] = []

        store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        original_confirm = store.confirm
        rec = store.propose(content="内容甲", proposed_by="u")

        def wrapped_confirm(pending_id, remember_fn, *a, **kw):
            calls.append("confirm-start")
            try:
                return original_confirm(pending_id, remember_fn, *a, **kw)
            finally:
                calls.append("confirm-end")

        store.confirm = wrapped_confirm  # type: ignore[method-assign]

        def remember(content, category, memory_type):
            calls.append("remember")
            return "mem_1"

        store.confirm(rec["id"], remember)
        assert calls == ["confirm-start", "remember", "confirm-end"], (
            f"动作执行顺序 {calls} 违反 confirm 锁内契约（端点先执行后标记的旧顺序）"
        )
