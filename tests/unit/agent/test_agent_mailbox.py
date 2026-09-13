# -*- coding: utf-8 -*-
"""P2-5 子代理完成回传 mailbox（Codex 邮箱+trigger_turn 对齐）。

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


class TestSpawnMailboxPush:
    @pytest.mark.asyncio
    async def test_spawn_result_pushed_to_mailbox(self, mailbox, monkeypatch):
        """spawn_subagent 完成结果投递父会话邮箱（嵌套模式）。"""
        from unittest.mock import MagicMock

        from neurova import tool_executor as te

        class _FakeSwarm:
            async def spawn(self, **kwargs):
                return {"success": True, "agent_id": "sub-1", "reply": "任务完成"}

        monkeypatch.setattr(
            "neurova.agent.swarm.get_swarm_manager", lambda: _FakeSwarm()
        )
        agent = MagicMock()
        agent.current_session_id = "s-parent"
        executor = te.ToolExecutor(agent)
        await executor._execute_spawn_subagent({"task": "写个总结"})

        msgs = mailbox.drain("s-parent")
        assert msgs and "sub-1" in msgs[0] and "任务完成" in msgs[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
