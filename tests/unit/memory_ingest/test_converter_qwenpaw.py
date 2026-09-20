# -*- coding: utf-8 -*-
"""QwenPaw 会话族转换器：只产包、不写库。

现脚本对 conversation_history 是字段级有损的（14 列只取 9 列），本转换器的验收标准是
把 headline / tool_state / agent_id / tool_input / metadata 补回；凡是契约与 extra 都
接不住的东西（未知列、未知 kind）必须进 manifest.dropped 申报——静默降级是市面互导
实现共同的病灶。
"""
import json
import sqlite3
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters.qwenpaw_history import convert

COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content", "tool_call_id",
        "tool_input", "tool_state", "headline", "blocks", "metadata", "created_at", "dedup_key"]


def _row(**kw):
    base = {c: None for c in COLS}
    base.update(kw)
    return tuple(base[c] for c in COLS)


@pytest.fixture()
def src(tmp_path: Path) -> Path:
    """源 kind 用真实词表（context_msg / model_turn / tool_result），不是包内规范名。"""
    db = tmp_path / "history.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in COLS) + ")")
    conn.executemany(
        f"INSERT INTO conversation_history VALUES ({','.join('?' * len(COLS))})",
        [
            _row(seq=1, session_id="sA", agent_id="凯", kind="context_msg", role="user",
                 name="用户", content="问题", created_at="2026-05-01T10:00:01", dedup_key="k1"),
            _row(seq=2, session_id="sA", agent_id="凯", kind="model_turn", role="assistant",
                 name="凯", content="先读文件", headline="要点",
                 blocks=json.dumps([{"type": "thinking", "thinking": "想一想"}]),
                 created_at="2026-05-01T10:00:02", dedup_key="k2"),
            _row(seq=3, session_id="sA", agent_id="凯", kind="tool_result", role="tool",
                 name="fs_read", content="结果", tool_call_id="tc1", tool_state="ok",
                 created_at="2026-05-01T10:00:03", dedup_key="k3"),
            _row(seq=4, session_id="sA", agent_id="凯", kind="model_turn", role="assistant",
                 name="fs_read", tool_call_id="tc9",
                 tool_input=json.dumps({"path": "config"}),
                 created_at="2026-05-01T10:00:04", dedup_key="k4"),
            _row(seq=5, session_id="sB", agent_id="凯", kind="context_msg", role="user",
                 name="用户", content="另一会话", created_at="2026-05-01T11:00:01",
                 dedup_key="k5"),
        ])
    conn.commit()
    conn.close()
    return db


def _records(out: Path):
    lines = [json.loads(x) for x in (out / "transcripts.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    return {f"{r['session_id']}:{r['seq']}": r for r in lines}


def test_convert_produces_valid_bundle(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")

    assert validate_bundle(out) == []


def test_convert_keeps_fields_the_old_script_dropped(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert by_key["sA:2"]["extra"]["headline"] == "要点"
    assert by_key["sA:3"]["tool_state"] == "ok"
    assert by_key["sA:1"]["extra"]["agent_id"] == "凯"
    assert by_key["sA:4"]["extra"]["tool_input"] == json.dumps({"path": "config"})


def test_convert_normalizes_source_kinds(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert [by_key[f"sA:{n}"]["kind"] for n in (1, 2, 3, 4)] == [
        "user_message", "assistant_message", "tool_result", "tool_call"]


def test_convert_renumbers_seq_per_session_and_keeps_source_seq(tmp_path: Path, src: Path):
    """包内 seq 是会话内 1..n（校验器要求）；源全局 seq 进 extra 不丢。"""
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert by_key["sB:1"]["seq"] == 1
    assert by_key["sB:1"]["extra"]["source_seq"] == 5


def test_convert_keeps_reasoning_as_text(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")

    assistant = _records(out)["sA:2"]
    assert assistant["reasoning_state"] == "text"
    assert assistant["reasoning_text"] == "想一想"


def test_convert_reports_no_loss_for_this_source(tmp_path: Path, src: Path):
    """这支转换器把每列都放进了契约或 extra，因此"无损"是可验证的承诺。"""
    out = tmp_path / "bundle"
    manifest = convert(src, out, agent_name="imported")

    assert manifest.dropped == ()
    assert manifest.counts == {"transcripts": 5, "memories": 0, "relations": 0}


def test_convert_declares_unmapped_columns(tmp_path: Path, src: Path):
    """源里出现契约与 extra 都接不住的列时，必须申报条数而不是丢掉。"""
    conn = sqlite3.connect(src)
    conn.execute("ALTER TABLE conversation_history ADD COLUMN dream_state TEXT")
    conn.execute("UPDATE conversation_history SET dream_state = 'active'")
    conn.commit()
    conn.close()
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")

    assert any(entry["field"] == "dream_state" and entry["count"] == 5
               and entry["reason"] for entry in manifest.dropped)


def test_convert_declares_unknown_kind_rows(tmp_path: Path, src: Path):
    """认不出的 kind 不猜映射：整行不入包，但必须在申报里数得出来。"""
    conn = sqlite3.connect(src)
    conn.execute(
        "INSERT INTO conversation_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        _row(seq=6, session_id="sA", kind="dream_turn", role="assistant", content="?",
             created_at="2026-05-01T10:00:05", dedup_key="k6"))
    conn.commit()
    conn.close()
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")

    assert any(entry["field"] == "kind:dream_turn" and entry["count"] == 1
               for entry in manifest.dropped)
    assert manifest.counts["transcripts"] == 5
    assert validate_bundle(out) == []


def test_convert_is_read_only_on_source(tmp_path: Path, src: Path):
    before = src.read_bytes()

    convert(src, tmp_path / "bundle", agent_name="imported")

    assert src.read_bytes() == before
