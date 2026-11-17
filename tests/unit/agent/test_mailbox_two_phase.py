# -*- coding: utf-8 -*-
"""H-1 邮箱两阶段确认单元测试（CoworkOS 对照评测改进项）。

语义（对齐 CoworkOS "Queuing is not acknowledgement"）：
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
