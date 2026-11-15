# -*- coding: utf-8 -*-
"""P2（ZCode agent-loop 对照 #3/#5）：

- #3 取消流快照：中断前已流式产出的部分正文随失败轮落点进会话盘；
- #5 steering 入队侧：活跃回合注册表＋submitSteer 门（回合不在跑 = 不入队，
  调用方按新回合处理）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.failed_turn_landing import landFailedTurn
from neurova.core.steer_queue import (
    ActiveTurnRegistry,
    get_active_turn_registry,
    get_steer_queue,
    reset_active_turn_registry,
    reset_steer_queue,
    submitSteer,
)


@pytest.fixture
def cleanSteer():
    reset_steer_queue()
    reset_active_turn_registry()
    yield
    reset_steer_queue()
    reset_active_turn_registry()


class TestCancelStreamSnapshot:
    def test_cancelled_turn_lands_partial_reply(self):
        """中断轮落点带"中断前已产出的部分内容"，不再只有一句中止告示。"""
        captured = {}

        class FakePost:
            async def _step_save_session(self, user_input, reply, session_id, *args, **kwargs):
                captured["reply"] = reply

        pipeline = SimpleNamespace(post_chat_pipeline=FakePost())
        ctx = SimpleNamespace(
            post_chat_ran=False,
            save_memory=True,
            partial_reply="已分析前半部分，结论是",
            user_input="问题",
            session_id="sess-1",
            metadata=None,
            user_message_persisted=True,
            writer_claim=None,
        )
        asyncio.run(landFailedTurn(pipeline, ctx, asyncio.CancelledError()))
        assert "已分析前半部分，结论是" in captured["reply"]
        assert "本轮被中止" in captured["reply"]

    def test_cancel_without_partial_keeps_honest_notice(self):
        captured = {}

        class FakePost:
            async def _step_save_session(self, user_input, reply, session_id, *args, **kwargs):
                captured["reply"] = reply

        pipeline = SimpleNamespace(post_chat_pipeline=FakePost())
        ctx = SimpleNamespace(
            post_chat_ran=False,
            save_memory=True,
            user_input="问题",
            session_id="sess-1",
            metadata=None,
            user_message_persisted=True,
            writer_claim=None,
        )
        asyncio.run(landFailedTurn(pipeline, ctx, asyncio.CancelledError()))
        assert "本轮被中止" in captured["reply"]
        assert "部分内容" not in captured["reply"]

    def test_failure_with_partial_also_lands(self):
        """非取消失败（如上游 5xx）同样带出已产出的部分内容。"""
        captured = {}

        class FakePost:
            async def _step_save_session(self, user_input, reply, session_id, *args, **kwargs):
                captured["reply"] = reply

        pipeline = SimpleNamespace(post_chat_pipeline=FakePost())
        ctx = SimpleNamespace(
            post_chat_ran=False,
            save_memory=True,
            partial_reply="开头段落已经写完",
            user_input="问题",
            session_id="sess-1",
            metadata=None,
            user_message_persisted=True,
            writer_claim=None,
        )
        asyncio.run(landFailedTurn(pipeline, ctx, RuntimeError("upstream 5xx")))
        assert "开头段落已经写完" in captured["reply"]
        assert "未能生成回复" in captured["reply"]


class TestActiveTurnRegistry:
    def test_mark_started_and_ended(self):
        registry = ActiveTurnRegistry()
        assert registry.isActive("s1") is False
        registry.markStarted("s1")
        assert registry.isActive("s1") is True
        registry.markEnded("s1")
        assert registry.isActive("s1") is False

    def test_nested_marks_need_matching_ends(self):
        registry = ActiveTurnRegistry()
        registry.markStarted("s1")
        registry.markStarted("s1")  # 嵌套（理论上不应发生；注册表按计数兜底）
        registry.markEnded("s1")
        assert registry.isActive("s1") is True
        registry.markEnded("s1")
        assert registry.isActive("s1") is False

    def test_blank_session_ignored(self):
        registry = ActiveTurnRegistry()
        registry.markStarted("")
        assert registry.isActive("") is False


class TestSubmitSteer:
    def test_steers_only_when_turn_active(self, cleanSteer):
        get_active_turn_registry().markStarted("sess-1")
        assert submitSteer("sess-1", "补充一点") is True
        assert get_steer_queue().pending("sess-1") == 1

    def test_rejects_when_no_active_turn(self, cleanSteer):
        assert submitSteer("sess-none", "hello") is False
        assert get_steer_queue().pending("sess-none") == 0

    def test_rejects_after_turn_ends(self, cleanSteer):
        registry = get_active_turn_registry()
        registry.markStarted("sess-2")
        registry.markEnded("sess-2")
        assert submitSteer("sess-2", "hello") is False

    def test_rejects_blank(self, cleanSteer):
        get_active_turn_registry().markStarted("sess-3")
        assert submitSteer("sess-3", "  ") is False
