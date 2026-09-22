# -*- coding: utf-8 -*-
"""记忆写入口的属主参数：为他人导入的记忆要有主（Issue #81 断点②，用户拍板）。

红灯依据：`apply --owner-user-id u_alice` 只覆盖会话面——同一支包里的记忆行三元组取
**调用现场**作用域（CLI 下即 `('default','default')`），于是"为他人导入的会话有主、
同一支包里的记忆无主"。实测：u_alice 实例 reload 拿到 0 条、她的列表为空、recall 也空；
她只能经管理口径（agent_wide）看见。

根因与 F-04 同源——**导入侧生产了"没有属主"这份状态**——只是落在另一条咽喉上。
所以修在记忆写入口：`import_memories(..., owner_user_id=...)` 给行定标属主，
缺省仍取调用现场作用域（行为与既有口径一致，单用户桌面下无感）。

判据（先红后绿）：
1. 属主给定 → 行三元组的账号与用户两轴都是该属主，属主实例按三层隔离检索可见；
2. 非属主实例按同一判据检索看不见（归属不是装饰，真的参与隔离）；
3. 缺省不给属主 → 取调用现场作用域（旧行为不变，不悄悄改成 default 或空）；
4. 端到端：真 intake `apply_bundle(owner_user_id=...)` 把属主透传到记忆行；
5. 撤销仍按行自带三元组删干净——属主变了不等于撤不掉。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.records import MemoryRecord

_RUN = "nvimp-owner-1"


def _manager(tmp_path: Path, user_id: str = "default", neuser_id: str = "default") -> MemoryManager:
    return MemoryManager(
        db_path=str(tmp_path / "memory" / "memory.db"),
        agent_id="owner-agent",
        neuser_id=neuser_id,
        user_id=user_id,
        enable_buffer=False,
    )


def _record(seq: int, content: str) -> MemoryRecord:
    return MemoryRecord(identity_key=f"ik-owner-{seq}", content=content,
                        memory_type="semantic", category="general", origin="owner",
                        importance=60.0, ts=f"2026-05-0{seq}T10:00:00+00:00")


def test_owner_is_stamped_on_both_identity_axes(tmp_path: Path):
    manager = _manager(tmp_path)

    manager.import_memories([_record(1, "u_alice 的历史")], ingest_run_id=_RUN,
                            owner_user_id="u_alice")

    stored = next(m for m in manager._memories.values() if m.content == "u_alice 的历史")
    assert (stored.neuser_id, stored.user_id) == ("u_alice", "u_alice"), (
        "属主只写了一轴：三层隔离的第二轴仍回落到调用现场，属主实例按作用域检索依旧看不见"
    )


def test_owner_row_is_visible_to_its_owner_and_hidden_from_others(tmp_path: Path):
    writer = _manager(tmp_path)
    writer.import_memories([_record(1, "u_alice 的历史")], ingest_run_id=_RUN,
                          owner_user_id="u_alice")
    writer.close()

    alice = _manager(tmp_path, user_id="u_alice", neuser_id="u_alice")
    bob = _manager(tmp_path, user_id="u_bob", neuser_id="u_bob")

    assert "u_alice 的历史" in [row["content"] for row in alice.get_memories(limit=100)], (
        "属主实例按自己作用域检索看不见被导入给她的记忆——属主参数没生效"
    )
    assert "u_alice 的历史" not in [row["content"] for row in bob.get_memories(limit=100)], (
        "非属主按同一判据看见了别人的私有历史——归属没参与隔离"
    )
    alice.close()
    bob.close()


def test_without_owner_the_calling_scope_is_used(tmp_path: Path):
    """缺省不给属主：仍是调用现场作用域（旧行为不变）。"""
    manager = _manager(tmp_path, user_id="u_carol", neuser_id="u_carol")

    manager.import_memories([_record(1, "现场作用域的历史")], ingest_run_id=_RUN)

    stored = next(m for m in manager._memories.values() if m.content == "现场作用域的历史")
    assert (stored.neuser_id, stored.user_id) == ("u_carol", "u_carol")


def test_owner_survives_undo_by_row_scope(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.import_memories([_record(1, "要撤掉的属主行")], ingest_run_id=_RUN,
                            owner_user_id="u_alice")

    removed = manager.delete_ingested_memories(_RUN)
    manager.close()

    assert removed == 1
    reopened = _manager(tmp_path)
    assert reopened._memories == {}, "属主行的撤销没删掉盘上行——重启即复活"
    reopened.close()


def test_intake_apply_stamps_the_owner_on_memories(tmp_path: Path, monkeypatch):
    """端到端：真 apply_bundle 的 owner_user_id 同时管会话面与记忆面。"""
    from neurova.memory_ingest.intake import apply_bundle
    from neurova.session_manager import SessionManager

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "imported", "source": {"converter": "test", "version": "1"},
        "counts": {"transcripts": 1, "memories": 1, "relations": 0},
        "dropped": [], "stores": []}), encoding="utf-8")
    (bundle / "transcripts.jsonl").write_text(json.dumps({
        "session_id": "sA", "seq": 1, "kind": "user_message",
        "ts": "2026-05-01T10:00:01+00:00", "identity_key": "e1", "role": "user",
        "content_blocks": [{"type": "text", "text": "问题"}]}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (bundle / "memories.jsonl").write_text(json.dumps({
        "identity_key": "m1", "content": "同批导入的记忆", "memory_type": "semantic",
        "category": "general", "origin": "owner", "importance": 60.0,
        "ts": "2026-05-01T10:00:00+00:00"}, ensure_ascii=False) + "\n",
        encoding="utf-8")

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    sessions = SessionManager()
    manager = _manager(tmp_path)
    try:
        report = apply_bundle(bundle, agent_id="owner-agent", manager=manager,
                              sessions=sessions, owner_user_id="u_alice")

        stored = next(m for m in manager._memories.values() if m.content == "同批导入的记忆")
        assert (stored.neuser_id, stored.user_id) == ("u_alice", "u_alice"), (
            "同一支包里的会话有主、记忆无主——apply 没把属主透给记忆写入口"
        )
        assert report.owner_user_id == "u_alice"
    finally:
        SessionManager._instance = None


def test_same_identity_key_can_be_imported_for_two_owners(tmp_path: Path):
    """同一份历史导给两个人：各自一条行，不是"先到的占住幂等键"。

    幂等键是"这段历史"的身份，行的归属是"这段历史是谁的"——两者不是同一件事。
    按全局键去重会让第二个属主静默少一批记忆（报告写 +0、他的列表据此为空）。
    """
    writer = _manager(tmp_path)
    first = writer.import_memories([_record(1, "同一段历史")], ingest_run_id="nvimp-a",
                                   owner_user_id="u_alice")
    second = writer.import_memories([_record(1, "同一段历史")], ingest_run_id="nvimp-b",
                                    owner_user_id="u_bob")
    writer.close()
    assert (first["added"], second["added"]) == (1, 1), (
        f"同一份历史导给第二个人被静默回落成跳过：{first} / {second}"
    )

    alice = _manager(tmp_path, user_id="u_alice", neuser_id="u_alice")
    bob = _manager(tmp_path, user_id="u_bob", neuser_id="u_bob")

    assert [row["content"] for row in alice.get_memories(limit=100)] == ["同一段历史"]
    assert [row["content"] for row in bob.get_memories(limit=100)] == ["同一段历史"]
    alice.close()
    bob.close()


def test_supersede_declaration_looks_in_the_owners_scope(tmp_path: Path):
    """取代声明的旧行要在**属主作用域**里找：属主导入的取代不能因现场作用域不同而落空。"""
    writer = _manager(tmp_path)
    writer.import_memories([_record(1, "旧结论")], ingest_run_id="nvimp-old",
                           owner_user_id="u_alice")
    writer.close()

    running = _manager(tmp_path)
    outcome = running.import_memories(
        [MemoryRecord(identity_key="ik-owner-new", content="新结论", memory_type="semantic",
                      category="general", origin="owner", importance=60.0,
                      ts="2026-05-02T10:00:00+00:00", supersedes="旧结论")],
        ingest_run_id="nvimp-new", owner_user_id="u_alice")
    running.close()

    assert outcome["superseded"], "属主导入的取代声明落成了找不到目标——旧行就在属主作用域里"
    assert outcome["supersede_unresolved"] == []


def test_cli_owner_flag_lands_on_memories_too(tmp_path: Path, monkeypatch, capsys):
    """CLI 面：`--owner-user-id` 一处给，会话行与记忆行两条咽喉都用。"""
    from scripts.ingest_memory import main

    from neurova.session_manager import SessionManager

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "cli-owner", "source": {"converter": "test", "version": "1"},
        "counts": {"transcripts": 1, "memories": 1, "relations": 0},
        "dropped": [], "stores": []}), encoding="utf-8")
    (bundle / "transcripts.jsonl").write_text(json.dumps({
        "session_id": "sA", "seq": 1, "kind": "user_message",
        "ts": "2026-05-01T10:00:01+00:00", "identity_key": "e1", "role": "user",
        "content_blocks": [{"type": "text", "text": "问题"}]}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (bundle / "memories.jsonl").write_text(json.dumps({
        "identity_key": "m1", "content": "CLI 导入的属主记忆", "memory_type": "semantic",
        "category": "general", "origin": "owner", "importance": 60.0,
        "ts": "2026-05-01T10:00:00+00:00"}, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    sessions = SessionManager()
    manager = _manager(tmp_path)
    try:
        code = main(["apply", str(bundle), "--agent-id", "owner-agent", "--yes",
                     "--run-id", "cli-owner-1", "--owner-user-id", "u_alice"],
                    manager=manager, sessions=sessions)
        rows = list(manager._memories.values())
        assert code == 0 and rows, f"CLI 导入没有落记忆行（退出码 {code}）"
        assert all((m.neuser_id, m.user_id) == ("u_alice", "u_alice") for m in rows), (
            "CLI 给了属主，记忆行仍取调用现场作用域——会话有主、记忆无主"
        )
        stored_session = next(iter(sessions.iter_session_files("owner-agent")))
        assert json.loads(stored_session.read_text(encoding="utf-8"))["user_id"] == "u_alice"
    finally:
        SessionManager._instance = None
        capsys.readouterr()
