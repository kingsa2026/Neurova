# -*- coding: utf-8 -*-
"""Ingest Bundle 记录类型与 manifest：版本不符与字段缺失都必须挡住（设计 §2 取证 3）。"""
import json
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.manifest import BundleError, load_manifest
from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord

GOOD_MANIFEST = {
    "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
    "agent_name": "imported", "source": {"converter": "x", "version": "1"},
    "counts": {"transcripts": 1, "memories": 1, "relations": 0},
    "dropped": [], "stores": [],
}


def test_load_manifest_reads_fields(tmp_path: Path):
    (tmp_path / "manifest.json").write_text(json.dumps(GOOD_MANIFEST), encoding="utf-8")

    manifest = load_manifest(tmp_path / "manifest.json")

    assert manifest.schema_version == 1 and manifest.agent_name == "imported"
    assert manifest.counts == {"transcripts": 1, "memories": 1, "relations": 0}


def test_load_manifest_rejects_unknown_version(tmp_path: Path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(dict(GOOD_MANIFEST, schema_version=99)), encoding="utf-8")

    with pytest.raises(BundleError, match="schema_version"):
        load_manifest(tmp_path / "manifest.json")


def test_load_manifest_rejects_missing_counts(tmp_path: Path):
    broken = {k: v for k, v in GOOD_MANIFEST.items() if k != "counts"}
    (tmp_path / "manifest.json").write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(BundleError, match="counts"):
        load_manifest(tmp_path / "manifest.json")


def test_transcript_to_session_message_keeps_roles_and_identity():
    """工具调用与结果必须各自成行（各家无一家内嵌，设计 §2 取证 1）。

    工具字段还要落进 metadata.ingest：读取模型 SessionMessage 只带 4 个字段，
    只写顶层会落盘成功但读不出来。
    """
    rec = TranscriptRecord(
        session_id="s1", seq=3, kind="tool_result", ts="2026-05-01T10:00:00+00:00",
        identity_key="ik3", role="tool", tool_call_id="tc1", tool_name="fs_read",
        tool_state="ok", content_blocks=({"type": "text", "text": "结果正文"},),
    )

    msg = rec.to_session_message()

    assert msg["role"] == "tool" and msg["tool_call_id"] == "tc1" and msg["tool_state"] == "ok"
    assert msg["content"] == "结果正文"
    ingest = msg["metadata"]["ingest"]
    assert ingest["identity_key"] == "ik3" and ingest["tool_call_id"] == "tc1"
    assert ingest["tool_name"] == "fs_read" and ingest["tool_state"] == "ok"


def test_transcript_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        TranscriptRecord(session_id="s", seq=1, kind="weird", ts="t", identity_key="k")


def test_reasoning_text_lands_in_metadata():
    rec = TranscriptRecord(session_id="s1", seq=2, kind="assistant_message",
                           ts="2026-05-01T10:00:00+00:00", identity_key="ik2",
                           reasoning_state="text", reasoning_text="想一想")

    msg = rec.to_session_message()

    assert msg["metadata"]["ingest"]["reasoning_state"] == "text"
    assert msg["metadata"]["reasoning_content"] == "想一想"


def test_memory_record_defaults_keep_history_temperature():
    rec = MemoryRecord(identity_key="m1", content="c", memory_type="semantic",
                       category="general", origin="owner", importance=50.0,
                       ts="2026-05-01T10:00:00+00:00")

    assert rec.temperature == 100.0 and rec.origin == "owner" and rec.tags == ()
