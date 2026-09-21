# -*- coding: utf-8 -*-
"""opencode 会话族（opencode.db）→ Ingest Bundle。

取证自本机真实库（4 场会话 / 845 消息 / 4423 块）：一次助手轮的内容散在 part 表的
data JSON 里（text / reasoning / tool / step-start / step-finish / patch / compaction /
file），而 tool 块把**调用与结果放在同一个 state** 里（state.input / state.output，
失败时 state.error）。所以一支块要展开成两条包内事件，靠 callID 关联——这正是别家互导
最容易丢的地方。

时间口径：源里是 epoch 毫秒（绝对时刻，无本地语义），统一按 UTC 定标，日期分桶因此稳定可复现。
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from neurova.memory_ingest.bundle.manifest import BundleError
from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.converters.opencode_session import CONVERTER_NAME, convert
from neurova.memory_ingest.probe import probe_store

EPOCH = 1787791388521          # 真实库里第一条消息的毫秒值


def _data(**kw: Any) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, title TEXT,"
                 " directory TEXT, model TEXT, agent TEXT, cost REAL, time_created INTEGER)")
    conn.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,"
                 " time_created INTEGER, time_updated INTEGER, data TEXT)")
    conn.execute("CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,"
                 " time_created INTEGER, time_updated INTEGER, data TEXT)")
    conn.execute("CREATE TABLE todo (session_id TEXT, content TEXT, status TEXT,"
                 " priority TEXT, position INTEGER)")
    conn.execute("INSERT INTO session VALUES ('ses_1', NULL, 'New session', '/w',"
                 " '{\"id\":\"qwen/x\"}', 'build', 0.42, ?)", (EPOCH,))
    rows = [
        ("msg_u1", "ses_1", EPOCH, _data(role="user", time={"created": EPOCH}, agent="build")),
        ("msg_a1", "ses_1", EPOCH + 1000,
         _data(role="assistant", time={"created": EPOCH + 1000, "completed": EPOCH + 9000},
               modelID="qwen/x", providerID="pc", cost=0.42, agent="build", finish="stop",
               path="/w", tokens={"input": 11, "output": 7, "reasoning": 2})),
    ]
    conn.executemany("INSERT INTO message VALUES (?,?,?,0,?)",
                     [(i, s, t, d) for i, s, t, d in rows])
    parts = [
        ("prt_1", "msg_u1", EPOCH, _data(type="text", text="跑一下", time={"created": EPOCH})),
        ("prt_2", "msg_a1", EPOCH + 1100, _data(type="step-start", snapshot="abc")),
        ("prt_3", "msg_a1", EPOCH + 1200, _data(type="reasoning", text="先想",
                                                 time={"created": EPOCH + 1200})),
        ("prt_4", "msg_a1", EPOCH + 1300, _data(type="text", text="我读一下",
                                                 time={"created": EPOCH + 1300})),
        ("prt_5", "msg_a1", EPOCH + 1400,
         _data(type="tool", callID="call_1", tool="read",
               state={"status": "completed", "input": {"path": "A.md"}, "output": "内容A",
                      "title": "read A.md", "metadata": {"m": 1}, "time": {"start": 1, "end": 2}})),
        ("prt_6", "msg_a1", EPOCH + 1500,
         _data(type="tool", callID="call_2", tool="shell",
               state={"status": "error", "input": {"cmd": "x"}, "error": "boom",
                      "time": {"start": 3, "end": 4}})),
        ("prt_7", "msg_a1", EPOCH + 1600,
         _data(type="step-finish", reason="end_turn", cost=0.4, tokens={"input": 11},
               snapshot="def")),
        ("prt_8", "msg_a1", EPOCH + 1700, _data(type="patch", hash="h1", files=["A.md", "B.md"])),
        ("prt_9", "msg_a1", EPOCH + 1800,
         _data(type="compaction", auto=True, overflow=False, tail_start_id="msg_u1")),
        ("prt_10", "msg_a1", EPOCH + 1900,
         _data(type="file", filename="shot.png", mime="image/png",
               url="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
                   "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")),
    ]
    conn.executemany("INSERT INTO part VALUES (?,?,?,?,0,?)",
                     [(i, m, "ses_1", t, d) for i, m, t, d in parts])
    conn.execute("INSERT INTO todo VALUES ('ses_1', '补测试', 'pending', 'medium', 0)")
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def src(tmp_path: Path) -> Path:
    return _db(tmp_path / "opencode.db")


def _mini_db(tmp_path: Path, messages, parts) -> Path:
    """自定内容的最小库：本任务要的两种形状（只有思考块 / 思考后接 user）在固定夹具里没有。"""
    path = tmp_path / "mini.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, title TEXT,"
                 " directory TEXT, model TEXT, agent TEXT, cost REAL, time_created INTEGER)")
    conn.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,"
                 " time_created INTEGER, time_updated INTEGER, data TEXT)")
    conn.execute("CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,"
                 " time_created INTEGER, time_updated INTEGER, data TEXT)")
    conn.execute("INSERT INTO session VALUES ('s1', NULL, '标题', '/w', '{}', 'build', 0, ?)",
                 (EPOCH,))
    conn.executemany("INSERT INTO message VALUES (?,?,?,0,?)",
                     [(mid, "s1", at, _data(role=role)) for mid, role, at in messages])
    conn.executemany("INSERT INTO part VALUES (?,?,?,?,0,?)",
                     [(pid, mid, "s1", at, _data(**body)) for pid, mid, body, at in parts])
    conn.commit()
    conn.close()
    return path


def test_reasoning_only_session_converts_without_crash(tmp_path: Path):
    """只有思考块的一场会话：转得出包，不是一句 IndexError。"""
    out = tmp_path / "bundle"

    manifest = convert(_mini_db(tmp_path, [("m1", "assistant", 100)],
                                [("p1", "m1", {"type": "reasoning", "text": "只想了一下"}, 100)]),
                       out, agent_name="imported")

    assert validate_bundle(out) == []
    assert manifest.counts["transcripts"] == 1
    record = list(_records(out)[0].values())[0]
    assert record["kind"] == "assistant_message" and record["reasoning_state"] == "text"


def test_thinking_does_not_bleed_into_next_message(tmp_path: Path):
    """上一轮没人接的思考不能挂到下一条（可能是 user）头上。"""
    out = tmp_path / "bundle"
    convert(_mini_db(tmp_path,
                     [("m1", "assistant", 100), ("m2", "user", 200)],
                     [("p1", "m1", {"type": "reasoning", "text": "思考"}, 100),
                      ("p2", "m2", {"type": "text", "text": "用户提问"}, 200)]),
            out, agent_name="imported")

    rows = list(_records(out)[0].values())
    user = next(r for r in rows if r["kind"] == "user_message")
    assert user.get("reasoning_state", "absent") == "absent"


def _records(out: Path) -> List[Dict[str, Any]]:
    rows = [json.loads(x) for x in (out / "transcripts.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    return {f"{r['identity_key']}": r for r in rows}, rows


def test_store_is_recognized_as_opencode(tmp_path: Path, src: Path):
    assert probe_store(src).hits == (CONVERTER_NAME,)


def test_convert_produces_valid_bundle(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")

    assert validate_bundle(out) == []


def test_tool_part_splits_into_call_and_result(tmp_path: Path, src: Path):
    """opencode 把调用与结果塞在同一块里：两条事件都要有，callID 要连得上。"""
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key, _ = _records(out)

    call = by_key["ses_1#prt_5#0"]
    result = by_key["ses_1#prt_5#1"]
    assert call["kind"] == "tool_call" and call["tool_name"] == "read"
    assert call["tool_call_id"] == result["tool_call_id"] == "call_1"
    assert json.loads(call["extra"]["tool_input"]) == {"path": "A.md"}
    assert call["tool_state"] == "completed"
    assert result["kind"] == "tool_result"
    assert result["content_blocks"][0]["text"] == "内容A"


def test_failed_tool_keeps_error_as_result(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key, _ = _records(out)

    result = by_key["ses_1#prt_6#1"]
    assert result["kind"] == "tool_result" and result["tool_state"] == "error"
    assert result["content_blocks"][0]["text"] == "boom"


def test_reasoning_and_text_order(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key, _ = _records(out)

    text = by_key["ses_1#prt_4"]
    assert text["kind"] == "assistant_message"
    assert text["content_blocks"][0]["text"] == "我读一下"
    assert text["reasoning_state"] == "text" and text["reasoning_text"] == "先想"


def test_message_level_metering_is_carried(tmp_path: Path, src: Path):
    """cost/tokens/model/agent 是源里的事实：挂在该消息**首条被携带**的事件上，
    不靠 step-finish 重复表达（步进记账因此只是记账，不是丢内容）。"""
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key, _ = _records(out)

    extra = by_key["ses_1#prt_4"]["extra"]
    assert extra["agent"] == "build" and extra["model_id"] == "qwen/x"
    assert extra["cost"] == 0.42 and extra["tokens"] == {"input": 11, "output": 7, "reasoning": 2}
    assert extra["finish"] == "stop"


def test_user_row_becomes_user_message(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key, _ = _records(out)

    user = by_key["ses_1#prt_1"]
    assert user["kind"] == "user_message" and user["role"] == "user"
    assert user["content_blocks"][0]["text"] == "跑一下"
    assert user["ts"].endswith("+00:00")


def test_compaction_marker_is_kept(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key, _ = _records(out)

    marker = by_key["ses_1#prt_9"]
    assert marker["kind"] == "compact_summary"
    assert marker["extra"]["tail_start_id"] == "msg_u1"


def test_file_part_lands_in_bundle_media(tmp_path: Path, src: Path):
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")
    by_key, _ = _records(out)
    block = by_key["ses_1#prt_10"]["content_blocks"][0]

    assert block["type"] == "file" and block["mime"] == "image/png"
    assert (out / block["media"]).read_bytes() == png
    assert not any(entry["field"] == "part:file" for entry in manifest.dropped)


def test_accounting_and_todolist_are_declared_not_silently_dropped(tmp_path: Path, src: Path):
    """步进记账与待办：包里没带，但条数与去处必须在报告里说清。"""
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")
    fields = {entry["field"]: entry for entry in manifest.dropped}

    assert fields["part:step-start"]["count"] == 1
    assert "message 级" in fields["part:step-finish"]["reason"]
    assert fields["part:patch"]["count"] == 1
    assert fields["table:todo"]["count"] == 1


def test_convert_refuses_foreign_store(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "other.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(BundleError):
        convert(tmp_path / "other.db", tmp_path / "bundle", agent_name="x")


def test_source_is_read_only(tmp_path: Path, src: Path):
    before = src.read_bytes()

    convert(src, tmp_path / "bundle", agent_name="x")

    assert src.read_bytes() == before


def test_is_routable_by_handprint_name():
    assert CONVERTERS[CONVERTER_NAME] is convert
