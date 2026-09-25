"""RoomStore 单元测试：复用 SessionManager 以 room_id 作 agent_id+session_id 键持久房间消息。

发送者归属经 metadata.{sender_type,sender_id} 往返；agent→assistant、user→user。
"""
from __future__ import annotations

from neurova.collaboration.room_store import RoomStore


class _FakeRepo:
    def __init__(self):
        self.saved = []

    def save_message(self, agent_id, session_id, role, content, metadata=None):
        self.saved.append({
            "agent_id": agent_id, "session_id": session_id, "role": role,
            "content": content, "metadata": metadata or {}, "timestamp": 1,
        })
        return True

    def get_history(self, agent_id, session_id, max_messages=0):
        return self.saved


def test_append_stores_under_room_id_and_sender_in_metadata():
    repo = _FakeRepo()
    store = RoomStore(repo=repo)
    store.append("project_x", "agent", "a1", "hello", {"model": "m"})
    m = repo.saved[0]
    assert m["agent_id"] == "project_x" and m["session_id"] == "project_x"
    assert m["role"] == "assistant"  # agent → assistant
    assert m["metadata"]["sender_id"] == "a1"
    assert m["metadata"]["sender_type"] == "agent"
    assert m["metadata"]["model"] == "m"


def test_user_maps_to_user_role():
    repo = _FakeRepo()
    RoomStore(repo=repo).append("project_x", "user", "u1", "hi")
    assert repo.saved[0]["role"] == "user"


def test_history_restores_sender_attribution():
    repo = _FakeRepo()
    store = RoomStore(repo=repo)
    store.append("project_x", "user", "u1", "hi")
    rows = store.history("project_x")
    assert rows[0]["sender_type"] == "user"
    assert rows[0]["sender_id"] == "u1"
    assert rows[0]["content"] == "hi"


def test_history_limit_returns_latest():
    repo = _FakeRepo()
    store = RoomStore(repo=repo)
    for i in range(5):
        store.append("project_x", "user", "u1", f"m{i}")
    rows = store.history("project_x", limit=2)
    assert [r["content"] for r in rows] == ["m3", "m4"]
