"""会话分叉（fork）+ 钩子/检查点（checkpoint）— 后端契约测试（红绿灯 TDD）

对齐 ZCode 消息操作条（fork/checkpoint 图标）：
1. POST /console/chat/sessions/{id}/fork：按 until_timestamp 双路定位截取
   历史（含该条）到新会话，返回新 session_id；新会话消息数与截取数一致；
   未知 timestamp → 400；越权/不存在 → 404。
2. POST /console/chat/checkpoint：设置/移除消息钩子（metadata.checkpoint），
   复用 feedback 的双路定位；成功返回 ok。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import console as console_module


class FakeRepo:
    """最小 repo 桩：内存消息列表 + create/save/get/update_metadata。"""

    def __init__(self, messages=None, owner_user_id="u1"):
        self.messages = list(messages or [])
        self.owner_user_id = owner_user_id
        self.saved: list = []
        self.created: list = []
        self.metadata_patches: list = []

    def _session(self):
        return {"session_id": "s1", "agent_id": "default", "user_id": self.owner_user_id, "title": "原会话"}

    def list_sessions(self, agent_id="", user_id=""):
        s = self._session()
        if user_id and s["user_id"] and s["user_id"] != user_id:
            return []
        return [s]

    def get_history(self, agent_id="", session_id="", max_messages=0):
        return list(self.messages)

    def create_session(self, agent_id="", user_id="", title="新对话"):
        self.created.append({"agent_id": agent_id, "user_id": user_id, "title": title})
        return f"fork-{len(self.created)}"

    def save_message(self, agent_id="", session_id="", role="", content="", metadata=None):
        self.saved.append({"session_id": session_id, "role": role, "content": content, "metadata": metadata})
        return True

    def update_message_metadata(self, agent_id="", session_id="", timestamp="", metadata_patch=None, role=None):
        self.metadata_patches.append({"timestamp": timestamp, "patch": metadata_patch, "role": role})
        return True


def _messages():
    return [
        {"role": "user", "content": "q1", "timestamp": "2026-09-06T10:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-09-06T10:00:05"},
        {"role": "user", "content": "q2", "timestamp": "2026-09-06T10:01:00"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-09-06T10:01:05"},
    ]


def _client(monkeypatch, repo):
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    app = FastAPI()
    app.include_router(console_module.router, prefix="/api/v1/console")
    return TestClient(app)


class TestForkEndpoint:
    def test_fork_copies_history_up_to_timestamp(self, monkeypatch):
        repo = FakeRepo(messages=_messages())
        client = _client(monkeypatch, repo)
        resp = client.post(
            "/api/v1/console/chat/sessions/s1/fork",
            json={"until_timestamp": "2026-09-06T10:00:05"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["new_session_id"] == "fork-1"
        # 截取到 10:00:05（含）= 前 2 条
        assert len(repo.saved) == 2
        assert [m["content"] for m in repo.saved] == ["q1", "a1"]
        assert repo.created[0]["user_id"] == "u1"

    def test_fork_unknown_timestamp_is_400(self, monkeypatch):
        repo = FakeRepo(messages=_messages())
        client = _client(monkeypatch, repo)
        resp = client.post(
            "/api/v1/console/chat/sessions/s1/fork",
            json={"until_timestamp": "2099-01-01T00:00:00"},
        )
        assert resp.status_code == 400

    def test_fork_missing_session_is_404(self, monkeypatch):
        repo = FakeRepo()  # list_sessions 返回空 → s1 不存在
        monkeypatch.setattr(repo, "list_sessions", lambda agent_id="", user_id="": [])
        client = _client(monkeypatch, repo)
        resp = client.post(
            "/api/v1/console/chat/sessions/s1/fork",
            json={"until_timestamp": "2026-09-06T10:00:05"},
        )
        assert resp.status_code == 404


class TestCheckpointEndpoint:
    def test_set_and_unset_checkpoint(self, monkeypatch):
        repo = FakeRepo(messages=_messages())
        client = _client(monkeypatch, repo)

        resp = client.post(
            "/api/v1/console/chat/checkpoint",
            json={"session_id": "s1", "timestamp": "2026-09-06T10:00:05", "active": True},
        )
        assert resp.status_code == 200
        assert repo.metadata_patches[-1]["patch"] == {"checkpoint": True}

        resp = client.post(
            "/api/v1/console/chat/checkpoint",
            json={"session_id": "s1", "timestamp": "2026-09-06T10:00:05", "active": False},
        )
        assert resp.status_code == 200
        assert repo.metadata_patches[-1]["patch"] == {"checkpoint": False}

    def test_checkpoint_unknown_message_is_404(self, monkeypatch):
        class _FailRepo(FakeRepo):
            def update_message_metadata(self, **kwargs):
                return False

        repo = _FailRepo(messages=_messages())
        client = _client(monkeypatch, repo)
        resp = client.post(
            "/api/v1/console/chat/checkpoint",
            json={"session_id": "s1", "timestamp": "ghost", "active": True},
        )
        assert resp.status_code == 404
