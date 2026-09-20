# -*- coding: utf-8 -*-
"""OpenClaw 会话族（agent 库的 transcript_events）→ Ingest Bundle。

格式取证自本机该平台上游源码，不是靠样例猜：
- 表结构 `src/state/openclaw-agent-schema.sql`：``transcript_events(session_id, seq,
  event_json, created_at)``，主键 (session_id, seq)，外键指向 ``session_windows``；
  会话出处在 ``session_windows``（session_key/model/channel/chat_type/parent_session_key…）。
- 事件信封 ``src/config/sessions/session-accessor.sqlite-transcript-store.ts``：
  ``{id, type, parentId, message}``，``type == "message"`` 时 ``message`` 才是可见正文；
  ``message.content`` 沿用 Anthropic 形块（text / thinking / tool_use / tool_result / 媒体），
  所以块词表复用 converters.blocks，一家一份的规则不再多写一遍。

seq 是这张表的主键，但重写/压缩后可能跳号——包内仍按会话重编 1..n，源 seq 留
extra.source_seq；非 message 事件一律申报条数，不猜它是正文。
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

import pytest

from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.converters.openclaw_transcript import CONVERTER_NAME, convert
from neurova.memory_ingest.probe import probe_store

COLS = ["session_id", "seq", "event_json", "created_at"]


def _event(event_id: str, etype: str, message: Dict[str, Any] = None,
           parent: str = None) -> str:
    body = {"id": event_id, "type": etype}
    if message is not None:
        body["message"] = message
    if parent:
        body["parentId"] = parent
    return json.dumps(body, ensure_ascii=False)


def _db(tmp_path: Path, name: str = "agent.db", events=None, windows=True,
        memory=None) -> Path:
    path = tmp_path / name
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE transcript_events (session_id TEXT NOT NULL, seq INTEGER NOT NULL,"
                 " event_json TEXT NOT NULL, created_at INTEGER NOT NULL,"
                 " PRIMARY KEY (session_id, seq))")
    if windows:
        conn.execute("CREATE TABLE session_windows (session_id TEXT NOT NULL PRIMARY KEY,"
                     " session_key TEXT NOT NULL, model TEXT, model_provider TEXT, channel TEXT,"
                     " chat_type TEXT, created_at INTEGER NOT NULL, parent_session_key TEXT)")
        conn.execute("INSERT INTO session_windows VALUES ('ses_a', 'key-a', 'gpt-x', 'pc',"
                     " 'telegram', 'direct', 1787791388521, NULL)")
    conn.executemany("INSERT INTO transcript_events VALUES (?,?,?,?)",
                     events if events is not None else [
                         ("ses_a", 1, _event("e1", "message",
                                             {"role": "user",
                                              "content": [{"type": "text", "text": "跑一下"}]}),
                          1787791388521),
                     ])
    _memory_tables(conn, memory)
    conn.commit()
    conn.close()
    return path


def _memory_tables(conn, memory) -> None:
    """按上游建表语句的列集建记忆索引三表（chunks 是正文，出处与召回各一张附表）。"""
    if memory is None:
        return
    conn.execute("CREATE TABLE memory_index_chunks (id TEXT PRIMARY KEY, path TEXT NOT NULL,"
                 " source TEXT NOT NULL DEFAULT 'memory', start_line INTEGER NOT NULL,"
                 " end_line INTEGER NOT NULL, hash TEXT NOT NULL, model TEXT NOT NULL,"
                 " text TEXT NOT NULL, embedding TEXT NOT NULL, updated_at INTEGER NOT NULL)")
    conn.execute("CREATE TABLE memory_index_chunk_provenance (chunk_id TEXT PRIMARY KEY,"
                 " origin_class TEXT NOT NULL, session_kind TEXT NOT NULL,"
                 " observed_at INTEGER NOT NULL, supersedes_key TEXT)")
    conn.execute("CREATE TABLE memory_index_chunk_recall_metadata (chunk_id TEXT PRIMARY KEY,"
                 " importance INTEGER, triggers TEXT, project_key TEXT)")
    conn.executemany("INSERT INTO memory_index_chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
                     memory.get("chunks", []))
    conn.executemany("INSERT INTO memory_index_chunk_provenance VALUES (?,?,?,?,?)",
                     memory.get("provenance", []))
    conn.executemany("INSERT INTO memory_index_chunk_recall_metadata VALUES (?,?,?,?)",
                     memory.get("recall", []))


def _chunk(chunk_id: str, text: str, *, source: str = "memory", path: str = "memory/笔记.md",
           lines=(3, 9), at: int = 1787791388521) -> tuple:
    return (chunk_id, path, source, lines[0], lines[1], "hash-" + chunk_id, "embed-model",
            text, "W1sxdGlu", at)


def _rows(out: Path) -> Dict[str, Dict[str, Any]]:
    return {r["identity_key"]: r for r in
            (json.loads(x) for x in (out / "transcripts.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip())}


def test_store_is_recognized_as_openclaw(tmp_path: Path):
    assert probe_store(_db(tmp_path)).hits == (CONVERTER_NAME,)


def test_missing_session_windows_is_not_recognized(tmp_path: Path):
    """外键指向的表没了就是漂移，宁可判未识别也不半导。"""
    assert probe_store(_db(tmp_path, windows=False)).verdict == "unknown"


def test_message_event_becomes_visible_record(tmp_path: Path):
    out = tmp_path / "bundle"

    manifest = convert(_db(tmp_path), out, agent_name="imported")

    assert validate_bundle(out) == []
    assert manifest.counts["transcripts"] == 1
    record = next(iter(_rows(out).values()))
    assert record["kind"] == "user_message" and record["role"] == "user"
    assert record["content_blocks"][0]["text"] == "跑一下"
    assert record["ts"].endswith("+00:00")
    assert record["extra"]["session_key"] == "key-a"
    assert record["extra"]["model"] == "gpt-x"


def test_tool_blocks_split_into_call_and_result(tmp_path: Path):
    events = [
        ("ses_a", 2, _event("e2", "message", {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "先看"},
            {"type": "text", "text": "我读"},
            {"type": "tool_use", "id": "tu1", "name": "read", "input": {"path": "A.md"}}]}),
         1787791400000),
        ("ses_a", 3, _event("e3", "message", {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "内容A"}]}), 1787791410000),
    ]

    manifest = convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    rows = list(_rows(tmp_path / "bundle").values())

    kinds = [r["kind"] for r in rows]
    assert "assistant_message" in kinds and "tool_call" in kinds and "tool_result" in kinds
    turn = next(r for r in rows if r["kind"] == "assistant_message")
    assert turn["content_blocks"][0]["text"] == "我读" and turn["reasoning_text"] == "先看"
    call = next(r for r in rows if r["kind"] == "tool_call")
    assert call["tool_call_id"] == "tu1" and call["tool_name"] == "read"
    assert json.loads(call["extra"]["tool_input"]) == {"path": "A.md"}
    result = next(r for r in rows if r["kind"] == "tool_result")
    assert result["role"] == "user" and result["tool_call_id"] == "tu1"
    assert result["content_blocks"][0]["text"] == "内容A"
    assert not any(e["field"].startswith("event:") for e in manifest.dropped)


def test_toolresult_role_is_not_thrown_away(tmp_path: Path):
    """结果行在这家是以 toolResult 角色寄出的，判成"认不出的角色"就等于把整条结果丢掉。"""
    events = [("ses_a", 1, _event("e1", "message", {"role": "toolResult", "content": [
        {"type": "tool_result", "tool_use_id": "tu1", "content": "结果正文"}]}), 1)]

    manifest = convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    record = next(iter(_rows(tmp_path / "bundle").values()))

    assert record["kind"] == "tool_result" and record["tool_call_id"] == "tu1"
    assert record["content_blocks"][0]["text"] == "结果正文"
    assert not any(e["field"].startswith("role:") for e in manifest.dropped)


def test_compaction_summary_becomes_a_summary_record(tmp_path: Path):
    events = [("ses_a", 1, _event("e1", "message", {"role": "compactionSummary",
                                                    "summary": "前情提要"}), 1)]

    convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    record = next(iter(_rows(tmp_path / "bundle").values()))

    assert record["kind"] == "compact_summary"
    assert record["content_blocks"][0]["text"] == "前情提要"


def test_event_timestamp_wins_over_the_row_column(tmp_path: Path):
    """created_at 是落库时刻；事件自带的 timestamp 才是发生时刻，两者并存时以后者为准。"""
    events = [("ses_a", 1, json.dumps({"id": "e1", "type": "message",
                                       "timestamp": "2026-05-01T10:00:00Z",
                                       "message": {"role": "user", "content": [
                                           {"type": "text", "text": "甲"}]}}),
               1_700_000_000_000)]

    convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")

    assert next(iter(_rows(tmp_path / "bundle").values()))["ts"] == "2026-05-01T10:00:00+00:00"


def test_keys_without_a_landing_are_declared(tmp_path: Path):
    events = [("ses_a", 1, json.dumps({"id": "e1", "type": "message",
                                       "sidecar": {"a": 1},
                                       "message": {"role": "user", "content": "甲",
                                                   "stopReason": "end_turn"}}), 1)]

    manifest = convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    fields = {e["field"] for e in manifest.dropped}

    assert "event键:sidecar" in fields and "消息键:stopReason" in fields


def test_foreign_role_name_does_not_leak_into_the_record(tmp_path: Path):
    """包内 role 会被运行期与前端读到：源里的角色名只留进 extra.source_role。

    包内空 role 的含义是"按 kind 取规范角色"（装配处与落盘各自兜底），所以这里钉的是
    "不是那个外来的名字"，而不是某个具体名字。
    """
    events = [("ses_a", 1, _event("e1", "message", {"role": "compactionSummary",
                                                    "summary": "前情提要"}), 1),
              ("ses_a", 2, _event("e2", "message", {"role": "toolResult", "content": [
                  {"type": "tool_result", "id": "tu9", "content": "结果"}]}), 2)]

    convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    rows = sorted(_rows(tmp_path / "bundle").values(), key=lambda r: r["seq"])

    assert [r["role"] for r in rows] == ["", ""]
    assert [r["extra"]["source_role"] for r in rows] == ["compactionSummary", "toolResult"]


def test_non_message_events_are_declared(tmp_path: Path):
    events = [
        ("ses_a", 1, _event("e1", "message", {"role": "user",
                                              "content": [{"type": "text", "text": "甲"}]}), 1),
        ("ses_a", 2, _event("e2", "compaction"), 2),
        ("ses_a", 3, _event("e3", "model_switch"), 3),
        ("ses_a", 4, json.dumps({"type": "no_id"}), 4),
    ]

    manifest = convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    fields = {e["field"]: e["count"] for e in manifest.dropped}

    assert fields["event:compaction"] == 1 and fields["event:model_switch"] == 1
    assert fields["event:<无id>"] == 1
    assert manifest.counts["transcripts"] == 1


def test_sparse_seq_is_renumbered_and_source_kept(tmp_path: Path):
    events = [("ses_a", 7, _event("e7", "message", {"role": "user", "content": [
        {"type": "text", "text": "第一段"}]}), 1),
        ("ses_a", 41, _event("e41", "message", {"role": "assistant", "content": [
            {"type": "text", "text": "第二段"}]}), 2)]

    convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    rows = sorted(_rows(tmp_path / "bundle").values(), key=lambda r: r["seq"])

    assert [r["seq"] for r in rows] == [1, 2]
    assert [r["extra"]["source_seq"] for r in rows] == [7, 41]
    assert validate_bundle(tmp_path / "bundle") == []


def test_media_block_lands_in_bundle(tmp_path: Path):
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    events = [("ses_a", 1, _event("e1", "message", {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                      "data": base64.b64encode(png).decode()}}]}), 1)]

    manifest = convert(_db(tmp_path, events=events), tmp_path / "bundle", agent_name="x")
    blocks = next(iter(_rows(tmp_path / "bundle").values()))["content_blocks"]

    assert blocks[0]["type"] == "image" and (tmp_path / "bundle" / blocks[0]["media"]).read_bytes() == png
    assert manifest.dropped == ()


def test_source_is_read_only(tmp_path: Path):
    src = _db(tmp_path)
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


def _memories(out: Path):
    return [json.loads(x) for x in (out / "memories.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]


def test_memory_index_chunks_land_as_memories(tmp_path: Path):
    """同属一支 store 的两族记录：会话从事件表来，记忆从索引表来，一支包两样都装。"""
    memory = {"chunks": [_chunk("ck1", "用户偏好中文回复")],
              "provenance": [("ck1", "owner", "interactive", 1787791388521, None)],
              "recall": [("ck1", 8, "回复语言", "proj-a")]}

    manifest = convert(_db(tmp_path, memory=memory), tmp_path / "bundle", agent_name="x")
    row = _memories(tmp_path / "bundle")[0]

    assert validate_bundle(tmp_path / "bundle") == []
    assert manifest.counts["memories"] == 1 and manifest.counts["transcripts"] == 1
    assert row["identity_key"] == "ck1" and row["content"] == "用户偏好中文回复"
    assert row["origin"] == "owner" and row["importance"] == 80.0
    assert row["memory_type"] == "semantic" and row["category"] == "knowledge"
    assert row["source_ref"] == "memory/笔记.md#L3-L9"
    assert row["ts"].endswith("+00:00")
    assert "session_kind:interactive" in row["tags"] and "project:proj-a" in row["tags"]


def test_session_sourced_chunks_map_to_episodic(tmp_path: Path):
    memory = {"chunks": [_chunk("ck2", "那次发布前夜", source="sessions")],
              "provenance": [("ck2", "agent", "subagent", 1787791388521, "ck1")]}

    convert(_db(tmp_path, memory=memory), tmp_path / "bundle", agent_name="x")
    row = _memories(tmp_path / "bundle")[0]

    assert (row["memory_type"], row["category"]) == ("episodic", "conversation")
    assert row["origin"] == "agent" and row["supersedes"] == "ck1"


def test_chunk_without_provenance_is_declared_not_guessed(tmp_path: Path):
    """origin 是信任级：源里没记出处就不导，宁可少一条也不给它抬信任。"""
    memory = {"chunks": [_chunk("ck3", "无出处条目")]}

    manifest = convert(_db(tmp_path, memory=memory), tmp_path / "bundle", agent_name="x")

    assert _memories(tmp_path / "bundle") == []
    assert manifest.counts["memories"] == 0
    entry = next(e for e in manifest.dropped if e["field"] == "memory:无出处")
    assert entry["count"] == 1 and "信任" in entry["reason"]


def test_missing_importance_uses_the_store_default(tmp_path: Path):
    memory = {"chunks": [_chunk("ck4", "没打重要度")],
              "provenance": [("ck4", "system", "cron", 1787791388521, None)]}

    convert(_db(tmp_path, memory=memory), tmp_path / "bundle", agent_name="x")

    assert _memories(tmp_path / "bundle")[0]["importance"] == 50.0


def test_derived_index_columns_are_declared_once(tmp_path: Path):
    """向量与内容哈希是派生索引，本系统自算：不搬，但条数要申报。"""
    memory = {"chunks": [_chunk("ck5", "甲"), _chunk("ck6", "乙")],
              "provenance": [("ck5", "owner", "interactive", 1, None),
                             ("ck6", "owner", "interactive", 1, None)]}

    manifest = convert(_db(tmp_path, memory=memory), tmp_path / "bundle", agent_name="x")
    entry = next(e for e in manifest.dropped if e["field"] == "memory:派生索引")

    assert entry["count"] == 2


def test_store_without_memory_tables_is_untouched(tmp_path: Path):
    """没建记忆索引的库不是"丢了记忆"：不产行也不申报。"""
    manifest = convert(_db(tmp_path), tmp_path / "bundle", agent_name="x")

    assert manifest.counts["memories"] == 0 and manifest.dropped == ()


@pytest.fixture()
def manager(tmp_path: Path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


@pytest.fixture()
def sessions(tmp_path: Path, monkeypatch):
    from neurova.session_manager import SessionManager
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def test_converted_memories_apply_and_undo(tmp_path: Path, manager, sessions):
    """整链闭环：转换器产出的记忆行要真能进咽喉，撤销后一条不剩。

    这一条查的是"字段翻译对了没"——origin 的词、importance 的尺度、ts 的格式在源侧
    对不上时，转换器自己不会报错，落库时才会。
    """
    from neurova.cognitive_layers.memory_layer.models import MemoryOrigin
    from neurova.memory_ingest.intake import apply_bundle

    memory = {"chunks": [_chunk("ck9", "用户偏好中文回复")],
              "provenance": [("ck9", "owner", "interactive", 1787791388521, None)],
              "recall": [("ck9", 8, None, None)]}
    out = tmp_path / "bundle"
    convert(_db(tmp_path, memory=memory), out, agent_name="imported")

    report = apply_bundle(out, agent_id="default", manager=manager, sessions=sessions)
    stored = next(m for m in manager._memories.values() if m.content == "用户偏好中文回复")

    assert report.memories_added == 1
    assert stored.origin is MemoryOrigin.OWNER and stored.importance == 80.0
    assert (stored.metadata.get("ingest") or {})["identity_key"] == "ck9"

    removed = report.undo(manager=manager, sessions=sessions)

    assert removed[0] == 1 and manager._memories == {}
