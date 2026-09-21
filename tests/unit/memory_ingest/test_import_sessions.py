# -*- coding: utf-8 -*-
"""SessionManager 导入入口：只认包内形状，不承担纠错。

喂进来的必须是产品会产出的形状（轮形装配的产物，见 bundle/turns.py）；咽喉不负责把
扁平事件拼成轮——那是装配层的事，两处各拼一次就会从第二处开始漂移。

取证事实（设计 §2）：工具调用与结果在所有被调研 harness 里都跨行关联；市面上的互导
实现（把调用压成 "[ran tool: name]"、丢结果与推理）正是我们要反着做的。
"""
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.records import TranscriptRecord
from neurova.memory_ingest.bundle.turns import to_turn_messages
from neurova.session_manager import (SessionManager, SessionOwnerConflict,
                                     normalize_store_key)

_RUN = "nvimp-sess-1"


@pytest.fixture()
def sessions(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(root))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def _record(seq: int, kind: str, text: str, **kw) -> TranscriptRecord:
    return TranscriptRecord(
        session_id="sA", seq=seq, kind=kind, ts=f"2026-05-01T10:00:{seq:02d}+00:00",
        identity_key=f"ik{seq}", content_blocks=({"type": "text", "text": text},) if text else (),
        **kw,
    )


def _messages() -> list:
    """喂给咽喉的是产品会产出的形状：轮形装配的产物，不是单条记录。"""
    return to_turn_messages([
        _record(1, "user_message", "问题", role="user"),
        _record(2, "assistant_message", "先读文件", role="assistant"),
        _record(3, "tool_call", "", tool_call_id="tc1", tool_name="fs_read",
                extra={"tool_input": '{"path": "A.md"}'}),
        _record(4, "tool_result", "结果正文", tool_call_id="tc1", tool_name="fs_read",
                tool_state="ok"),
    ])


def _stored(sessions: SessionManager, agent_id: str, session_id: str, date: str) -> list:
    """读文件原文：get_session 的 SessionMessage 只带 4 个字段，看不到落盘全貌。"""
    data = sessions._read_session_file(
        sessions._get_session_file(agent_id, session_id, date))
    return (data or {}).get("messages", [])


def test_import_keeps_the_turn_shape_with_its_tool_entries(sessions):
    """一轮多事件合成一条 assistant 消息，工具调用与结果都在 metadata.tool_calls 里。

    这条断言的是"导入产物与运行期落盘同形"：前端步骤卡按 tool_name/params/result 读，
    拆成一条行一事件就看不见工具轨迹。
    """
    added, skipped = sessions.import_session_messages(
        "default", "sA", "2026-05-01", _messages(), ingest_run_id=_RUN)

    stored = _stored(sessions, "default", "sA", "2026-05-01")
    assert (added, skipped) == (2, 0)
    assert [m["role"] for m in stored] == ["user", "assistant"]
    entries = stored[1]["metadata"]["tool_calls"]
    assert [e["type"] for e in entries] == ["tool_call", "tool_result"]
    assert entries[0]["tool_call_id"] == "tc1" and entries[0]["params"] == {"path": "A.md"}
    assert entries[1]["result"] == "结果正文" and entries[1]["state"] == "ok"


def test_imported_tool_entries_survive_the_read_model(sessions):
    """读路径也得拿到工具轨迹：SessionMessage 只透传 metadata，故整串条目留在 metadata 上。"""
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)

    read = sessions.get_session("default", "sA", date="2026-05-01").messages[1]

    assert read.role == "assistant"
    assert [e["tool_name"] for e in read.metadata["tool_calls"]] == ["fs_read", "fs_read"]


def test_import_is_idempotent_by_identity_key(sessions):
    first = sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                             ingest_run_id=_RUN)
    again = sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                             ingest_run_id=_RUN)

    assert (first, again) == ((2, 0), (0, 2))
    assert len(_stored(sessions, "default", "sA", "2026-05-01")) == 2


def test_import_creates_missing_session_with_history_date_and_title(sessions):
    """新会话按历史日期建文件，标题取首条用户消息（前端会话列表要用）。"""
    sessions.import_session_messages("default", "sNew", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)

    data = sessions._read_session_file(
        sessions._get_session_file("default", "sNew", "2026-05-01"))
    assert data["session_date"] == "2026-05-01"
    assert data["created_at"] == "2026-05-01T10:00:01+00:00"
    assert data["title"] == "问题"          # 首条用户消息派生（会话列表要用）
    assert data["total_messages"] == len(data["messages"])


def test_import_appends_to_existing_session_without_rewriting_messages(sessions):
    sessions.add_message("default", "sA", "运行期提问", "运行期回答", date="2026-05-01")
    before = len(_stored(sessions, "default", "sA", "2026-05-01"))

    sessions.import_session_messages("default", "sA", "2026-05-01", _messages()[:2],
                                     ingest_run_id=_RUN)

    after = _stored(sessions, "default", "sA", "2026-05-01")
    assert len(after) == before + 2
    assert after[0]["content"] == "运行期提问"          # 原有消息顺序与内容不动


def test_delete_ingested_messages_removes_only_that_run(sessions):
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)
    sessions.add_message("default", "sA", "运行期提问", "运行期回答", date="2026-05-01")

    removed = sessions.delete_ingested_messages("default", _RUN)

    stored = _stored(sessions, "default", "sA", "2026-05-01")
    assert removed == 2
    assert [m["role"] for m in stored] == ["user", "assistant"]


def test_delete_empties_file_when_all_messages_come_from_the_run(sessions, tmp_path: Path):
    sessions.import_session_messages("default", "sSolo", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)
    path = sessions._get_session_file("default", "sSolo", "2026-05-01")

    removed = sessions.delete_ingested_messages("default", _RUN)

    assert removed == 2 and not path.exists()


def test_import_requires_run_id(sessions):
    with pytest.raises(ValueError, match="ingest_run_id"):
        sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                         ingest_run_id="")


# --- 外部标识符进咽喉前必须归一：实测 Windows 下名字里的冒号被 NTFS 当数据流分隔符，
#     文件写得出去、glob 看不见（基名 0 字节），斜杠则能越出 agent 目录


def test_hostile_session_id_stays_inside_agent_dir(sessions, tmp_path: Path):
    sessions.import_session_messages("default", "evil/../../../../outside/x", "2026-05-01",
                                     _messages(), ingest_run_id=_RUN)

    assert not (tmp_path / "outside").exists()
    files = list((tmp_path / "sessions" / "default").glob("session_*.json"))
    assert len(files) == 1


def test_colon_bearing_id_writes_a_plain_filename(sessions, tmp_path: Path):
    """导入的会话必须被 session_*.json 的 glob 看得见，否则历史在列表里根本不存在。"""
    sessions.import_session_messages("default", "wechat:o9cq8@im.wechat", "2026-05-01",
                                     _messages(), ingest_run_id=_RUN)

    files = list((tmp_path / "sessions" / "default").glob("session_*.json"))
    assert len(files) == 1 and ":" not in files[0].name


def test_normalized_id_is_deterministic_and_safe_ids_are_untouched():
    """同一源 id 两次导入必须落到同一文件；已合规的运行期 id 不得改名。"""
    assert normalize_store_key("wechat:o9cq8@im.wechat") == \
        normalize_store_key("wechat:o9cq8@im.wechat")
    assert ":" not in normalize_store_key("wechat:o9cq8@im.wechat")
    assert normalize_store_key("auto-5e868087690a") == "auto-5e868087690a"
    assert normalize_store_key("sA") == "sA"


def test_source_session_id_is_recorded_and_session_is_readable(sessions):
    """改名不能改丢出处：原 id 留在 metadata，按归一 id 仍要读得回整段会话。"""
    raw = "wechat:o9cq8@im.wechat"
    sessions.import_session_messages("default", raw, "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)
    key = normalize_store_key(raw)

    stored = _stored(sessions, "default", key, "2026-05-01")
    record = sessions.get_session("default", key, "2026-05-01")

    assert [m["metadata"]["ingest"]["source_session_id"] for m in stored[:1]] == [raw]
    assert stored[0]["metadata"]["ingest"]["session_id"] == key
    assert len(record.messages) == 2


def test_empty_session_id_is_rejected(sessions):
    with pytest.raises(ValueError, match="session_id"):
        sessions.import_session_messages("default", "  ", "2026-05-01", _messages(),
                                         ingest_run_id=_RUN)


# --- F-04 导入会话的属主：归属由导入侧写进落盘形状，读侧既有过滤才咬得住


def test_imported_session_is_visible_only_to_its_owner(sessions):
    """不写属主的导入会话对任意 user_id 都可见，且可被任意用户改名/删除。

    读侧（list_sessions / delete / rename）的过滤规则是"空属主=共享"，本来正确；
    错在导入侧生产了"没有属主"这份状态——修在产生它的这一侧。
    """
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN, owner_user_id="u_alice")

    assert [s["session_id"] for s in sessions.list_sessions("default", user_id="u_alice")] == ["sA"]
    assert sessions.list_sessions("default", user_id="u_bob") == []


def test_imported_session_summary_reports_the_owner(sessions):
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN, owner_user_id="u_alice")

    assert sessions.list_sessions("default")[0]["user_id"] == "u_alice"


def test_import_leaves_the_session_shared_when_no_owner_is_given(sessions):
    """缺省仍是"共享"：单用户桌面下这是一条合法语义，不是缺陷。"""
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)

    summary = sessions.list_sessions("default")[0]
    assert summary["user_id"] == ""
    assert [s["session_id"] for s in sessions.list_sessions("default", user_id="u_bob")] == ["sA"]


def test_import_refuses_to_rewrite_an_existing_owner(sessions):
    """一份会话文件的属主一旦定下来就不再被另一次导入改写。

    否则后一次导入能把别人的历史认领成自己的（或把自己的推给别人），
    读侧过滤是在错误的事实上做正确的事。
    """
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages()[:1],
                                     ingest_run_id=_RUN, owner_user_id="u_alice")

    with pytest.raises(SessionOwnerConflict, match="u_alice"):
        sessions.import_session_messages("default", "sA", "2026-05-01", _messages()[1:],
                                         ingest_run_id="nvimp-sess-2", owner_user_id="u_bob")

    assert sessions.list_sessions("default")[0]["user_id"] == "u_alice"


def test_shared_import_cannot_widen_an_owned_session(sessions):
    """往已有属主的会话里导"共享"批次 = 把私有历史的可见范围放宽，必须拒。"""
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages()[:1],
                                     ingest_run_id=_RUN, owner_user_id="u_alice")

    with pytest.raises(SessionOwnerConflict, match="u_alice"):
        sessions.import_session_messages("default", "sA", "2026-05-01", _messages()[1:],
                                         ingest_run_id="nvimp-sess-3")


def test_import_backfills_the_owner_on_a_shared_session(sessions):
    """存量共享会话被指定属主导入时回填（与 add_message 的 DATA-P1-1 同一口径）。"""
    sessions.add_message("default", "sA", "运行期提问", "运行期回答", date="2026-05-01")

    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN, owner_user_id="u_alice")

    assert sessions.list_sessions("default")[0]["user_id"] == "u_alice"
    assert sessions.list_sessions("default", user_id="u_bob") == []
