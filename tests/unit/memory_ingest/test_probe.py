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
