# -*- coding: utf-8 -*-
"""来源识别：结构断言 + 三态结论（设计 §5）。

未识别不是失败：必须回结构摘要供新增指纹，绝不允许"挑最像的格式硬导"。
私有方言（qwenpaw_memory* 一族，公开来源零命中）有意不在指纹表内。
"""
import json
import sqlite3
from pathlib import Path

from neurova.memory_ingest.probe import probe_store

QWENPAW_COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content",
                "tool_call_id", "tool_input", "tool_state", "headline", "blocks",
                "metadata", "created_at", "dedup_key"]


def _db(path: Path, cols) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in cols) + ")")
    conn.commit()
    conn.close()
    return path


def test_qwenpaw_history_recognized(tmp_path: Path):
    finding = probe_store(_db(tmp_path / "history.db", QWENPAW_COLS))

    assert finding.verdict == "unique"
    assert finding.hits == ("qwenpaw_history",)


def test_missing_dedup_key_is_not_recognized(tmp_path: Path):
    """像但不是：缺 dedup_key 即漂移，不能认成 QwenPaw（宁可未识别）。"""
    finding = probe_store(_db(tmp_path / "history.db",
                              [c for c in QWENPAW_COLS if c != "dedup_key"]))

    assert finding.verdict == "unknown"
    assert finding.hits == ()
    assert "conversation_history" in finding.structure["tables"]


def test_unrelated_sqlite_is_unknown_with_structure_summary(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "other.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()

    finding = probe_store(tmp_path / "other.db")

    assert finding.verdict == "unknown"
    assert finding.structure["tables"] == ["unrelated"]


def test_dsh_jsonl_header_recognized(tmp_path: Path):
    log = tmp_path / "session.jsonl"
    log.write_text(json.dumps({"type": "session", "version": 3, "id": "s1",
                               "createdAt": 1, "cwd": "/", "isSeeded": False,
                               "delegationDepth": 0}) + "\n", encoding="utf-8")

    assert probe_store(log).hits == ("dsh_session",)


def test_broken_jsonl_does_not_crash(tmp_path: Path):
    log = tmp_path / "broken.jsonl"
    log.write_text("{oops\n", encoding="utf-8")

    finding = probe_store(log)

    assert finding.verdict == "unknown" and finding.structure["first_line_keys"] == []


def test_directory_yields_one_finding_per_store(tmp_path: Path):
    """识别单位是 store 不是目录：一个目录里两族就要出两条结论。"""
    _db(tmp_path / "history.db", QWENPAW_COLS)
    (tmp_path / "session.jsonl").write_text(
        json.dumps({"type": "session", "version": 3, "id": "s", "createdAt": 1}) + "\n",
        encoding="utf-8")

    findings = probe_store(tmp_path)

    assert isinstance(findings, list) and len(findings) == 2
    assert sorted(f.hits[0] for f in findings) == ["dsh_session", "qwenpaw_history"]


def test_every_family_matches_only_its_own_store(tmp_path: Path):
    """四家 JSONL + 四家 SQLite（含只有指纹的一家）：每家都必须只被自己那支认出。

    这是 detect 的命门——互相误认会静默走错转换器，比认不出更糟。
    """
    _db(tmp_path / "history.db", QWENPAW_COLS)
    (tmp_path / "dialog.jsonl").write_text(json.dumps(
        {"role": "user", "name": "u", "content": [{"type": "text", "text": "甲"}],
         "timestamp": "2026-04-07 10:00:00", "id": "m1", "metadata": None}) + chr(10),
        encoding="utf-8")
    (tmp_path / "legacy.jsonl").write_text(json.dumps(
        {"type": "message", "message": {"role": "user", "content": "甲"},
         "timestamp": "2026-04-06T18:00:00Z", "id": "m1", "parentId": None}) + chr(10),
        encoding="utf-8")
    (tmp_path / "rollout.jsonl").write_text(json.dumps(
        {"type": "session_meta", "payload": {"id": "t1", "timestamp": "2026-05-01T10:00:00Z",
         "cwd": "/w"}}) + chr(10), encoding="utf-8")
    (tmp_path / "dsh.jsonl").write_text(json.dumps(
        {"type": "session", "version": 3, "id": "s1", "createdAt": 1}) + chr(10),
        encoding="utf-8")
    conn = __import__("sqlite3").connect(tmp_path / "opencode.db")
    conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, data TEXT)")
    conn.execute("CREATE TABLE part (id TEXT, message_id TEXT, data TEXT)")
    conn.commit()
    conn.close()
    conn = __import__("sqlite3").connect(tmp_path / "agent.db")
    conn.execute("CREATE TABLE transcript_events (session_id TEXT NOT NULL,"
                 " seq INTEGER NOT NULL, event_json TEXT NOT NULL, created_at INTEGER NOT NULL,"
                 " PRIMARY KEY (session_id, seq))")
    conn.execute("CREATE TABLE session_windows (session_id TEXT NOT NULL PRIMARY KEY,"
                 " session_key TEXT NOT NULL)")
    conn.commit()
    conn.close()
    conn = __import__("sqlite3").connect(tmp_path / "state.db")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
                 " content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,"
                 " timestamp REAL)")
    conn.commit()
    conn.close()

    expected = {"history.db": "qwenpaw_history", "dialog.jsonl": "dialog_daily",
                "legacy.jsonl": "legacy_session", "rollout.jsonl": "codex_rollout",
                "dsh.jsonl": "dsh_session", "opencode.db": "opencode_session",
                "agent.db": "openclaw_transcript", "state.db": "hermes_state"}

    for name, family in expected.items():
        finding = probe_store(tmp_path / name)
        assert finding.verdict == "unique", (name, finding.hits)
        assert finding.hits == (family,), (name, finding.hits)
