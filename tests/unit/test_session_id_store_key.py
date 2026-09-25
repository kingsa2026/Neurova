# -*- coding: utf-8 -*-
"""会话标识落到盘上的那一层：外部 id 不能决定文件名。

通道侧把会话 id 拼成 "discord:{channel}:{user}"（qq/mqtt 同形），而这些字符在盘上是有
代价的：Windows 把冒号当数据流分隔符（原子写的改名直接 OSError 87），斜杠与 ".." 能越出
agent 目录，方括号与星号让按 id 拼的 glob 静默失配。归一在路径装配处做一次，读侧保留源名
兜底（POSIX 老库里冒号本来就是合法文件名），否则升级会把已有频道历史读丢。
"""
from datetime import datetime
from pathlib import Path

import pytest

from neurova.session_manager import SessionManager

_DATE = "2026-05-01"


@pytest.fixture()
def sm(tmp_path, monkeypatch) -> SessionManager:
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def _root(sm: SessionManager) -> Path:
    return Path(sm._sessions_dir)


def _files(sm: SessionManager, agent_id: str = "default"):
    return sorted(p.name for p in (_root(sm) / agent_id).glob("session_*.json"))


def test_colon_id_writes_plain_name_and_stays_readable(tmp_path, sm):
    sm.add_message("default", "discord:42:alice", "问题", "回答", date=_DATE)

    names = _files(sm)
    assert len(names) == 1 and ":" not in names[0]
    record = sm.get_session("default", "discord:42:alice", _DATE)
    assert [m.role for m in record.messages] == ["user", "assistant"]


def test_second_turn_appends_into_the_same_file(tmp_path, sm):
    sm.add_message("default", "mqtt:chat-1", "一", "1", date=_DATE)
    first = _files(sm)

    sm.add_message("default", "mqtt:chat-1", "二", "2", date=_DATE)

    assert _files(sm) == first
    assert len(sm.get_session("default", "mqtt:chat-1", _DATE).messages) == 4


def test_traversal_id_cannot_escape_agent_dir(tmp_path, sm):
    sm.add_message("default", "../../escaped", "问题", "回答", date=_DATE)

    escaped = [x for x in _root(sm).rglob("session_*.json") if "default" not in x.parts]
    assert escaped == []                      # 全都会话文件都留在 agent 目录内
    assert len(_files(sm)) == 1


def test_glob_metacharacter_id_is_matched_literally(tmp_path, sm):
    """老库里可能留着按源名落的文件（冒号在 POSIX 合法、方括号会破坏 glob）：读得到、续写同一份。"""
    legacy_dir = _root(sm) / "default"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy = legacy_dir / f"session_a[b]c_{_DATE}.json"
    legacy.write_text('{"session_id": "a[b]c", "messages": [{"role": "user", "content": "老消息"}]}',
                      encoding="utf-8")

    record = sm.get_session("default", "a[b]c", _DATE)
    sm.add_message("default", "a[b]c", "新消息", "新回答", date=_DATE)

    assert [m.content for m in record.messages] == ["老消息"]
    assert legacy.exists() and "新消息" in legacy.read_text(encoding="utf-8")


def test_archive_and_delete_cover_the_normalized_name(tmp_path, sm):
    sm.add_message("default", "qq:9:bo", "问题", "回答", date=_DATE)

    assert sm.archive_session("default", "qq:9:bo") is True
    assert _files(sm) == []
    assert sm.unarchive_session("default", "qq:9:bo") is True
    assert len(_files(sm)) == 1


def test_list_sessions_reports_the_readable_id(tmp_path, sm):
    """列表里的会话号必须与文件里存的一致，否则点开就 404。"""
    sm.add_message("default", "wechat:o9cq@im.wechat", "问题", "回答", date=_DATE)

    items = sm.list_sessions("default")

    listed = items[0]["session_id"]
    assert len(_files(sm)) == 1 and ":" not in _files(sm)[0]
    # 列表里报出的号必须点得开——不管它带不带冒号
    assert len(sm.get_session("default", listed, _DATE).messages) == 2


def test_ingest_entry_and_runtime_entry_agree_on_the_name(tmp_path, sm):
    """两条写入口对同一个源 id 必须算出同一个名字，否则一场对话裂成两份文件。"""
    sm.import_session_messages("default", "wechat:o9cq@im.wechat", _DATE,
                               [{"role": "user", "content": "导入", "timestamp": _DATE,
                                 "metadata": {"ingest": {"identity_key": "ik1"}}}],
                               ingest_run_id="run-x")
    imported = _files(sm)

    sm.add_message("default", "wechat:o9cq@im.wechat", "运行期", "回答", date=_DATE)

    assert _files(sm) == imported
    assert len(sm.get_session("default", "wechat:o9cq@im.wechat", _DATE).messages) == 3
