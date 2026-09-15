"""赞踩 → 使命感(purpose)真实信号回流（2026-09-15 动机真实化收尾）

/chat/feedback 已有 agent_id+feedback，接入 MotivationLedger.observe_purpose：
- like → 用户肯定贡献价值，记录高影响贡献（impact=0.9）
- dislike → 不记贡献（PurposeDrive 强度按贡献计数窗口，低 impact 也虚增；
  负反馈的真实效果已由记忆温度 -15 链路承担）
- 取消（None）/未装配 ledger → 不报错、不造假
"""

import asyncio
import types

import pytest
from fastapi import Request

import neurova.api.endpoints.console as console_module


def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/console/chat/feedback",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope, receive)


class FakeRepo:
    def find_session(self, session_id):
        return {"agent_id": "a1", "session_id": session_id, "user_id": "u1"}

    def update_message_metadata(self, **kw):
        return True

    def get_round(self, **kw):
        return {"user": {"content": "Q1"}, "assistant": {"content": "A1"}}


class RecordingLedger:
    def __init__(self):
        self.purpose_events = []

    def observe_purpose(self, contribution, impact=0.5):
        self.purpose_events.append((contribution, impact))


def _wire(monkeypatch, ledger):
    agent = types.SimpleNamespace(intrinsic_motivation=ledger, memory_agent=None)
    monkeypatch.setattr(console_module, "_get_user_id", lambda *a: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: FakeRepo())
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": agent)
    return ledger


def _post(feedback):
    body = console_module.FeedbackRequest(session_id="s1", timestamp="2026-09-15T10:00:00", feedback=feedback)
    return asyncio.run(console_module.post_chat_feedback(body, _make_request()))


def test_like_flows_to_purpose_drive(monkeypatch):
    ledger = _wire(monkeypatch, RecordingLedger())
    resp = _post("like")
    assert resp["code"] == 0
    assert len(ledger.purpose_events) == 1
    contribution, impact = ledger.purpose_events[0]
    assert "点赞" in contribution
    assert impact == pytest.approx(0.9)


def test_dislike_does_not_inflate_purpose(monkeypatch):
    """点踩不得记贡献（强度按计数窗口，低 impact 同样虚增）"""
    ledger = _wire(monkeypatch, RecordingLedger())
    _post("dislike")
    assert ledger.purpose_events == []


def test_cancel_feedback_no_purpose_event(monkeypatch):
    ledger = _wire(monkeypatch, RecordingLedger())
    _post(None)
    assert ledger.purpose_events == []


def test_no_ledger_honest_noop(monkeypatch):
    """未装配/无动机系统的 agent：反馈主链路照常成功，不崩不造假"""
    _wire(monkeypatch, None)
    resp = _post("like")
    assert resp["code"] == 0


def test_agent_absent_no_crash(monkeypatch):
    monkeypatch.setattr(console_module, "_get_user_id", lambda *a: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: FakeRepo())
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": None)
    resp = _post("like")
    assert resp["code"] == 0
