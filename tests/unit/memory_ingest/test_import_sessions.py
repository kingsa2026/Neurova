# -*- coding: utf-8 -*-
"""SessionManager 导入入口：保留扁平事件行，不压成一问一答。

取证事实（设计 §2）：工具调用与结果在所有被调研 harness 里都跨行关联；市面上的互导
实现（把调用压成 "[ran tool: name]"、丢结果与推理）正是我们要反着做的。
"""
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.records import TranscriptRecord
from neurova.session_manager import SessionManager, normalize_store_key

_RUN = "nvimp-sess-1"


@pytest.fixture()
def sessions(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(root))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def _msg(seq: int, kind: str, text: str, **kw) -> dict:
    record = TranscriptRecord(
        session_id="sA", seq=seq, kind=kind, ts=f"2026-05-01T10:00:{seq:02d}+00:00",
        identity_key=f"ik{seq}", content_blocks=({"type": "text", "text": text},) if text else (),
        **kw,
    )
    return record.to_session_message()


def _messages() -> list:
    return [
        _msg(1, "user_message", "问题"),
        _msg(2, "assistant_message", "先读文件"),
        _msg(3, "tool_call", "", tool_call_id="tc1", tool_name="fs_read"),
        _msg(4, "tool_result", "结果正文", tool_call_id="tc1", tool_name="fs_read",
             tool_state="ok"),
    ]


def _stored(sessions: SessionManager, agent_id: str, session_id: str, date: str) -> list:
    """读文件原文：get_session 的 SessionMessage 只带 4 个字段，看不到落盘全貌。"""
    data = sessions._read_session_file(
        sessions._get_session_file(agent_id, session_id, date))
    return (data or {}).get("messages", [])


def test_import_keeps_tool_events_as_separate_rows(sessions):
    added, skipped = sessions.import_session_messages(
        "default", "sA", "2026-05-01", _messages(), ingest_run_id=_RUN)

    stored = _stored(sessions, "default", "sA", "2026-05-01")
    assert (added, skipped) == (4, 0)
    assert [m["role"] for m in stored] == ["user", "assistant", "assistant", "tool"]
    assert stored[3]["tool_call_id"] == "tc1"
    assert stored[3]["tool_state"] == "ok"


def test_imported_tool_links_survive_the_read_model(sessions):
    """读路径也得拿到工具关联：SessionMessage 只透传 metadata，故镜像进 ingest。"""
    sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)

    read = sessions.get_session("default", "sA", date="2026-05-01").messages[3]

    assert read.role == "tool"
    assert read.metadata["ingest"]["tool_call_id"] == "tc1"
    assert read.metadata["ingest"]["tool_name"] == "fs_read"


def test_import_is_idempotent_by_identity_key(sessions):
    first = sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                             ingest_run_id=_RUN)
    again = sessions.import_session_messages("default", "sA", "2026-05-01", _messages(),
                                             ingest_run_id=_RUN)

    assert (first, again) == ((4, 0), (0, 4))
    assert len(_stored(sessions, "default", "sA", "2026-05-01")) == 4


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
    assert removed == 4
    assert [m["role"] for m in stored] == ["user", "assistant"]


def test_delete_empties_file_when_all_messages_come_from_the_run(sessions, tmp_path: Path):
    sessions.import_session_messages("default", "sSolo", "2026-05-01", _messages(),
                                     ingest_run_id=_RUN)
    path = sessions._get_session_file("default", "sSolo", "2026-05-01")

    removed = sessions.delete_ingested_messages("default", _RUN)

    assert removed == 4 and not path.exists()


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
    assert len(record.messages) == 4


def test_empty_session_id_is_rejected(sessions):
    with pytest.raises(ValueError, match="session_id"):
        sessions.import_session_messages("default", "  ", "2026-05-01", _messages(),
                                         ingest_run_id=_RUN)
