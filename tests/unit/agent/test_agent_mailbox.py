# -*- coding: utf-8 -*-
"""P2-5 子代理完成回传 mailbox。

- 会话级 mailbox：子代理完成结果投递父会话邮箱；agent loop 工具轮间隙
  排空注入（嵌套等待模式是增强可见性，后台模式是唯一回传通道）
- 与 steer 队列同构（TTL/上限/会话隔离）
"""
import pytest


@pytest.fixture()
def mailbox(monkeypatch):
    from neurova.agent.mailbox import AgentMailbox
    from neurova.agent import mailbox as mb

    box = AgentMailbox()
    monkeypatch.setattr(mb, "_MAILBOX", box)
    yield box
    monkeypatch.setattr(mb, "_MAILBOX", None)


class TestAgentMailbox:
    def test_push_drain(self, mailbox):
        assert mailbox.push("s1", "子代理A 完成：已生成报告") is True
        assert mailbox.drain("s1") == ["子代理A 完成：已生成报告"]
        assert mailbox.drain("s1") == []

    def test_session_isolation_and_empty(self, mailbox):
        mailbox.push("s1", "a")
        mailbox.push("s2", "b")
        assert mailbox.drain("s1") == ["a"]
        assert mailbox.drain("") == []
        assert mailbox.drain("nope") == []

    def test_ttl_expiry(self, mailbox):
        mailbox.ttl_seconds = 0.01
        import time

        mailbox.push("s1", "old")
        time.sleep(0.05)
        assert mailbox.drain("s1") == []

    def test_max_cap(self, mailbox):
        mailbox.max_per_session = 2
        mailbox.push("s1", "a")
        mailbox.push("s1", "b")
        assert mailbox.push("s1", "c") is False


# ⚠ 原 `TestSpawnMailboxPush` 已删除：它用 FakeSwarm 返回自造的 {"reply": ...}，
# 而真 `spawn()` 的信封里报告键名是 report——替身与读侧代码一起错向同一个不存在的键，
# 两边自洽便恒绿，把「邮箱正文恒为空壳」这个缺陷一路掩盖。回灌行为改由
# test_subagentCompletionReachesMailboxWithReportBody.py 以真 SwarmManager 跨边界判定。


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
