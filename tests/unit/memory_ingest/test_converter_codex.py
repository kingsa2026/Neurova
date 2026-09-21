# -*- coding: utf-8 -*-
"""Codex rollout 族转换器：字段取自该平台写入侧枚举，不靠样例文件猜。

这族最容易出事的两处：调用与结果本来就是两条线（call_id 关联），以及推理正文可能是
密文（encrypted_content）——密文必须显式标 opaque，不能写成"没有推理"。
"""
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from neurova.memory_ingest.bundle.manifest import BundleError
from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.converters.codex_rollout import CONVERTER_NAME, convert
from neurova.memory_ingest.probe import probe_store

META = {"type": "session_meta", "payload": {"id": "thr_7", "timestamp": "2026-05-01T10:00:00Z",
                                            "cwd": "/w", "model": "gpt-x", "cli_version": "0.9"}}


def _line(payload: Dict[str, Any], rtype: str = "response_item") -> str:
    return json.dumps({"type": rtype, "payload": payload}, ensure_ascii=False)


def _rollout(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "sessions" / "2026" / "05" / "01" / "rollout-2026-05-01T10-00-00-thr_7.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([json.dumps(META, ensure_ascii=False), *lines]) + "\n",
                    encoding="utf-8")
    return path


def _records(out: Path) -> Dict[str, Dict[str, Any]]:
    rows = [json.loads(x) for x in (out / "transcripts.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    return {r["identity_key"]: r for r in rows}


def test_store_is_recognized_and_others_are_not(tmp_path: Path):
    src = _rollout(tmp_path, _line({"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": "跑一下"}]}))

    assert probe_store(src).hits == (CONVERTER_NAME,)


def test_converts_to_valid_bundle(tmp_path: Path):
    src = _rollout(tmp_path, _line({"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": "跑一下"}]}))
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")

    assert validate_bundle(out) == []


def test_call_and_result_lines_keep_their_linkage(tmp_path: Path):
    src = _rollout(tmp_path,
                   _line({"type": "message", "role": "user",
                          "content": [{"type": "input_text", "text": "读A"}]}),
                   _line({"type": "function_call", "call_id": "c1", "name": "shell",
                          "arguments": "{\"cmd\":\"ls\"}"}),
                   _line({"type": "function_call_output", "call_id": "c1",
                          "output": [{"type": "input_text", "text": "a.txt"}]}))
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")
    by_key = _records(out)

    kinds = [r["kind"] for r in by_key.values()]
    assert kinds == ["user_message", "tool_call", "tool_result"]
    call = next(r for r in by_key.values() if r["kind"] == "tool_call")
    result = next(r for r in by_key.values() if r["kind"] == "tool_result")
    assert call["tool_call_id"] == result["tool_call_id"] == "c1"
    assert call["extra"]["tool_input"] == "{\"cmd\":\"ls\"}"      # 参数原样带走，不猜解析
    assert result["content_blocks"][0]["text"] == "a.txt"


def test_encrypted_reasoning_is_marked_opaque(tmp_path: Path):
    src = _rollout(tmp_path,
                   _line({"type": "reasoning", "summary": [], "id": "r1",
                          "encrypted_content": "gAAAASmv..."}),
                   _line({"type": "message", "role": "assistant",
                          "content": [{"type": "output_text", "text": "做完了"}]}))
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")
    assistant = next(r for r in _records(out).values() if r["kind"] == "assistant_message")

    assert assistant["reasoning_state"] == "opaque"
    assert assistant.get("reasoning_text", "") == ""


def test_plain_reasoning_summary_attaches_to_next_message(tmp_path: Path):
    src = _rollout(tmp_path,
                   _line({"type": "reasoning",
                          "summary": [{"type": "summary_text", "text": "先看目录"}]}),
                   _line({"type": "message", "role": "assistant",
                          "content": [{"type": "output_text", "text": "在 /w"}]}))
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")
    assistant = next(r for r in _records(out).values() if r["kind"] == "assistant_message")

    assert assistant["reasoning_state"] == "text" and assistant["reasoning_text"] == "先看目录"


def test_developer_role_and_image_and_compaction(tmp_path: Path):
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    src = _rollout(tmp_path,
                   _line({"type": "message", "role": "developer",
                          "content": [{"type": "input_text", "text": "系统约定"}]}),
                   _line({"type": "message", "role": "user",
                          "content": [{"type": "input_text", "text": "看这张"},
                                      {"type": "input_image",
                                       "image_url": "data:image/png;base64,"
                                       + base64.b64encode(png).decode()}]}),
                   _line({"replaced": 3, "message": "上下文已压缩"}, rtype="compacted"))
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert [r["kind"] for r in by_key.values()] == ["system", "user_message", "compact_summary"]
    blocks = by_key["thr_7#L3"]["content_blocks"]
    assert blocks[1]["type"] == "image" and (out / blocks[1]["media"]).read_bytes() == png
    assert manifest.dropped == ()


def test_bookkeeping_lines_are_declared_with_counts(tmp_path: Path):
    src = _rollout(tmp_path,
                   _line({"turn_id": "t1", "model": "gpt-x"}, rtype="turn_context"),
                   _line({"info": {"total_token_usage": {}}}, rtype="token_usage_record"),
                   _line({"type": "user_message", "message": "跑一下"}, rtype="event_msg"),
                   _line({"type": "web_search_call", "call_id": "w1"}),
                   "not-json")
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")
    fields = {entry["field"]: entry for entry in manifest.dropped}

    assert fields["payload:turn_context"]["count"] == 1
    assert fields["payload:token_usage_record"]["count"] == 1
    assert fields["event_msg"]["count"] == 1 and "response_item" in fields["event_msg"]["reason"]
    assert fields["payload:web_search_call"]["count"] == 1
    assert fields["坏行"]["count"] == 1
    assert manifest.counts["transcripts"] == 0


def test_source_meta_is_carried_once(tmp_path: Path):
    src = _rollout(tmp_path, _line({"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": "甲"}]}))
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")

    first = next(iter(_records(out).values()))
    assert first["extra"]["session_meta"]["cwd"] == "/w"
    assert first["ts"].endswith("+00:00")


def test_refuses_foreign_store(tmp_path: Path):
    other = tmp_path / "notes.jsonl"
    other.write_text(json.dumps({"role": "user", "content": []}) + "\n", encoding="utf-8")

    with pytest.raises(BundleError):
        convert(other, tmp_path / "bundle", agent_name="x")


def test_line_without_any_time_is_declared_not_stamped(tmp_path: Path):
    """没有 per-line 时间、session_meta 也没给时间：报 timestamp，不盖今天的章。"""
    path = tmp_path / "sessions" / "rollout-2026-05-01T10-00-00-thr_9.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": "thr_9"}}),
        _line({"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": "跑一下"}]}),
    ]) + "\n", encoding="utf-8")
    out = tmp_path / "bundle"

    manifest = convert(path, out, agent_name="imported")

    assert manifest.counts["transcripts"] == 0
    assert any(e["field"] == "timestamp" and e["count"] == 1 for e in manifest.dropped)


def test_is_routable_by_handprint_name():
    assert CONVERTERS[CONVERTER_NAME] is convert
