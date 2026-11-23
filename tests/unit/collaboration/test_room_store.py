# -*- coding: utf-8 -*-
"""RoomStore 存储契约（2026-11-23 落点收口）：房间消息落
`data/collaboration/rooms/<room_id>/messages.jsonl`，**不再**借 agent 会话层、
**不再**在数据根顶层制造 `data/<room_id>/` 目录。

旧契约（room_id 同时当 agent_id+session_id 复用 SessionManager）随本批退役——
它曾让每个发过消息的房间都在 data/ 顶层长出一个目录（43 个 project_*）。
"""
from __future__ import annotations

import json
import threading

import pytest

from neurova.collaboration.room_store import (
    RoomStore,
    get_room_messages_path,
    get_room_store,
)


@pytest.fixture()
def dataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_append_lands_in_collaboration_namespace_not_top_level(dataRoot):
    store = RoomStore()
    store.append("project_ab12cd34ef56", "user", "u1", "你好")

    target = get_room_messages_path("project_ab12cd34ef56")
    assert target == dataRoot / "collaboration" / "rooms" / "project_ab12cd34ef56" / "messages.jsonl"
    assert target.exists(), "房间消息必须落在 collaboration/rooms 命名空间"
    assert not (dataRoot / "project_ab12cd34ef56").exists(), (
        "房间不得再在数据根顶层制造目录——那正是 316 个顶层条目的来源之一"
    )
    record = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
    assert record["sender_type"] == "user"
    assert record["sender_id"] == "u1"
    assert record["content"] == "你好"
    assert record["role"] == "user"
    assert record["timestamp"]


def test_agent_sender_maps_to_assistant_role_and_meta_roundtrip(dataRoot):
    store = RoomStore()
    store.append("project_x", "agent", "a1", "收到", {"model": "glm-4"})
    row = store.history("project_x")[0]
    assert row["sender_type"] == "agent"
    assert row["sender_id"] == "a1"
    assert row["role"] == "assistant"
    assert row["content"] == "收到"
    assert row["meta"] == {"model": "glm-4"}
    assert row["ts"]


def test_history_limit_returns_latest(dataRoot):
    store = RoomStore()
    for i in range(5):
        store.append("project_x", "user", "u1", f"m{i}")
    rows = store.history("project_x", limit=2)
    assert [r["content"] for r in rows] == ["m3", "m4"]
    assert len(store.history("project_x")) == 5


def test_rooms_are_isolated_by_room_id(dataRoot):
    store = RoomStore()
    store.append("project_a", "user", "u1", "a-msg")
    store.append("project_b", "user", "u1", "b-msg")
    assert [r["content"] for r in store.history("project_a")] == ["a-msg"]
    assert [r["content"] for r in store.history("project_b")] == ["b-msg"]
    assert get_room_messages_path("project_a").parent != get_room_messages_path("project_b").parent


def test_history_of_unknown_room_is_empty(dataRoot):
    assert RoomStore().history("project_nochat") == []


def test_concurrent_appends_keep_every_line(dataRoot):
    """房间是多发送者群聊：并发追加不得丢行（每行一条 JSON）。"""
    store = RoomStore()
    errors: list = []

    def worker(tid: int) -> None:
        try:
            for i in range(25):
                store.append("project_x", "agent", f"agent-{tid}", f"m-{tid}-{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    lines = get_room_messages_path("project_x").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    assert all(json.loads(line)["content"] for line in lines)


def test_room_id_is_sanitized_against_path_escape(dataRoot):
    """room_id 来自协作系统，但落盘前必须收进命名空间（防 ../ 逃逸）。"""
    store = RoomStore()
    store.append("../evil", "user", "u1", "x")
    target = get_room_messages_path("../evil")
    assert dataRoot / "collaboration" / "rooms" in target.parents
    assert target.exists()
    assert not (dataRoot / "evil").exists()
    assert not (dataRoot.parent / "evil").exists()


def test_singleton_returns_same_instance():
    assert get_room_store() is get_room_store()
