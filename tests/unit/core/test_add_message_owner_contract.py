# -*- coding: utf-8 -*-
"""DATA-P1-1（审计 2026-09-11）回归：add_message 会话属主契约。

- 新建会话分支必须写入 user_id/title（与 create_session 对齐），
  否则 _collect_summaries 对空属主放行 → 会话跨用户可见。
- 存量会话缺 user_id 时随下次写入回填。

SessionManager 是 __new__ 单例：目录覆盖走 NEUROVA_SESSIONS_DIR env，
每个用例重置单例 + 独立 tmp 目录（同 test_session_pin.py 范式）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import neurova.session_manager as sm_mod


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    sm_mod.SessionManager._instance = None
    mgr = sm_mod.SessionManager()
    yield mgr, tmp_path / "sessions"
    sm_mod.SessionManager._instance = None


def _find_session_file(sessions_dir: Path, session_id: str) -> Path:
    for p in sessions_dir.rglob("session_*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("session_id") == session_id:
            return p
    raise AssertionError(f"session file not found: {session_id}")


def test_add_message_new_session_writes_user_id(manager):
    sm, sessions_dir = manager
    sm.add_message(
        agent_id="a1", session_id="s-new-1",
        user_content="hi", assistant_content="hello",
        user_id="userA",
    )
    data = json.loads(_find_session_file(sessions_dir, "s-new-1").read_text(encoding="utf-8"))
    assert data["user_id"] == "userA"
    assert data.get("title")


def test_add_message_backfills_missing_owner(manager):
    sm, sessions_dir = manager
    sm.add_message(agent_id="a1", session_id="s-legacy",
                   user_content="hi", assistant_content="hello")
    path = _find_session_file(sessions_dir, "s-legacy")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("user_id", None)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    sm.add_message(agent_id="a1", session_id="s-legacy",
                   user_content="again", assistant_content="ok", user_id="userB")
    healed = json.loads(path.read_text(encoding="utf-8"))
    assert healed["user_id"] == "userB"


def test_collect_summaries_filters_other_owner(manager):
    sm, _ = manager
    sm.add_message(agent_id="a1", session_id="s-alice",
                   user_content="q", assistant_content="a", user_id="alice")
    sm.add_message(agent_id="a1", session_id="s-bob",
                   user_content="q", assistant_content="a", user_id="bob")
    seen_alice = {s["session_id"] for s in sm.list_sessions(agent_id="a1", user_id="alice")}
    assert "s-alice" in seen_alice
    assert "s-bob" not in seen_alice
