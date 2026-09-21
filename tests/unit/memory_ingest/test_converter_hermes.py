# -*- coding: utf-8 -*-
"""Hermes 会话族（单库 state.db 的 messages + sessions）→ Ingest Bundle。

格式取证自该平台上游源码（不是靠样例猜）：
- hermes_state_common.py:328-430 SCHEMA_SQL（SCHEMA_VERSION=30）：
  ``messages(id, session_id, role, content, tool_call_id, tool_calls, tool_name,
  effect_disposition, timestamp, token_count, finish_reason, reasoning, reasoning_content,
  reasoning_details, codex_reasoning_items, codex_message_items, platform_message_id,
  observed, _compressed_summary, active, compacted, api_content, display_kind,
  display_metadata, display_identity, display_order)``，
  ``sessions(id, source, session_key, chat_id, chat_type, model, parent_session_id, ...)``，
  另有 ``schema_version(version)`` 一支——这一家是有版本号的，漂移可以直接判而不是猜。
- hermes_state.py:1537 ``_CONTENT_JSON_PREFIX = "\\x00json:"``：content 列里的块数组是
  带哨兵前缀的 JSON（_encode_content/_decode_content，hermes_state_messages.py:124-145），
  裸字符串就是正文。
- hermes_state_messages.py:245-270 _message_row_params：tool_calls 是 json.dumps 后的数组，
  一次调用一条元素；三个 reasoning_* 列存的是 JSON 文本而非人类可读推理。
- agent/session_persistence.py:154-186 _db_flush_row：行键与上面同集，_compressed_summary
  为标记位（摘要行）。

timestamp 是 REAL 秒（epoch），不是 ISO 串；顺序靠 id（AUTOINCREMENT），不靠时间。
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

import pytest

from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.converters.hermes_state import CONVERTER_NAME, convert
from neurova.memory_ingest.probe import probe_store

MESSAGE_COLUMNS = ("id", "session_id", "role", "content", "tool_call_id", "tool_calls",
                   "tool_name", "effect_disposition", "timestamp", "token_count",
                   "finish_reason", "reasoning", "reasoning_content", "reasoning_details",
                   "codex_reasoning_items", "codex_message_items", "platform_message_id",
                   "observed", "_compressed_summary", "active", "compacted", "api_content",
                   "display_kind", "display_metadata", "display_identity", "display_order")

SENTINEL = "\x00json:"


def _db(tmp_path: Path, name: str = "state.db", rows=(), sessions=None,
        version: int = 30, extra_column: str = "") -> Path:
    path = tmp_path / name
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version VALUES (?)", (version,))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL,"
                 " session_key TEXT, chat_id TEXT, chat_type TEXT, model TEXT,"
                 " parent_session_id TEXT, title TEXT, started_at REAL NOT NULL)")
    columns = ", ".join(MESSAGE_COLUMNS)
    if extra_column:
        columns += f", {extra_column} TEXT"
    conn.execute(f"CREATE TABLE messages ({columns})")
    placeholders = ", ".join(["?"] * (len(MESSAGE_COLUMNS) + bool(extra_column)))
    conn.executemany(f"INSERT INTO messages VALUES ({placeholders})",
                     [_row(row, bool(extra_column)) for row in rows])
    for session in (sessions if sessions is not None else
                    [("ses_a", "cli", "key-a", None, "direct", "gpt-x", None, "标题", 1.0)]):
        conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)", session)
    conn.commit()
    conn.close()
    return path


def _row(values: Dict[str, Any], pad: bool = False) -> tuple:
    row = [None] * len(MESSAGE_COLUMNS)
    for key, value in values.items():
        row[MESSAGE_COLUMNS.index(key)] = value
    return tuple(row + [None] if pad else row)


def _rows(out: Path) -> Dict[str, Dict[str, Any]]:
    return {r["identity_key"]: r for r in
            (json.loads(x) for x in (out / "transcripts.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip())}


def _message(msg_id: int, role: str, content: Any, **extra) -> Dict[str, Any]:
    body = {"id": msg_id, "session_id": "ses_a", "role": role, "content": content,
            "timestamp": 1787791388.5}
    body.update(extra)
    return body


def test_store_is_recognized_as_hermes(tmp_path: Path):
    assert probe_store(_db(tmp_path, rows=[_message(1, "user", "甲")])).hits == (CONVERTER_NAME,)


def test_missing_sessions_table_is_not_recognized(tmp_path: Path):
    """血缘表没了就无从确定会话出处，宁可判未识别。"""
    path = tmp_path / "nochildren.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
                 " content TEXT, timestamp REAL)")
    conn.commit()
    conn.close()
    assert probe_store(path).verdict == "unknown"


def test_plain_rows_become_visible_records(tmp_path: Path):
    out = tmp_path / "bundle"

    manifest = convert(_db(tmp_path, rows=[_message(1, "user", "甲"),
                                           _message(2, "assistant", "乙")]),
                       out, agent_name="imported")

    assert validate_bundle(out) == []
    assert manifest.counts["transcripts"] == 2
    first = next(iter(_rows(out).values()))
    assert first["kind"] == "user_message" and first["content_blocks"][0]["text"] == "甲"
    assert first["ts"].startswith("2026-") and first["ts"].endswith("+00:00")
    assert first["extra"]["session_key"] == "key-a" and first["extra"]["model"] == "gpt-x"


def test_sentinel_content_decodes_to_parts(tmp_path: Path):
    """块数组按哨兵前缀解，不能把 \x00json:[...] 原样当正文搬进包。"""
    parts = [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "x"}}]

    manifest = convert(_db(tmp_path, rows=[_message(1, "user", SENTINEL + json.dumps(parts))]),
                       tmp_path / "bundle", agent_name="x")
    record = next(iter(_rows(tmp_path / "bundle").values()))

    assert record["content_blocks"][0]["text"] == "看图"
    assert any(e["field"] == "blocks:image_url" for e in manifest.dropped)


def test_tool_calls_array_expands_to_one_call_each(tmp_path: Path):
    calls = [{"id": "c1", "function": {"name": "read", "arguments": '{"p":"A.md"}'}},
             {"id": "c2", "function": {"name": "grep", "arguments": '{"q":"x"}'}}]
    rows = [_message(1, "user", "甲"),
            _message(2, "assistant", None, tool_calls=json.dumps(calls)),
            _message(3, "tool", "内容A", tool_call_id="c1", tool_name="read"),
            _message(4, "tool", "内容B", tool_call_id="c2", tool_name="grep")]

    manifest = convert(_db(tmp_path, rows=rows), tmp_path / "bundle", agent_name="x")
    events = list(_rows(tmp_path / "bundle").values())

    assert manifest.counts["transcripts"] == 5            # 1 正文 + 2 调用 + 2 结果
    calls_found = [e for e in events if e["kind"] == "tool_call"]
    assert {c["tool_call_id"] for c in calls_found} == {"c1", "c2"}
    assert json.loads(calls_found[0]["extra"]["tool_input"]) == {"p": "A.md"}
    results = {e["tool_call_id"]: e for e in events if e["kind"] == "tool_result"}
    assert set(results) == {"c1", "c2"}
    assert results["c2"]["content_blocks"][0]["text"] == "内容B"


def test_compressed_summary_row_becomes_summary_kind(tmp_path: Path):
    rows = [_message(1, "system", "前情提要", _compressed_summary=1)]

    convert(_db(tmp_path, rows=rows), tmp_path / "bundle", agent_name="x")

    assert next(iter(_rows(tmp_path / "bundle").values()))["kind"] == "compact_summary"


def test_readable_reasoning_is_text_and_structured_is_opaque(tmp_path: Path):
    rows = [_message(1, "assistant", "甲", reasoning="我想了想"),
            _message(2, "assistant", "乙", reasoning_details=json.dumps([{"id": "enc"}]))]

    convert(_db(tmp_path, rows=rows), tmp_path / "bundle", agent_name="x")
    events = _rows(tmp_path / "bundle")

    states = {r["content_blocks"][0]["text"]: (r["reasoning_state"], r["reasoning_text"])
              for r in events.values()}
    assert states["甲"] == ("text", "我想了想")
    assert states["乙"][0] == "opaque" and states["乙"][1] == ""


def test_reasoning_text_and_structured_items_both_declared(tmp_path: Path):
    """有明文摘要不等于密文项没被丢：两份都得看得见。"""
    rows = [_message(1, "assistant", "甲", reasoning="先想",
                     reasoning_details=json.dumps([{"id": "enc"}]))]

    manifest = convert(_db(tmp_path, rows=rows), tmp_path / "bundle", agent_name="x")

    assert any(e["field"] == "reasoning:结构化" and e["count"] == 1
               for e in manifest.dropped)


def test_columns_without_a_landing_are_declared(tmp_path: Path):
    rows = [_message(1, "user", "甲")]
    path = _db(tmp_path, rows=rows, extra_column="mystery")
    conn = sqlite3.connect(path)
    conn.execute("UPDATE messages SET mystery='值'")
    conn.commit()
    conn.close()

    manifest = convert(path, tmp_path / "bundle", agent_name="x")

    entry = next(e for e in manifest.dropped if e["field"] == "mystery")
    assert entry["count"] == 1


def test_newer_schema_version_is_reported_not_guessed(tmp_path: Path):
    """版本号只申报不阻拦：列齐了就能转，但包外必须看得见"这库比转换器已知的新"。"""
    manifest = convert(_db(tmp_path, rows=[_message(1, "user", "甲")], version=99),
                       tmp_path / "bundle", agent_name="x")

    assert manifest.stores[0]["schema_version"] == 99
    assert any("schema_version" in e["field"] for e in manifest.dropped)


def test_source_is_read_only(tmp_path: Path):
    src = _db(tmp_path, rows=[_message(1, "user", "甲")])
    before = src.read_bytes()

    convert(src, tmp_path / "bundle", agent_name="x")

    assert src.read_bytes() == before


def test_refuses_foreign_store(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "other.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(Exception):
        convert(tmp_path / "other.db", tmp_path / "bundle", agent_name="x")


def test_is_routable_by_handprint_name():
    assert CONVERTERS[CONVERTER_NAME] is convert
