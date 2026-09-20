# -*- coding: utf-8 -*-
"""intake 编排：校验 → 只读出计划 → 显式写库 → 按批次撤销。

"不 --apply 就不写库"的姿态在这里落地：plan_bundle 全程只读。写会话必须过轮形装配，
否则导入产物是运行期从不在盘上出现的形状（见 bundle/turns.py）。
"""
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.manifest import BundleError
from neurova.memory_ingest.intake import apply_bundle, plan_bundle
from neurova.session_manager import SessionManager

_ROWS: List[Dict[str, Any]] = [
    {"session_id": "sA", "seq": 1, "kind": "user_message", "ts": "2026-05-01T10:00:01+00:00",
     "identity_key": "e1", "role": "user",
     "content_blocks": [{"type": "text", "text": "问题"}]},
    {"session_id": "sA", "seq": 2, "kind": "assistant_message",
     "ts": "2026-05-01T10:00:02+00:00", "identity_key": "e2", "role": "assistant",
     "content_blocks": [{"type": "text", "text": "先读文件"}], "reasoning_state": "text",
     "reasoning_text": "在想"},
    {"session_id": "sA", "seq": 3, "kind": "tool_call", "ts": "2026-05-01T10:00:03+00:00",
     "identity_key": "e3", "role": "assistant", "tool_call_id": "tc1",
     "tool_name": "fs_read", "extra": {"tool_input": '{"path": "A.md"}'}},
    {"session_id": "sA", "seq": 4, "kind": "tool_result", "ts": "2026-05-01T10:00:04+00:00",
     "identity_key": "e4", "role": "tool", "tool_call_id": "tc1", "tool_name": "fs_read",
     "tool_state": "success", "content_blocks": [{"type": "text", "text": "结果正文"}]},
]

_MEM = {"identity_key": "m1", "content": "历史记忆", "memory_type": "semantic",
        "category": "general", "origin": "owner", "importance": 60.0,
        "ts": "2026-05-01T10:00:00+00:00"}

_DROPPED = [{"field": "blocks:data", "count": 1, "reason": "media 未落地"}]


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    return _write_bundle(tmp_path, _ROWS, [_MEM])


def _write_bundle(tmp_path: Path, rows, memories=(), *, counts=None, dropped=()) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "imported", "source": {"converter": "test", "version": "1"},
        "counts": counts or {"transcripts": len(rows), "memories": len(memories),
                             "relations": 0},
        "dropped": list(dropped), "stores": []}, ensure_ascii=False), encoding="utf-8")
    (root / "transcripts.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    (root / "memories.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in memories), encoding="utf-8")
    return root


@pytest.fixture()
def manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


@pytest.fixture()
def sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def _stored_messages(sessions: SessionManager, agent_id: str, session_id: str) -> List[dict]:
    path = sessions._get_session_file(agent_id, session_id, "2026-05-01")
    data = sessions._read_session_file(path) or {}
    return data.get("messages", [])


def test_plan_is_read_only(manager, sessions, bundle, tmp_path: Path):
    plan = plan_bundle(bundle)

    assert plan.counts == {"transcripts": 4, "memories": 1}
    assert plan.turn_messages == 2               # 4 条事件装配成 2 条轮形消息
    assert plan.agent_name == "imported"
    assert manager._memories == {}
    # 会话根目录由 SessionManager 自身建，只读的要害是不产出任何会话文件
    assert not list((tmp_path / "sessions").glob("**/session_*.json"))


def test_apply_writes_both_throats(manager, sessions, bundle):
    report = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)

    assert (report.memories_added, report.memories_skipped) == (1, 0)
    assert (report.messages_added, report.messages_skipped) == (2, 0)
    assert report.sessions_touched == 1
    assert any(m.content == "历史记忆" for m in manager._memories.values())


def test_apply_writes_turn_shaped_messages(manager, sessions, bundle):
    """写进会话文件的必须是运行期那条形：一条 assistant 消息带整串工具调用与结果。"""
    apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)

    stored = _stored_messages(sessions, "default", "sA")
    assert [m["role"] for m in stored] == ["user", "assistant"]
    turn = stored[1]
    assert turn["content"] == "先读文件"
    assert turn["metadata"]["reasoning_content"] == "在想"
    entries = turn["metadata"]["tool_calls"]
    assert [e["type"] for e in entries] == ["tool_call", "tool_result"]
    assert entries[0]["params"] == {"path": "A.md"}
    assert entries[1]["result"] == "结果正文"


def test_apply_twice_is_idempotent(manager, sessions, bundle):
    first = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    second = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)

    assert (first.memories_added, first.messages_added) == (1, 2)
    assert (second.memories_added, second.memories_skipped) == (0, 1)
    assert (second.messages_added, second.messages_skipped) == (0, 2)


def test_undo_removes_exactly_the_batch(manager, sessions, bundle):
    report = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    manager.remember(content="运行期记忆", category="general")

    mem_removed, msg_removed = report.undo(manager=manager, sessions=sessions)

    assert (mem_removed, msg_removed) == (1, 2)
    assert [m.content for m in manager._memories.values()] == ["运行期记忆"]


def test_report_carries_loss_declarations(manager, sessions, tmp_path: Path):
    root = _write_bundle(tmp_path, _ROWS, [], dropped=_DROPPED)

    plan = plan_bundle(root)
    report = apply_bundle(root, agent_id="default", manager=manager, sessions=sessions)

    assert plan.dropped == tuple(_DROPPED)
    assert report.dropped == tuple(_DROPPED)


def test_invalid_bundle_is_rejected_wholesale(manager, sessions, tmp_path: Path):
    broken = _write_bundle(tmp_path, _ROWS, [], counts={"transcripts": 99, "memories": 0,
                                                        "relations": 0})

    with pytest.raises(BundleError, match="计数不符"):
        plan_bundle(broken)
    assert manager._memories == {}


def test_unknown_field_in_record_is_rejected(manager, sessions, tmp_path: Path):
    """拼错的字段名不能被静默忽略：整包拒绝，否则那条数据的语义已经不可知。"""
    rows = [dict(_ROWS[0], dreaming="?")]
    root = _write_bundle(tmp_path, rows, [])

    with pytest.raises(BundleError, match="transcripts.jsonl"):
        apply_bundle(root, agent_id="default", manager=manager, sessions=sessions)


def test_oversized_bundle_is_refused(manager, sessions, bundle, monkeypatch):
    monkeypatch.setattr("neurova.memory_ingest.intake.MAX_RECORDS", 3)

    with pytest.raises(BundleError, match="超上限"):
        apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)


def test_session_write_failure_tells_how_to_undo(manager, sessions, bundle, monkeypatch):
    """半途失败不能留悬批：报错必须给出撤销路径，已落的记忆才收得回。"""
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sessions, "import_session_messages", boom)

    with pytest.raises(BundleError, match="undo"):
        apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    assert any(m.content == "历史记忆" for m in manager._memories.values())


def test_hostile_agent_id_is_refused_before_any_write(manager, sessions, bundle, tmp_path):
    with pytest.raises(BundleError, match="agent_id"):
        apply_bundle(bundle, agent_id="../escape", manager=manager, sessions=sessions)

    assert manager._memories == {}
    assert not list(tmp_path.glob("**/session_*.json"))
