# -*- coding: utf-8 -*-
"""会话置顶 roundtrip 测试（补课 2.3）。

SessionManager.set_session_pinned 写 pinned 字段到所有日期文件，
list_sessions 摘要透出 pinned；ABC 默认实现优雅降级返回 False。

SessionManager 是 __new__ 单例：目录覆盖走 NEUROVA_SESSIONS_DIR env，
每个用例重置单例 + 独立 tmp 目录。
"""
from pathlib import Path

import pytest

import neurova.session_manager as sm_mod


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    sm_mod.SessionManager._instance = None
    mgr = sm_mod.SessionManager()
    yield mgr
    sm_mod.SessionManager._instance = None


def test_pin_roundtrip(manager):
    sid = manager.create_session(agent_id="a1", user_id="u1", title="T")
    assert manager.set_session_pinned("a1", sid, True) is True
    sessions = manager.list_sessions(agent_id="a1")
    target = next(s for s in sessions if s["session_id"] == sid)
    assert target["pinned"] is True

    assert manager.set_session_pinned("a1", sid, False) is True
    sessions = manager.list_sessions(agent_id="a1")
    target = next(s for s in sessions if s["session_id"] == sid)
    assert target["pinned"] is False


def test_pin_missing_session_returns_false(manager):
    assert manager.set_session_pinned("a1", "nonexistent", True) is False


def test_pin_writes_all_files(manager):
    sid = manager.create_session(agent_id="a1", user_id="u1", title="T")
    manager.save_message("a1", sid, "user", "hello")
    assert manager.set_session_pinned("a1", sid, True) is True
    sessions = manager.list_sessions(agent_id="a1")
    assert all(s["pinned"] is True for s in sessions if s["session_id"] == sid)
