# -*- coding: utf-8 -*-
"""死信重试耗尽后必须退出重放面（审计 3.2-6，2026-11-17）：

`_is_processed` 原实现恒 `return False`——重试次数达上限的死信永远留在
get_retryable()/get_pending() 重放面里，重放循环会反复投递（acp_runtime
复用本队列，属活伤）。锁定契约：
1. 重试耗尽（retry_count >= max_retries）→ 不再出现在 get_retryable；
2. 重试耗尽 → retry() 拒绝返回消息（既有守卫，与判定同源不漂移）；
3. mark_processed 后 → 不在 get_pending（队列移出判定）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from neurova.agent.protocols.dead_letter_queue import DLQConfig, DeadLetterQueue
from neurova.agent.protocols.message_protocol import AgentMessage, DeadLetterReason


@pytest.fixture
def dlq(tmp_path) -> DeadLetterQueue:
    return DeadLetterQueue(
        DLQConfig(max_retries=2, storage_path=str(tmp_path / "dlq"), enable_auto_retry=False)
    )


def _msg(msg_id: str = "m-replay-1") -> AgentMessage:
    return AgentMessage(
        sender_id="a",
        receiver_id="b",
        action="test",
        data={"k": "v"},
        message_id=msg_id,
    )


class _Clock:
    """可控时钟：替身 dead_letter_queue 模块的 time，按需推进。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now


class TestRetryExhaustionLeavesReplaySurface:
    def test_exhausted_message_not_in_retryable(self, dlq, monkeypatch):
        """重试耗尽后，退避窗口再到期也不得重回重放面（重复投递根伤）。"""
        clock = _Clock()
        monkeypatch.setattr("neurova.agent.protocols.dead_letter_queue.time", clock)

        dlq.add(_msg(), DeadLetterReason.SYSTEM_ERROR, "boom")
        clock.now += 10
        assert len(dlq.get_retryable()) == 1, "窗口到期后应可重试"
        dlq.retry("m-replay-1")  # 1/2
        clock.now += 10
        assert len(dlq.get_retryable()) == 1, "预算内仍可重试"
        dlq.retry("m-replay-1")  # 2/2 → 耗尽
        clock.now += 10  # 耗尽后的窗口到期

        assert dlq.get_retryable() == [], "重试耗尽的死信必须退出重放面（原恒 False：永远留在面里反复重放）"

    def test_exhausted_message_not_in_pending(self, dlq):
        dlq.add(_msg(), DeadLetterReason.SYSTEM_ERROR, "boom")
        dlq.retry("m-replay-1")
        dlq.retry("m-replay-1")

        assert dlq.get_pending() == [], "重试耗尽的死信不再属于自动待处理面"

    def test_retry_refuses_after_exhaustion(self, dlq):
        dlq.add(_msg(), DeadLetterReason.SYSTEM_ERROR, "boom")
        dlq.retry("m-replay-1")
        dlq.retry("m-replay-1")
        assert dlq.retry("m-replay-1") is None, "耗尽后 retry() 必须拒绝（既有守卫保持）"

    def test_mark_processed_removes_from_pending(self, dlq):
        dlq.add(_msg(), DeadLetterReason.SYSTEM_ERROR, "boom")
        dlq.mark_processed("m-replay-1")
        assert dlq.get_pending() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
