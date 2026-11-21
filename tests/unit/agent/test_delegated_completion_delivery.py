# -*- coding: utf-8 -*-
"""B1 子代理完成结果投递账本 单元测试。

覆盖：
- 父忙全链：pending→claimed→acknowledged；
- 同 message_id 幂等去重（返回既有单，不重复入账）；
- 父闲补投 catchUp 成功/失败两态（失败 → dispose("catchup_failed")）；
- 重复 catchUp 不二次投（已 redelivered 的单不再投）；
- dispose 留痕且 reason 必填；
- audit trail 完整（record/claim/acknowledge/dispose/catchup 全留痕）。
"""

import pytest

from neurova.agent.delegated_delivery import (
    DELIVERY_ACKNOWLEDGED,
    DELIVERY_CLAIMED,
    DELIVERY_DISPOSED,
    DELIVERY_PENDING,
    DeliveryLedger,
)


class TestFullDeliveryChain:
    def test_pending_claim_acknowledge_full_chain(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"report": "r1"}, "mid-1")
        assert ticket["status"] == DELIVERY_PENDING
        assert ticket["subagent_id"] == "swarm_child"
        assert ticket["parent_run_id"] == "swarm_parent"
        assert ticket["tag"] == "result"
        assert ledger.claim(ticket["ticket_id"]) is True
        assert ledger.get(ticket["ticket_id"])["status"] == DELIVERY_CLAIMED
        assert ledger.acknowledge(ticket["ticket_id"]) is True
        assert ledger.get(ticket["ticket_id"])["status"] == DELIVERY_ACKNOWLEDGED

    def test_pending_direct_acknowledge_allowed(self):
        # 先确认后补记的形态：pending 直达 acknowledged
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-direct")
        assert ledger.acknowledge(ticket["ticket_id"]) is True
        assert ledger.get(ticket["ticket_id"])["status"] == DELIVERY_ACKNOWLEDGED

    def test_claim_is_idempotent_and_rejects_closed(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-claim")
        assert ledger.claim(ticket["ticket_id"]) is True
        assert ledger.claim(ticket["ticket_id"]) is True, "重复 claim 幂等"
        assert ledger.get(ticket["ticket_id"])["status"] == DELIVERY_CLAIMED
        assert ledger.claim("no-such-ticket") is False, "未知单 claim 返回 False"
        assert ledger.acknowledge("no-such-ticket") is False, "未知单 acknowledge 返回 False"
        ledger.acknowledge(ticket["ticket_id"])
        assert ledger.claim(ticket["ticket_id"]) is False, "已销账的单不可再领取"
        assert ledger.acknowledge(ticket["ticket_id"]) is True, "重复确认幂等"

    def test_record_requires_subagent_and_parent(self):
        ledger = DeliveryLedger()
        with pytest.raises(ValueError):
            ledger.record("", "swarm_parent", "result", {}, "mid-x1")
        with pytest.raises(ValueError):
            ledger.record("swarm_child", "", "result", {}, "mid-x2")

    def test_record_carries_tag_and_generation(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "resume", {"r": 1}, "mid-gen", generation=3)
        assert ticket["tag"] == "resume"
        assert ticket["generation"] == 3

    def test_get_unknown_ticket_returns_none(self):
        assert DeliveryLedger().get("nope") is None


class TestMessageIdDedup:
    def test_same_message_id_returns_existing_ticket(self):
        ledger = DeliveryLedger()
        first = ledger.record("swarm_child", "swarm_parent", "result", {"n": 1}, "mid-dup")
        second = ledger.record("swarm_child", "swarm_parent", "result", {"n": 2}, "mid-dup")
        assert second["ticket_id"] == first["ticket_id"], "同 messageId 幂等返回既有单"
        assert len(ledger.snapshot()) == 1, "不重复入账"
        assert ledger.get(first["ticket_id"])["envelope"] == {"n": 1}, "保留首次内容"

    def test_different_message_id_creates_separate_tickets(self):
        ledger = DeliveryLedger()
        first = ledger.record("swarm_child", "swarm_parent", "result", {"n": 1}, "mid-a")
        second = ledger.record("swarm_child", "swarm_parent", "result", {"n": 2}, "mid-b")
        assert first["ticket_id"] != second["ticket_id"]
        assert len(ledger.snapshot()) == 2


class TestCatchUp:
    def test_catchup_success_marks_redelivered(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-c1")
        delivered = []

        def deliver_fn(t):
            delivered.append(t["ticket_id"])
            return True

        out = ledger.catchUp("swarm_parent", deliver_fn)
        assert [t["ticket_id"] for t in out] == [ticket["ticket_id"]]
        assert delivered == [ticket["ticket_id"]]
        got = ledger.get(ticket["ticket_id"])
        assert got["redelivered"] is True
        assert got["status"] == DELIVERY_PENDING, "补投成功不改状态，只标记已补投"

    def test_catchup_failure_disposes_with_reason(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-c2")
        out = ledger.catchUp("swarm_parent", lambda t: False)
        assert [t["ticket_id"] for t in out] == [ticket["ticket_id"]]
        got = ledger.get(ticket["ticket_id"])
        assert got["status"] == DELIVERY_DISPOSED
        assert got["disposed_reason"] == "catchup_failed"

    def test_catchup_exception_disposes_with_reason(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-c3")

        def boom(t):
            raise RuntimeError("下游投递通道炸了")

        ledger.catchUp("swarm_parent", boom)
        got = ledger.get(ticket["ticket_id"])
        assert got["status"] == DELIVERY_DISPOSED
        assert got["disposed_reason"] == "catchup_failed"
        actions = [a["action"] for a in got["audit"]]
        assert "catchup_failed" in actions, "补投异常留痕"

    def test_repeat_catchup_does_not_deliver_twice(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-c4")
        calls = []

        def deliver_fn(t):
            calls.append(t["ticket_id"])
            return True

        first = ledger.catchUp("swarm_parent", deliver_fn)
        second = ledger.catchUp("swarm_parent", deliver_fn)
        assert [t["ticket_id"] for t in first] == [ticket["ticket_id"]]
        assert second == [], "已补投过的单不再投"
        assert calls == [ticket["ticket_id"]], "deliver_fn 只被调用一次"

    def test_catchup_only_targets_given_parent_and_open_tickets(self):
        ledger = DeliveryLedger()
        t_open = ledger.record("c1", "parentA", "result", {}, "m-open")
        t_ack = ledger.record("c2", "parentA", "result", {}, "m-ack")
        ledger.record("c3", "parentB", "result", {}, "m-other")
        ledger.acknowledge(t_ack["ticket_id"])
        delivered = []

        def deliver_fn(t):
            delivered.append(t["ticket_id"])
            return True

        out = ledger.catchUp("parentA", deliver_fn)
        assert [t["ticket_id"] for t in out] == [t_open["ticket_id"]], "只补投目标父 run 的未销账单"
        assert delivered == [t_open["ticket_id"]]

    def test_catchup_claimed_ticket_is_included(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "m-claimed")
        ledger.claim(ticket["ticket_id"])
        out = ledger.catchUp("swarm_parent", lambda t: True)
        assert len(out) == 1, "claimed 态未销账单也在补投范围"


class TestDispose:
    def test_dispose_requires_non_empty_reason(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-d1")
        with pytest.raises(ValueError):
            ledger.dispose(ticket["ticket_id"], "")
        with pytest.raises(ValueError):
            ledger.dispose(ticket["ticket_id"], "   ")
        assert ledger.get(ticket["ticket_id"])["status"] == DELIVERY_PENDING, "拒绝处置不改状态"

    def test_dispose_marks_disposed_and_keeps_trace(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-d2")
        disposed = ledger.dispose(ticket["ticket_id"], "父 run 已终结")
        assert disposed["status"] == DELIVERY_DISPOSED
        assert disposed["disposed_reason"] == "父 run 已终结"
        got = ledger.get(ticket["ticket_id"])
        assert got["status"] == DELIVERY_DISPOSED
        assert got["audit"][-1] == {
            "action": "dispose",
            "reason": "父 run 已终结",
            "ts": got["audit"][-1]["ts"],
        }

    def test_dispose_unknown_ticket_raises_keyerror(self):
        with pytest.raises(KeyError):
            DeliveryLedger().dispose("no-such-ticket", "随便什么原因")

    def test_dispose_twice_is_idempotent(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-d3")
        first = ledger.dispose(ticket["ticket_id"], "原因甲")
        second = ledger.dispose(ticket["ticket_id"], "原因乙")
        assert second["ticket_id"] == first["ticket_id"]
        assert second["disposed_reason"] == "原因甲", "重复处置保留首次原因"


class TestAuditTrail:
    def test_full_chain_audit_is_complete_and_ordered(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-audit")
        ledger.claim(ticket["ticket_id"])
        ledger.acknowledge(ticket["ticket_id"])
        audit = ledger.get(ticket["ticket_id"])["audit"]
        actions = [a["action"] for a in audit]
        assert actions == ["record", "claim", "acknowledge"]
        assert all("ts" in a for a in audit), "每条审计都带时间戳"
        ts_list = [a["ts"] for a in audit]
        assert ts_list == sorted(ts_list), "审计按时间有序"

    def test_catchup_success_leaves_audit_trace(self):
        ledger = DeliveryLedger()
        ticket = ledger.record("swarm_child", "swarm_parent", "result", {"r": 1}, "mid-audit2")
        ledger.catchUp("swarm_parent", lambda t: True)
        actions = [a["action"] for a in ledger.get(ticket["ticket_id"])["audit"]]
        assert actions == ["record", "catchup_delivered"]


class TestQueries:
    def test_pending_for_parent_filters_open_tickets_of_that_parent(self):
        ledger = DeliveryLedger()
        t1 = ledger.record("c1", "parentA", "result", {}, "m1")
        t2 = ledger.record("c2", "parentA", "result", {}, "m2")
        t3 = ledger.record("c3", "parentB", "result", {}, "m3")
        ledger.acknowledge(t2["ticket_id"])
        pending_a = ledger.pendingForParent("parentA")
        assert [t["ticket_id"] for t in pending_a] == [t1["ticket_id"]]
        assert [t["ticket_id"] for t in ledger.pendingForParent("parentB")] == [t3["ticket_id"]]
        assert ledger.pendingForParent("parent-none") == []

    def test_snapshot_returns_all_tickets_in_creation_order(self):
        ledger = DeliveryLedger()
        t1 = ledger.record("c1", "p", "result", {}, "m1")
        t2 = ledger.record("c2", "p", "result", {}, "m2")
        assert [t["ticket_id"] for t in ledger.snapshot()] == [t1["ticket_id"], t2["ticket_id"]]
