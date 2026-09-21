# -*- coding: utf-8 -*-
"""会话 JSONL 族（每日对话 + 1.x 工作区会话）→ Ingest Bundle。

这两族是"三源等价并入"里剩下两源。它们没有会话表，一个文件就是一场会话：会话号取自
文件名，行内没有全局 seq，所以顺序靠源时间戳。时区口径按族固定（每日对话是本地裸时间，
1.x 会话是 UTC Z），换算只挪时区不改时刻——现脚本也是这个口径，等价验收才可比。
"""
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from neurova.memory_ingest.bundle.manifest import BundleError
from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.converters.dialog_daily import CONVERTER_NAME as DIALOG
from neurova.memory_ingest.converters.dialog_daily import convert as convert_dialog
from neurova.memory_ingest.converters.legacy_session import CONVERTER_NAME as LEGACY
from neurova.memory_ingest.converters.legacy_session import convert as convert_legacy
from neurova.memory_ingest.bundle.records import TranscriptRecord
from neurova.memory_ingest.bundle.turns import to_turn_messages
from neurova.memory_ingest.probe import probe_store

DOCX = b"PK" + bytes([0x03, 0x04]) + b"docx-payload"


def _jsonl(path: Path, *lines: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
                    encoding="utf-8")
    return path


def _dialog_line(role: str, content: Any, ts: str, **kw: Any) -> Dict[str, Any]:
    return {"role": role, "name": kw.get("name", role), "content": content,
            "timestamp": ts, "id": kw.get("id"), "metadata": kw.get("metadata"),
            **({"extra": kw["extra"]} if "extra" in kw else {})}


def _legacy_line(role: str, content: Any, ts: str) -> Dict[str, Any]:
    return {"type": "message", "message": {"role": role, "content": content,
                                           "timestamp": ts}, "timestamp": ts, "id": f"m{ts}"}



def test_unmapped_role_declared_as_role_not_empty_body(tmp_path: Path):
    """报告不能把"不认这个角色"说成"这行没内容"——接第二家时正是这个形状。"""
    src = _jsonl(tmp_path / "dialog" / "2026-04-07.jsonl",
                 _dialog_line("developer", [{"type": "text", "text": "指令"}],
                              "2026-04-07 17:36:13"))

    manifest = convert_dialog(src, tmp_path / "bundle", agent_name="imported")
    fields = {e["field"] for e in manifest.dropped}

    assert "role:developer" in fields
    assert "空正文" not in fields


def test_both_families_are_recognized_by_structure(tmp_path: Path):
    dialog = _jsonl(tmp_path / "dialog" / "2026-04-07.jsonl",
                    _dialog_line("user", [{"type": "text", "text": "问题"}],
                                 "2026-04-07 17:36:13.258"))
    legacy = _jsonl(tmp_path / "sessions" / "0239e765.jsonl",
                    _legacy_line("user", [{"type": "text", "text": "问题"}],
                                 "2026-04-06T18:06:20.520Z"))

    assert probe_store(dialog).hits == (DIALOG,)
    assert probe_store(legacy).hits == (LEGACY,)


def test_dialog_converts_with_local_day_session_and_offset(tmp_path: Path):
    src = _jsonl(tmp_path / "dialog" / "2026-04-07.jsonl",
                 _dialog_line("user", [{"type": "text", "text": "问题"}], "2026-04-07 17:36:13"),
                 _dialog_line("assistant", [{"type": "thinking", "thinking": "想"},
                                            {"type": "text", "text": "回答"}],
                              "2026-04-07 17:36:16", name="Friday"))
    out = tmp_path / "bundle"

    manifest = convert_dialog(src, out, agent_name="imported")
    rows = _rows(out)

    assert validate_bundle(out) == []
    assert manifest.counts["transcripts"] == 2
    assert {r["session_id"] for r in rows} == {"dialog-2026-04-07"}
    assert rows[0]["kind"] == "user_message" and rows[0]["role"] == "user"
    assert rows[0]["ts"] == "2026-04-07T17:36:13+08:00"      # 裸时间按源本地时区定标
    assert rows[1]["content_blocks"][0]["text"] == "回答"
    assert rows[1]["reasoning_state"] == "text" and rows[1]["reasoning_text"] == "想"
    assert rows[1]["extra"]["actor_name"] == "Friday"


def test_legacy_converts_utc_to_same_instant_with_offset(tmp_path: Path):
    src = _jsonl(tmp_path / "sessions" / "0239e765.jsonl",
                 _legacy_line("user", "纯字符串正文", "2026-04-06T18:06:20.520Z"),
                 _legacy_line("assistant", [{"type": "toolCall", "name": "read_file",
                                             "arguments": {"file_path": "A.md"}}],
                              "2026-04-06T18:06:31.000Z"))
    out = tmp_path / "bundle"

    manifest = convert_legacy(src, out, agent_name="imported")
    rows = _rows(out)

    assert validate_bundle(out) == []
    assert {r["session_id"] for r in rows} == {"0239e765"}
    assert rows[0]["content_blocks"][0]["text"] == "纯字符串正文"
    assert rows[0]["ts"] == "2026-04-07T02:06:20.520000+08:00"   # 同一时刻换区
    assert rows[1]["kind"] == "tool_call" and rows[1]["tool_name"] == "read_file"
    assert json.loads(rows[1]["extra"]["tool_input"]) == {"file_path": "A.md"}
    assert manifest.counts["transcripts"] == 2


def test_non_message_records_are_declared_not_dropped_silently(tmp_path: Path):
    """1.x 文件里混着 model_change/custom 等记录：不认的不入包，但必须数得出来。"""
    src = _jsonl(tmp_path / "sessions" / "sub-1.jsonl",
                 _legacy_line("user", [{"type": "text", "text": "问题"}], "2026-04-06T18:00:00Z"),
                 {"type": "model_change", "modelId": "x", "timestamp": "2026-04-06T18:01:00Z"},
                 {"type": "message", "message": {"role": "system", "content": [],
                                                 "timestamp": "2026-04-06T18:02:00Z"},
                  "timestamp": "2026-04-06T18:02:00Z"})
    out = tmp_path / "bundle"

    manifest = convert_legacy(src, out, agent_name="imported")

    assert manifest.counts["transcripts"] == 1
    fields = {entry["field"]: entry["count"] for entry in manifest.dropped}
    assert fields["type:model_change"] == 1 and fields["role:system"] == 1


def test_broken_lines_and_unknown_blocks_are_declared(tmp_path: Path):
    src = tmp_path / "dialog" / "2026-04-08.jsonl"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(json.dumps(_dialog_line("user", [{"type": "text", "text": "甲"}],
                                           "2026-04-08 10:00:00"), ensure_ascii=False)
                   + "\n{oops\n"
                   + json.dumps(_dialog_line("assistant", [{"type": "audio", "url": "x"}],
                                             "2026-04-08 10:01:00"), ensure_ascii=False) + "\n",
                   encoding="utf-8")
    out = tmp_path / "bundle"

    manifest = convert_dialog(src, out, agent_name="imported")
    fields = {entry["field"]: entry["count"] for entry in manifest.dropped}

    assert fields["坏行"] == 1
    assert fields["blocks:audio"] == 1
    assert validate_bundle(out) == []


def test_unparsable_timestamp_is_declared(tmp_path: Path):
    src = _jsonl(tmp_path / "dialog" / "2026-04-09.jsonl",
                 _dialog_line("user", [{"type": "text", "text": "甲"}], "不是时间"),
                 _dialog_line("assistant", [{"type": "text", "text": "乙"}],
                              "2026-04-09 11:00:00"))
    out = tmp_path / "bundle"

    manifest = convert_dialog(src, out, agent_name="imported")

    assert any(entry["field"] == "timestamp" and entry["count"] == 1 and "顺序" in entry["reason"]
               for entry in manifest.dropped)
    assert manifest.counts["transcripts"] == 1     # 排不了序的行不猜位置


def test_source_files_are_never_written(tmp_path: Path):
    dialog = _jsonl(tmp_path / "dialog" / "2026-04-07.jsonl",
                    _dialog_line("user", [{"type": "text", "text": "甲"}], "2026-04-07 10:00:00"))
    legacy = _jsonl(tmp_path / "sessions" / "s1.jsonl",
                    _legacy_line("user", [{"type": "text", "text": "甲"}], "2026-04-07T02:00:00Z"))
    before = (dialog.read_bytes(), legacy.read_bytes())

    convert_dialog(dialog, tmp_path / "b1", agent_name="x")
    convert_legacy(legacy, tmp_path / "b2", agent_name="x")

    assert (dialog.read_bytes(), legacy.read_bytes()) == before


def test_converters_refuse_foreign_stores(tmp_path: Path):
    foreign = _jsonl(tmp_path / "dialog" / "2026-04-07.jsonl",
                     _legacy_line("user", [{"type": "text", "text": "甲"}],
                                  "2026-04-07T02:00:00Z"))

    with pytest.raises(BundleError):
        convert_dialog(foreign, tmp_path / "b", agent_name="x")


def test_both_are_routable_by_handprint_name():
    assert CONVERTERS[DIALOG] is convert_dialog and CONVERTERS[LEGACY] is convert_legacy


def test_header_first_log_is_recognized_and_header_declared(tmp_path: Path):
    """实测 31/31 个真实文件以表头记录开头：只看首行的指纹永远认不出它，表头本身要申报。"""
    src = _jsonl(tmp_path / "sessions" / "s9.jsonl",
                 {"type": "session", "cwd": "/w", "id": "h1", "version": 2,
                  "timestamp": "2026-04-06T18:00:00Z"},
                 _legacy_line("user", [{"type": "text", "text": "问题"}], "2026-04-06T18:00:10Z"))

    assert probe_store(src).hits == (LEGACY,)
    manifest = convert_legacy(src, tmp_path / "bundle", agent_name="x")

    fields = {entry["field"]: entry["count"] for entry in manifest.dropped}
    assert fields["type:session"] == 1
    assert manifest.counts["transcripts"] == 1


def test_dialog_tool_use_and_carried_results_are_linked(tmp_path: Path):
    """实测每日对话把结果寄在 system 行的 tool_result 块里：调用与结果必须配得回去。"""
    call = {"type": "tool_use", "id": "tc1", "name": "memory_search",
            "input": {"query": "最近修改记录"}}
    result = {"type": "tool_result", "id": "tc1", "name": "memory_search",
              "output": [{"type": "text", "text": "[]"}]}
    src = _jsonl(tmp_path / "dialog" / "2026-04-10.jsonl",
                 _dialog_line("user", [{"type": "text", "text": "查一下"}], "2026-04-10 09:00:00"),
                 _dialog_line("assistant", [{"type": "text", "text": "我搜"}, call],
                              "2026-04-10 09:00:05"),
                 _dialog_line("system", [result], "2026-04-10 09:00:07"))

    manifest = convert_dialog(src, tmp_path / "bundle", agent_name="imported")
    rows = _rows(tmp_path / "bundle")

    assert validate_bundle(tmp_path / "bundle") == []
    assert [r["kind"] for r in rows] == ["user_message", "assistant_message", "tool_call",
                                         "tool_result"]
    assert json.loads(rows[2]["extra"]["tool_input"]) == {"query": "最近修改记录"}
    assert rows[3]["tool_call_id"] == "tc1" and rows[3]["content_blocks"][0]["text"] == "[]"
    assert not any(entry["field"].startswith("role:") for entry in manifest.dropped)

    turn = to_turn_messages([TranscriptRecord(**r) for r in rows])[1]
    entries = turn["metadata"]["tool_calls"]
    assert [e["type"] for e in entries] == ["tool_call", "tool_result"]
    assert entries[1]["result"] == "[]"


def test_legacy_tool_result_rows_become_tool_results(tmp_path: Path):
    """实测 1.x 把结果作为 role=toolResult 的独立行：带 toolCallId 与 toolName。"""
    src = _jsonl(tmp_path / "sessions" / "s5.jsonl",
                 _legacy_line("user", [{"type": "text", "text": "读文件"}],
                              "2026-04-06T18:00:00Z"),
                 {"type": "message", "id": "r1", "timestamp": "2026-04-06T18:00:09Z",
                  "message": {"role": "toolResult", "toolCallId": "read:0", "toolName": "read",
                              "content": [{"type": "text", "text": "# SOUL.md"}]}})

    manifest = convert_legacy(src, tmp_path / "bundle", agent_name="imported")
    rows = _rows(tmp_path / "bundle")

    assert manifest.counts["transcripts"] == 2
    assert rows[1]["kind"] == "tool_result"
    assert rows[1]["tool_call_id"] == "read:0" and rows[1]["tool_name"] == "read"
    assert rows[1]["content_blocks"][0]["text"] == "# SOUL.md"


def test_rows_sharing_a_source_id_do_not_collide(tmp_path: Path):
    """实测 19/40 个每日对话文件里调用行与它的 system 结果行共用一个 id：
    拿源 id 当幂等键会整包判重被拒，一个都导不进来。"""
    src = _jsonl(tmp_path / "dialog" / "2026-04-19.jsonl",
                 _dialog_line("assistant", [{"type": "tool_use", "id": "tc1", "name": "t",
                                             "input": {}}], "2026-04-19 09:00:00",
                              id="msg_shared"),
                 _dialog_line("system", [{"type": "tool_result", "id": "tc1", "name": "t",
                                          "output": [{"type": "text", "text": "结果"}]}],
                              "2026-04-19 09:00:01", id="msg_shared"))

    manifest = convert_dialog(src, tmp_path / "bundle", agent_name="imported")

    assert validate_bundle(tmp_path / "bundle") == []
    assert manifest.counts["transcripts"] == 2
    rows = _rows(tmp_path / "bundle")
    assert len({r["identity_key"] for r in rows}) == 2
    assert {r["extra"]["source_id"] for r in rows} == {"msg_shared"}


def test_path_form_media_is_copied_from_the_source_tree(tmp_path: Path):
    """源里的绝对路径属于另一台机器：在源目录树 media/ 下按同名找到就搬进包。"""
    (tmp_path / "workspace" / "media").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / "media" / "plan.docx").write_bytes(DOCX)
    src = _jsonl(tmp_path / "workspace" / "dialog" / "2026-04-11.jsonl",
                 _dialog_line("user", [{"type": "text", "text": "看方案"},
                                       {"type": "file", "source": "/agents/Kai/workspace/media/plan.docx",
                                        "filename": "plan.docx"}], "2026-04-11 09:00:00"))

    manifest = convert_dialog(src, tmp_path / "bundle", agent_name="imported")
    block = _rows(tmp_path / "bundle")[0]["content_blocks"][1]

    assert manifest.dropped == ()
    assert (tmp_path / "bundle" / block["media"]).read_bytes() == DOCX
    assert block["name"] == "plan.docx"


def test_image_block_lands_in_bundle_media(tmp_path: Path):
    """图片不再是"申报了事"：块落进包内 media/，记录里只留内容寻址引用。"""
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
                           "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    src = _jsonl(tmp_path / "dialog" / "2026-04-12.jsonl",
                 _dialog_line("user", [{"type": "text", "text": "看图"},
                                       {"type": "image",
                                        "source": {"type": "base64",
                                                   "data": base64.b64encode(png).decode()}}],
                              "2026-04-12 09:00:00"))

    manifest = convert_dialog(src, tmp_path / "bundle", agent_name="imported")
    rows = _rows(tmp_path / "bundle")

    blocks = rows[0]["content_blocks"]
    assert blocks[0]["text"] == "看图"
    assert blocks[1]["type"] == "image" and blocks[1]["mime"] == "image/png"
    assert (tmp_path / "bundle" / blocks[1]["media"]).read_bytes() == png
    assert not any(entry["field"].startswith("blocks:image") for entry in manifest.dropped)


def test_unreachable_file_block_is_declared(tmp_path: Path):
    """源里的绝对路径属于另一台机器：只在源树 media/ 下按同名找，找不到就申报。"""
    src = _jsonl(tmp_path / "workspace" / "dialog" / "2026-04-13.jsonl",
                 _dialog_line("user", [{"type": "file",
                                        "source": "/agents/Kai/workspace/media/没了.docx",
                                        "filename": "没了.docx"}], "2026-04-13 09:00:00"))

    manifest = convert_dialog(src, tmp_path / "bundle", agent_name="imported")
    fields = {entry["field"]: entry["count"] for entry in manifest.dropped}

    assert fields["media:不可达"] == 1 and manifest.counts["transcripts"] == 0


def _rows(out: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in (out / "transcripts.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
