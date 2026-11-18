# -*- coding: utf-8 -*-
"""H-1 邮箱两阶段确认单元测试（对照评测改进项）。

语义（对齐参照系 "Queuing is not acknowledgement"）：
- lease：把待投递消息以 {id, message} 形式交给消费方，并标记 leased——
  同会话再次 lease 仍能取到未 ack 的消息（至少一次投递，防"排空后落盘前
  崩溃丢信"）；
- acknowledge：只有真正进入持久上下文的消息才被消费删除；未 ack 的保持
  可再投；
- TTL 只清 ready 态过期件，leased 态不受 TTL 影响（在途处理不被中途丢弃）；
- drain() 移除：生产消费方必须走两阶段，不再提供破坏性一次性排空。
"""

import time

import pytest

from neurova.agent.mailbox import AgentMailbox


@pytest.fixture()
def mailbox(monkeypatch):
    from neurova.agent import mailbox as mb

    box = AgentMailbox()
    monkeypatch.setattr(mb, "_MAILBOX", box)
    yield box
    monkeypatch.setattr(mb, "_MAILBOX", None)


class TestLeaseAck:
    def test_lease_returns_messages_with_ids(self, mailbox):
        assert mailbox.push("s1", "子代理A 终态") is True
        leased = mailbox.lease("s1")
        assert [m["message"] for m in leased] == ["子代理A 终态"]
        assert all(m["id"] for m in leased)

    def test_unacked_message_is_redelivered_on_next_lease(self, mailbox):
        mailbox.push("s1", "第一条")
        mailbox.push("s1", "第二条")
        first = mailbox.lease("s1")
        assert len(first) == 2
        # 消费方还没 ack 就再次 lease（比如上一轮落盘失败）——消息不得消失
        again = mailbox.lease("s1")
        assert [m["id"] for m in again] == [m["id"] for m in first]

    def test_acknowledge_removes_only_acked(self, mailbox):
        mailbox.push("s1", "甲")
        mailbox.push("s1", "乙")
        leased = mailbox.lease("s1")
        mailbox.acknowledge("s1", [leased[0]["id"]])
        remaining = mailbox.lease("s1")
        assert [m["message"] for m in remaining] == ["乙"]

    def test_acknowledge_idempotent_and_tolerates_unknown_ids(self, mailbox):
        mailbox.push("s1", "甲")
        leased = mailbox.lease("s1")
        assert mailbox.acknowledge("s1", [leased[0]["id"]]) == 1
        assert mailbox.acknowledge("s1", [leased[0]["id"], "nope"]) == 0
        assert mailbox.pending("s1") == 0

    def test_pending_counts_leased_and_ready(self, mailbox):
        mailbox.push("s1", "甲")
        mailbox.lease("s1")
        mailbox.push("s1", "乙")
        assert mailbox.pending("s1") == 2

    def test_leased_messages_exempt_from_ttl(self, mailbox):
        mailbox.ttl_seconds = 0.01
        mailbox.push("s1", "在途件")
        leased = mailbox.lease("s1")
        time.sleep(0.05)
        # 新 push 触发 TTL 清扫，但不得动 leased 态的在途件
        mailbox.push("s1", "新件")
        msgs = [m["message"] for m in mailbox.lease("s1")]
        assert "在途件" in msgs, "leased 态消息不得被 TTL 清掉（排空后落盘前丢失=丢终态）"
        assert "新件" in msgs

    def test_ready_messages_still_expire(self, mailbox):
        mailbox.ttl_seconds = 0.01
        mailbox.push("s1", "旧件")
        time.sleep(0.05)
        mailbox.push("s1", "新件")
        msgs = [m["message"] for m in mailbox.lease("s1")]
        assert msgs == ["新件"]

    def test_session_isolation(self, mailbox):
        mailbox.push("s1", "a")
        mailbox.push("s2", "b")
        assert [m["message"] for m in mailbox.lease("s1")] == ["a"]
        assert [m["message"] for m in mailbox.lease("s2")] == ["b"]
        assert mailbox.lease("") == []

    def test_drain_removed(self):
        assert not hasattr(AgentMailbox, "drain"), \
            "破坏性一次性排空与两阶段确认并存=第二套投递语义（教义第 6 条）"


class TestReliabilitySemantics:
    """S2 邮箱可靠性语义补全（对照 C1/C3）。

    - 幂等：同 messageId 重复投递只生效一次；重复 ack 不重复计数；
    - 优先级：lease 按优先级降序（urgent > high > normal）、同级按时间升序；
    - 死主回收：leased 超 TTL 未 ack 回收回 ready（回收计数进 stats），
      回收后可再 lease 且 messageId 不变——宁重不丢，不升级成重复生效。
    """

    def test_duplicateMessageIdDeliveredOnce(self, mailbox):
        """重复 messageId 投递只生效一次；ack 重复调用不重复扣减计数。"""
        assert mailbox.push("s1", "第一遍", message_id="msg-dup") is True
        # 同 id 重复投递：幂等接受（消息已在箱，不重复入库）
        assert mailbox.push("s1", "第二遍", message_id="msg-dup") is True
        assert mailbox.pending("s1") == 1
        leased = mailbox.lease("s1")
        assert len(leased) == 1
        assert leased[0]["message"] == "第一遍"
        assert leased[0]["messageId"] == "msg-dup"
        # 落盘后 ack；对已 ack 的 id 重复调用必须幂等
        assert mailbox.acknowledge("s1", [leased[0]["id"]]) == 1
        assert mailbox.acknowledge("s1", [leased[0]["id"]]) == 0
        snapshot = mailbox.stats("s1")
        assert snapshot["ackedTotal"] == 1, "重复 ack 不得重复计数"
        assert snapshot["dedupedTotal"] == 1, "重复投递应被去重一次"

    def test_higherPriorityLeasedFirst(self, mailbox):
        """lease 按优先级降序返回；同优先级按投递时间升序（FIFO）。"""
        mailbox.push("s1", "普通件", priority="normal")
        mailbox.push("s1", "紧急件", priority="urgent")
        mailbox.push("s1", "普通件二")  # 缺省 normal
        mailbox.push("s1", "高优件", priority="high")
        leased = mailbox.lease("s1")
        assert [m["message"] for m in leased] == ["紧急件", "高优件", "普通件", "普通件二"]
        assert [m["priority"] for m in leased] == ["urgent", "high", "normal", "normal"]
        assert mailbox.stats("s1")["priorityDistribution"] == {
            "normal": 2, "high": 1, "urgent": 1,
        }

    def test_leasedTimeoutReclaimedThenReleasable(self, mailbox):
        """leased 超 TTL 未 ack 被回收回 ready；回收后可再 lease 且 messageId 不变。"""
        mailbox.ttl_seconds = 0.01
        mailbox.push("s1", "在途件", message_id="msg-dead")
        assert len(mailbox.lease("s1")) == 1
        time.sleep(0.05)
        snapshot = mailbox.stats("s1")  # 快照前先做死主回收清扫
        assert snapshot["reclaimedTotal"] == 1, "超时未 ack 的 leased 件应被回收"
        assert snapshot["leasedTotal"] == 0, "回收后在途租约应清零"
        again = mailbox.lease("s1")
        assert [m["message"] for m in again] == ["在途件"], \
            "回收回 ready 后可再 lease（宁重不丢）"
        assert again[0]["messageId"] == "msg-dead", \
            "重投件 messageId 不变（消费方据此判重，不重复生效）"
        assert mailbox.stats("s1")["reclaimedTotal"] == 1, "再次 lease 不算新回收"
