# -*- coding: utf-8 -*-
"""转换器共用的落包机制：事件 → 带会话内 seq 的记录 → 包目录。

三家转换器要的只是"源方言 → 事件"这一段，编号/幂等键/manifest 落盘是同一套规则；
留在各模块里各写一份，规则就会在第二家开始漂移（包内 seq 是否连续、identity_key
追加序号的方式等等）。
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord
from neurova.memory_ingest.bundle.writer import (SourceEvent, dropped_entries, ensure_offset,
                                                 materialize, write_bundle)


def _memory(**kw):
    return MemoryRecord(identity_key=kw.pop("identity_key", "mem#1"),
                        content=kw.pop("content", "事实正文"),
                        memory_type=kw.pop("memory_type", "semantic"),
                        category=kw.pop("category", "knowledge"),
                        origin=kw.pop("origin", "owner"),
                        importance=kw.pop("importance", 70.0),
                        ts=kw.pop("ts", "2026-05-01T10:00:00+00:00"), **kw)


def _event(kind="assistant_message", seq_ts="2026-05-01T10:00:00+00:00", **kw):
    return SourceEvent(kind=kind, ts=kw.pop("ts", seq_ts), **kw)


def test_ensure_offset_never_invents_now():
    """空与解不开都必须回空串：造一个 now() 会把六个月前的事写进今天的会话文件。"""
    assert ensure_offset("") == ""
    assert ensure_offset("不是时间") == ""
    assert ensure_offset("2026-05-01T10:00:00") == "2026-05-01T10:00:00+00:00"


def test_dropped_entries_single_shape():
    """申报只有一种形状：字段名原样带出，原因按整名/前缀查，查不到用本族兜底文案。"""
    entries = dropped_entries(Counter({"role:developer": 2, "media:不可达": 1}),
                              {"role": "该角色无对应 kind", "media": "取不到字节",
                               "__fallback__": "无落点"})

    assert entries == [{"field": "media:不可达", "count": 1, "reason": "取不到字节"},
                       {"field": "role:developer", "count": 2, "reason": "该角色无对应 kind"}]


def test_materialize_numbers_each_session_from_one():
    groups = [("sA", [("sA#1", [_event(text="甲"), _event(kind="tool_call", text="")])]),
              ("sB", [("sB#9", [_event(text="乙")])])]

    records = materialize(groups)

    assert [(r.session_id, r.seq) for r in records] == [("sA", 1), ("sA", 2), ("sB", 1)]


def test_materialize_addresses_events_within_one_source_row():
    """一行展开多条时幂等键必须各自可寻址，否则二次导入互相吞。"""
    records = materialize([("sA", [("sA#k1", [_event(text="一"), _event(text="二")])])])

    assert [r.identity_key for r in records] == ["sA#k1#0", "sA#k1#1"]


def test_materialize_keeps_single_row_key_unsuffixed():
    """只有一条时不加后缀：与"行即事件"的源保持键稳定。"""
    records = materialize([("sA", [("sA#k1", [_event(text="一")])])])

    assert records[0].identity_key == "sA#k1"


def test_materialize_carries_role_verbatim():
    """role 源里给什么记什么；缺省由消息层按 kind 回落（两处各猜一次就会打架）。"""
    records = materialize([("sA", [("sA#1", [
        _event(kind="tool_call", tool_call_id="tc1", tool_name="read", tool_state="finished",
               extra={"tool_input": '{"a": 1}'}),
        _event(role="user", text="提问")])])])

    assert records[0].tool_call_id == "tc1"
    assert records[0].extra == {"tool_input": '{"a": 1}'}
    assert records[0].reasoning_state == "absent"
    assert records[0].role == ""
    assert records[0].to_session_message()["role"] == "assistant"     # 消息层回落
    assert records[1].role == "user"


def test_materialize_attaches_media_blocks_after_the_text():
    """正文在前、媒体引用在后：顺序就是源块顺序，包内不做重排。"""
    ref = {"type": "image", "media": "media/abc.png", "digest": "abc", "bytes": 3,
           "name": "a.png", "mime": "image/png"}
    records = materialize([("sA", [("sA#1", [_event(text="看图", blocks=(ref,))])])])

    blocks = records[0].content_blocks
    assert [b["type"] for b in blocks] == ["text", "image"]
    assert blocks[1]["media"] == "media/abc.png"


def test_materialize_keeps_media_only_row():
    records = materialize([("sA", [("sA#1", [SourceEvent(
        kind="user_message", ts="2026-05-01T10:00:00+00:00", role="user",
        blocks=({"type": "file", "media": "media/x.bin", "digest": "x", "bytes": 1,
                 "name": "x.bin", "mime": "application/octet-stream"},))])])])

    assert records[0].text() == ""
    assert records[0].content_blocks[0]["type"] == "file"


def test_write_bundle_persists_manifest_records_and_declaration(tmp_path: Path):
    records = materialize([("sA", [("sA#1", [_event(text="正文", reasoning="在想")])])])
    out = tmp_path / "bundle"

    manifest = write_bundle(out, records, agent_name="imported",
                            source={"converter": "t", "version": "1"},
                            dropped=[{"field": "blocks:data", "count": 2, "reason": "无落点"}],
                            stores=[{"path": "x.db", "handprint": "t"}])

    assert manifest.counts == {"transcripts": 1, "memories": 0, "relations": 0}
    loaded = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert loaded["counts"] == manifest.counts and loaded["dropped"][0]["count"] == 2
    row = json.loads((out / "transcripts.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["content_blocks"] == [{"type": "text", "text": "正文"}]
    assert row["reasoning_state"] == "text"
    assert (out / "memories.jsonl").read_text(encoding="utf-8") == ""


def test_write_bundle_returns_the_same_records_it_wrote(tmp_path: Path):
    """落盘条数与返回计数必须相符——不符就是校验器要拦的那种半包。"""
    records = [TranscriptRecord(session_id="s", seq=1, kind="user_message",
                                ts="2026-05-01T00:00:00+00:00", identity_key="s#1",
                                role="user")]

    manifest = write_bundle(tmp_path / "b", records, agent_name="a",
                            source={}, dropped=[], stores=[])

    assert manifest.counts["transcripts"] == len(records)


def test_records_round_trip_through_the_dataclass(tmp_path: Path):
    """写出的行必须能被 TranscriptRecord(**row) 读回：intake 就是这么消费的。"""
    records = materialize([("sA", [("sA#1", [_event(text="甲", reasoning="思")])])])
    write_bundle(tmp_path / "b", records, agent_name="a", source={}, dropped=[], stores=[])

    row = json.loads((tmp_path / "b" / "transcripts.jsonl").read_text(
        encoding="utf-8").splitlines()[0])

    assert TranscriptRecord(**row) == records[0]


def test_write_bundle_lands_memory_rows_and_counts_them(tmp_path: Path):
    """会话与记忆是两支族：转换器给了记忆行，包里就不能仍是空的。"""
    out = tmp_path / "b"

    manifest = write_bundle(out, [], agent_name="a", source={}, dropped=[], stores=[],
                            memories=[_memory(), _memory(identity_key="mem#2", origin="agent")])

    assert manifest.counts == {"transcripts": 0, "memories": 2, "relations": 0}
    rows = [json.loads(x) for x in
            (out / "memories.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["identity_key"] for r in rows] == ["mem#1", "mem#2"]
    assert rows[1]["origin"] == "agent"


def test_memory_rows_round_trip_through_the_dataclass(tmp_path: Path):
    """intake 用 MemoryRecord(**row) 读回：list 与 tuple 不归一，幂等比对就会打架。"""
    out = tmp_path / "b"
    record = _memory(tags=("偏好", "长期"), supersedes="mem#0", temperature=60.0,
                     source_ref="memory/notes.md#L3-L9")

    write_bundle(out, [], agent_name="a", source={}, dropped=[], stores=[], memories=[record])

    row = json.loads((out / "memories.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert MemoryRecord(**row) == record


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
