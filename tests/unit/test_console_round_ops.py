"""红绿灯 TDD：console 轮次操作端点（编辑覆写/删除一轮 + 点赞点踩反馈）。

DELETE /console/chat/rounds  — 删除一轮（session 文件 + 记忆 + 存活 agent 内存历史）
POST /console/chat/feedback  — 点赞/点踩持久化到 assistant 消息 metadata

删除轮次的根因修复点（均在用例中固化）：
1. 记忆清除：session 删了但记忆还在 → agent 仍"记得"已删除的对话
2. 内存历史同步：_restore_session_history 只在"文件比内存长"时覆盖，
   删除后内存历史不会收缩 → 已删轮在下一轮 LLM 调用中复活
"""
from __future__ import annotations

import asyncio
import json
from starlette.requests import Request

from neurova.api.endpoints import console as console_module


def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "DELETE",
        "path": "/chat/rounds",
        "headers": [],
    }
    return Request(scope, receive=receive)


SESSION = {"session_id": "s1", "agent_id": "a1", "user_id": "u1", "title": "T"}
DELETED_ROUND = [
    {"role": "user", "content": "Q1", "timestamp": "2026-08-29T10:00:00"},
    {"role": "assistant", "content": "A1", "timestamp": "2026-08-29T10:00:00"},
]
REMAINING_HISTORY = [
    {"role": "user", "content": "Q2", "timestamp": "2026-08-29T11:00:00"},
    {"role": "assistant", "content": "A2", "timestamp": "2026-08-29T11:00:00"},
]


class FakeRepo:
    def __init__(self, sessions=None, deleted=None, history=None, metadata_ok=True):
        self.sessions = sessions if sessions is not None else [SESSION]
        self.deleted_result = deleted if deleted is not None else DELETED_ROUND
        self.history = history if history is not None else REMAINING_HISTORY
        self.metadata_ok = metadata_ok
        self.delete_round_calls = []
        self.metadata_calls = []
        # 反馈闭环 / stats 支持
        self.round_data = None
        self.agent_sessions = None
        self.histories_by_session = {}

    def list_sessions(self, agent_id="", user_id=""):
        if self.agent_sessions is not None:
            return self.agent_sessions
        return self.sessions

    def delete_round(self, agent_id, session_id, timestamp):
        self.delete_round_calls.append(
            {"agent_id": agent_id, "session_id": session_id, "timestamp": timestamp}
        )
        return self.deleted_result

    def get_history(self, agent_id, session_id, max_messages=0):
        if session_id in self.histories_by_session:
            return self.histories_by_session[session_id]
        return self.history

    def get_round(self, agent_id, session_id, timestamp):
        return self.round_data

    def update_message_metadata(self, agent_id, session_id, timestamp, metadata_patch, role=None):
        self.metadata_calls.append(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "timestamp": timestamp,
                "metadata_patch": metadata_patch,
                "role": role,
            }
        )
        return self.metadata_ok


class FakeMemCore:
    def __init__(self):
        self.calls = []
        self.feedback_calls = []

    def delete_round_memories(self, session_id, user_input, agent_response, approx_ts=None):
        self.calls.append(
            {
                "session_id": session_id,
                "user_input": user_input,
                "agent_response": agent_response,
                "approx_ts": approx_ts,
            }
        )
        return 2

    def apply_feedback_to_memories(self, session_id, user_input, agent_response, feedback, approx_ts=None):
        self.feedback_calls.append(
            {
                "session_id": session_id,
                "user_input": user_input,
                "agent_response": agent_response,
                "feedback": feedback,
                "approx_ts": approx_ts,
            }
        )
        return 2


class FakeContext:
    """duck typing ConversationContext（clear/extend）。"""

    def __init__(self):
        self.items = [{"role": "user", "content": "stale-1"},
                      {"role": "assistant", "content": "stale-2"},
                      {"role": "user", "content": "stale-3"},
                      {"role": "assistant", "content": "stale-4"}]

    def clear(self):
        self.items = []

    def extend(self, msgs):
        self.items.extend(msgs)


class FakeAgent:
    def __init__(self):
        self.memory_agent = FakeMemCore()
        self.conversation_history = list(FakeContext().items)
        self._conversation_context = FakeContext()


def test_delete_round_happy_path_purges_memory_and_syncs_history(monkeypatch):
    repo = FakeRepo()
    agent = FakeAgent()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": agent)

    resp = asyncio.run(
        console_module.delete_chat_round(
            session_id="s1", timestamp="2026-08-29T10:00:00", request=_make_request()
        )
    )

    assert resp["code"] == 0
    assert resp["data"]["deleted"] == 2
    # session 文件层定位参数正确
    assert repo.delete_round_calls == [
        {"agent_id": "a1", "session_id": "s1", "timestamp": "2026-08-29T10:00:00"}
    ]
    # 记忆清除：带上被删轮内容 + 轮次时间戳
    assert agent.memory_agent.calls == [
        {
            "session_id": "s1",
            "user_input": "Q1",
            "agent_response": "A1",
            "approx_ts": "2026-08-29T10:00:00",
        }
    ]
    # 内存历史同步：收缩为文件剩余历史（修复"只增长不收缩"复活问题）
    # 内存历史格式与 ChatPipeline._restore_session_history 一致：仅 role/content
    assert agent.conversation_history == [
        {"role": m["role"], "content": m["content"]} for m in REMAINING_HISTORY
    ]
    assert agent._conversation_context.items == agent.conversation_history


def test_delete_round_404_when_session_missing(monkeypatch):
    repo = FakeRepo(sessions=[])
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)

    from fastapi import HTTPException

    try:
        asyncio.run(
            console_module.delete_chat_round(
                session_id="ghost", timestamp="t0", request=_make_request()
            )
        )
        raised = False
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


def test_delete_round_403_on_user_mismatch(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u-other")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)

    from fastapi import HTTPException

    try:
        asyncio.run(
            console_module.delete_chat_round(
                session_id="s1", timestamp="t0", request=_make_request()
            )
        )
        raised = False
    except HTTPException as e:
        raised = e.status_code == 403
    assert raised


def test_delete_round_404_when_round_not_found(monkeypatch):
    repo = FakeRepo(deleted=[])
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": None)

    from fastapi import HTTPException

    try:
        asyncio.run(
            console_module.delete_chat_round(
                session_id="s1", timestamp="no-such", request=_make_request()
            )
        )
        raised = False
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


def test_delete_round_works_without_live_agent(monkeypatch):
    """后端重启后 agent 不可用：session 删除照常，记忆/历史同步跳过。"""
    repo = FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": None)

    resp = asyncio.run(
        console_module.delete_chat_round(
            session_id="s1", timestamp="t0", request=_make_request()
        )
    )
    assert resp["code"] == 0


def test_feedback_persists_to_assistant_metadata(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)

    body = console_module.FeedbackRequest(
        session_id="s1", timestamp="2026-08-29T10:00:00", feedback="like"
    )
    resp = asyncio.run(console_module.post_chat_feedback(body, _make_request()))

    assert resp["code"] == 0
    assert repo.metadata_calls == [
        {
            "agent_id": "a1",
            "session_id": "s1",
            "timestamp": "2026-08-29T10:00:00",
            "metadata_patch": {"feedback": "like"},
            "role": "assistant",
        }
    ]


def test_feedback_rejects_unknown_value():
    import pydantic

    try:
        console_module.FeedbackRequest(session_id="s1", timestamp="t0", feedback="meh")
        raised = False
    except pydantic.ValidationError:
        raised = True
    assert raised


def test_feedback_404_when_message_missing(monkeypatch):
    repo = FakeRepo(metadata_ok=False)
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)

    from fastapi import HTTPException

    body = console_module.FeedbackRequest(session_id="s1", timestamp="no-such", feedback="dislike")
    try:
        asyncio.run(console_module.post_chat_feedback(body, _make_request()))
        raised = False
    except HTTPException as e:
        raised = e.status_code == 404
    assert raised


def test_chat_request_accepts_client_timestamp():
    """client_timestamp 随 chat 请求进入 metadata，供轮次操作双路定位。"""
    body = console_module.ChatRequest(
        message="hi", session_id="s1", client_timestamp="2026-08-29T10:00:00.123+08:00"
    )
    assert body.client_timestamp == "2026-08-29T10:00:00.123+08:00"


# ── 反馈质量闭环：feedback 端点接入记忆温度 + stats 统计端点 ──────────────


def test_feedback_applies_memory_temperature(monkeypatch):
    """点赞/点踩后调用 memory_agent.apply_feedback_to_memories（best-effort）。"""
    repo = FakeRepo()
    repo.round_data = {
        "user": {"role": "user", "content": "Q1"},
        "assistant": {"role": "assistant", "content": "A1"},
    }
    agent = FakeAgent()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": agent)

    body = console_module.FeedbackRequest(
        session_id="s1", timestamp="2026-08-29T10:00:00", feedback="like"
    )
    resp = asyncio.run(console_module.post_chat_feedback(body, _make_request()))

    assert resp["code"] == 0
    assert agent.memory_agent.feedback_calls == [
        {
            "session_id": "s1",
            "user_input": "Q1",
            "agent_response": "A1",
            "feedback": "like",
            "approx_ts": "2026-08-29T10:00:00",
        }
    ]


def test_feedback_cancel_does_not_touch_memory(monkeypatch):
    """取消反馈（feedback=None）只清 metadata，不做温度操作。"""
    repo = FakeRepo()
    repo.round_data = {
        "user": {"role": "user", "content": "Q1"},
        "assistant": {"role": "assistant", "content": "A1"},
    }
    agent = FakeAgent()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id="default": agent)

    body = console_module.FeedbackRequest(session_id="s1", timestamp="t0", feedback=None)
    resp = asyncio.run(console_module.post_chat_feedback(body, _make_request()))

    assert resp["code"] == 0
    assert agent.memory_agent.feedback_calls == []


def test_feedback_stats_aggregates_across_sessions(monkeypatch):
    """stats 端点按 agent 聚合 like/dislike 计数 + 最近反馈明细。"""
    repo = FakeRepo()
    repo.agent_sessions = [
        {"session_id": "s1", "agent_id": "a1", "user_id": "u1"},
        {"session_id": "s2", "agent_id": "a1", "user_id": "u1"},
    ]
    repo.histories_by_session = {
        "s1": [
            {"role": "user", "content": "Q1", "timestamp": "2026-08-29T10:00:00"},
            {"role": "assistant", "content": "A1", "timestamp": "2026-08-29T10:00:00",
             "metadata": {"feedback": "like"}},
        ],
        "s2": [
            {"role": "assistant", "content": "A2", "timestamp": "2026-08-29T11:00:00",
             "metadata": {"feedback": "dislike"}},
            {"role": "assistant", "content": "A3", "timestamp": "2026-08-29T12:00:00",
             "metadata": {"feedback": "like"}},
        ],
    }
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)

    resp = asyncio.run(console_module.get_feedback_stats(agent_id="a1", limit=50, request=_make_request()))

    assert resp["code"] == 0
    data = resp["data"]
    assert data["like"] == 2
    assert data["dislike"] == 1
    assert data["total_feedback"] == 3
    # 最近反馈按时间倒序（12:00 like → 11:00 dislike → 10:00 like）
    assert [r["feedback"] for r in data["recent"]] == ["like", "dislike", "like"]
    assert data["recent"][0]["session_id"] == "s2"


def test_feedback_stats_empty_agent_returns_zeros(monkeypatch):
    repo = FakeRepo()
    repo.agent_sessions = []
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)

    resp = asyncio.run(console_module.get_feedback_stats(agent_id="a1", limit=50, request=_make_request()))

    data = resp["data"]
    assert data["like"] == 0 and data["dislike"] == 0 and data["total_feedback"] == 0
    assert data["recent"] == []
