# -*- coding: utf-8 -*-
"""分诊训练收割器的新命名空间覆盖（2026-11-23 落点收口配套）。

房间消息迁入 `data/collaboration/rooms/<room_id>/messages.jsonl`、外部数据集
迁入 `data/training_datasets/<source>/sessions/` 之后，收割器必须仍能吃到这两
类真实会话（否则训练数据静默缩水）。
"""
from __future__ import annotations

import json

from neurova.collaboration.triage_dataset import harvestSessionWindows


def _sessionFile(path, sessionId: str, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"msg-{sessionId}-{i}", "timestamp": f"2026-11-22T08:00:{i:02d}"}
        for i in range(count)
    ]
    path.write_text(json.dumps({"session_id": sessionId, "messages": messages}), encoding="utf-8")


def test_harvest_reads_training_datasets_namespace(tmp_path):
    _sessionFile(tmp_path / "training_datasets" / "ds1" / "sessions" / "session_a.json", "a", 8)
    windows = harvestSessionWindows(tmp_path, minMessages=6)
    assert any(w["conversationId"] == "training_datasets/ds1/a" for w in windows), windows


def test_harvest_reads_room_message_logs(tmp_path):
    log = tmp_path / "collaboration" / "rooms" / "project_x" / "messages.jsonl"
    log.parent.mkdir(parents=True)
    lines = []
    for i in range(7):
        lines.append(json.dumps({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"room-{i}",
            "timestamp": f"2026-11-22T09:00:{i:02d}",
            "sender_type": "user" if i % 2 == 0 else "agent",
            "sender_id": "u1" if i % 2 == 0 else "a1",
        }))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    windows = harvestSessionWindows(tmp_path, minMessages=6)
    assert any(w["conversationId"] == "collaboration/rooms/project_x" for w in windows), windows
    roomWindow = next(w for w in windows if w["conversationId"] == "collaboration/rooms/project_x")
    assert [e["content"] for e in roomWindow["events"]] == [f"room-{i}" for i in range(7)]


def test_harvest_room_skips_system_lines_and_short_rooms(tmp_path):
    log = tmp_path / "collaboration" / "rooms" / "project_short" / "messages.jsonl"
    log.parent.mkdir(parents=True)
    lines = [json.dumps({"role": "system", "content": "sys", "timestamp": "t"})]
    lines += [json.dumps({"role": "user", "content": f"u{i}", "timestamp": "t"}) for i in range(3)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert harvestSessionWindows(tmp_path, minMessages=6) == []
