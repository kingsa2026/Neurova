# -*- coding: utf-8 -*-
"""扁平事件流 → 轮形会话消息：导入产物必须与运行期落盘同形。

运行期一条 assistant 轮写的是"一条消息 + metadata.tool_calls 列表"
（post_chat_pipeline._step_save_session → _collect_tool_messages），前端步骤卡按
tool_name/params/result 读（collaborationRoom.normalizeToolMessages）。把 bundle 的
一行一事件直接写进会话文件，形状就和运行期产物不一致，工具轨迹在 UI 上看不见。
"""
from typing import Any, Dict, List

import pytest

from neurova.memory_ingest.bundle.records import TranscriptRecord
from neurova.memory_ingest.bundle.turns import to_turn_messages

_ROLES = {"user_message": "user", "assistant_message": "assistant",
          "tool_call": "assistant", "tool_result": "tool", "system": "system",
          "compact_summary": "assistant"}


def test_turn_collects_media_refs_in_order():
    """轮形装配把各行的 media 引用汇总成一条列表，intake 据此落工作区。"""
    ref = {"type": "image", "media": "media/a.png", "digest": "a", "bytes": 2,
           "name": "a.png", "mime": "image/png"}
    other = {"type": "file", "media": "media/b.bin", "digest": "b", "bytes": 3,
             "name": "b.bin", "mime": "application/octet-stream"}
    messages = to_turn_messages([
        _rec(1, "assistant_message", text="看"),
        _rec(2, "tool_result", text="结果", blocks=(other,)),
        _rec(3, "assistant_message", text="图", blocks=(ref,)),
    ])

    assert messages[0]["metadata"]["media"] == [other, ref]


def _rec(seq: int, kind: str, **kw: Any) -> TranscriptRecord:
    text = kw.get("text", "")
    extra: Dict[str, Any] = {}
    if kw.get("tool_input"):
        extra["tool_input"] = kw["tool_input"]
    return TranscriptRecord(
        session_id=kw.get("session_id", "sA"), seq=seq, kind=kind,
        ts=f"2026-05-01T10:00:{seq:02d}", identity_key=f"sA#{seq}", role=_ROLES[kind],
        tool_call_id=kw.get("tool_call_id", ""), tool_name=kw.get("tool_name", ""),
        tool_state=kw.get("tool_state", ""),
        reasoning_state="text" if kw.get("reasoning") else "absent",
        reasoning_text=kw.get("reasoning", ""), extra=extra,
        content_blocks=tuple(
            ([{"type": "text", "text": text}] if text else []) + list(kw.get("blocks", ()))),
    )


def _msgs(records: List[TranscriptRecord]) -> List[Dict[str, Any]]:
    return to_turn_messages(records)


def test_user_message_stands_alone():
    messages = _msgs([_rec(1, "user_message", text="问题")])

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "问题"
    assert "tool_calls" not in (messages[0]["metadata"] or {})


def test_turn_merges_interleaved_text_and_calls():
    """一轮里的正文与调用合成一条消息，条目顺序即源事件顺序。"""
    records = [
        _rec(1, "user_message", text="跑一下"),
        _rec(2, "assistant_message", text="先看", reasoning="在想"),
        _rec(3, "tool_call", tool_call_id="tc1", tool_name="read_file",
             tool_state="finished", tool_input='{"path": "A.md"}'),
        _rec(4, "tool_result", tool_call_id="tc1", tool_name="read_file",
             tool_state="success", text="结果A"),
        _rec(5, "assistant_message", text="再看"),
        _rec(6, "tool_call", tool_call_id="tc2", tool_name="glob_search",
             tool_state="finished", tool_input='{"pattern": "*.md"}'),
        _rec(7, "user_message", text="下一轮"),
    ]

    messages = _msgs(records)

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    turn = messages[1]
    assert turn["content"] == "先看\n再看"
    assert turn["metadata"]["reasoning_content"] == "在想"
    entries = turn["metadata"]["tool_calls"]
    assert [e["type"] for e in entries] == ["tool_call", "tool_result", "tool_call"]
    assert entries[0]["tool_name"] == "read_file" and entries[0]["params"] == {"path": "A.md"}
    assert entries[1]["result"] == "结果A"
    assert entries[0]["tool_call_id"] == "tc1" == entries[1]["tool_call_id"]
    assert entries[0]["timestamp"] == "2026-05-01T10:00:03"


def test_text_runs_join_with_newline_to_reproduce_source_content():
    """源 content 就是各正文块以换行拼接，装配回去必须逐字相同。"""
    records = [_rec(1, "assistant_message", text="\n\n"),
               _rec(2, "assistant_message", text="嘿，初次见面")]

    assert _msgs(records)[0]["content"] == "\n\n\n嘿，初次见面"


def test_tool_only_turn_still_yields_one_message():
    """空正文纯工具轮（实测源里确有此形态）不能因为没正文就整轮消失。"""
    records = [_rec(1, "tool_call", tool_call_id="tc1", tool_name="fs_read",
                    tool_state="finished", tool_input="{}")]

    messages = _msgs(records)

    assert len(messages) == 1 and messages[0]["role"] == "assistant"
    assert messages[0]["content"] == ""
    assert messages[0]["metadata"]["tool_calls"][0]["type"] == "tool_call"


def test_broken_tool_params_stay_verbatim():
    """参数不是合法 JSON 时原样带走，不解析失败就换成空字典。"""
    records = [_rec(1, "tool_call", tool_call_id="tc1", tool_name="t", tool_state="finished",
                    tool_input="not-json")]

    entry = _msgs(records)[0]["metadata"]["tool_calls"][0]

    assert entry["params"] == "not-json"


def test_turn_identity_is_addressable_and_covers_its_events():
    """幂等键取轮内首条事件，seq 区间留全，二次导入同一包才跳得干净。"""
    records = [_rec(1, "assistant_message", text="a"),
               _rec(2, "tool_call", tool_call_id="tc1", tool_name="t", tool_state="finished",
                    tool_input="{}")]

    ingest = _msgs(records)[0]["metadata"]["ingest"]

    assert ingest["identity_key"] == "sA#1"
    assert ingest["seq_from"] == 1 and ingest["seq_to"] == 2
    assert [k for k in ingest["event_keys"]] == ["sA#1", "sA#2"]


def test_system_and_compact_summary_break_the_turn():
    records = [_rec(1, "assistant_message", text="上半"),
               _rec(2, "system", text="系统提示"),
               _rec(3, "assistant_message", text="下半"),
               _rec(4, "compact_summary", text="压缩摘要")]

    messages = _msgs(records)

    assert [m["role"] for m in messages] == ["assistant", "system", "assistant", "assistant"]
    assert messages[0]["content"] == "上半" and messages[2]["content"] == "下半"


def test_state_is_carried_verbatim_not_reinterpreted():
    """源里的 state 词表不归运行期管，原样带上，不猜 success 布尔。"""
    records = [_rec(1, "tool_result", tool_call_id="tc1", tool_name="t",
                    tool_state="aborted", text="部分结果")]

    entry = _msgs(records)[0]["metadata"]["tool_calls"][0]

    assert entry["state"] == "aborted" and "success" not in entry


def test_empty_input_yields_no_messages():
    assert to_turn_messages([]) == []


def test_session_change_breaks_the_turn():
    """调用方按会话分组是约定，不是护栏：跨会话不得被合成一条消息。"""
    records = [_rec(1, "assistant_message", text="甲会话"),
               _rec(2, "assistant_message", text="乙会话", session_id="sB")]

    messages = _msgs(records)

    assert [m["content"] for m in messages] == ["甲会话", "乙会话"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
