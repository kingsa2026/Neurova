# -*- coding: utf-8 -*-
"""会话层建目录门（2026-11-24 拍板）：agent 私有根只允许为**登记在册**的 agent
生长（default 恒可）；未知 agent 读路径零建目录、写路径 fail-fast。

说明：conftest 会把 agent 根隔离到 NEUROVA_AGENT_WORKSPACES_DIR（生产形态下
它就是数据根），所以本档的"顶层"断言一律以 `get_agent_root()` 为准。
"""
from __future__ import annotations

import json

import pytest

from neurova.core.agent_workspaces import (
    UnknownAgentError,
    get_agent_root,
    is_registered_agent_id,
)
from neurova.session_manager import SessionManager


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """生产形态的 SessionManager：清掉 conftest 注入的 NEUROVA_SESSIONS_DIR
    （否则 _sessions_dir 走注入分支、建目录门被跳过）。SessionManager 是单例
    ——逐测试重置实例，保证落点口径一致。"""
    monkeypatch.delenv("NEUROVA_SESSIONS_DIR", raising=False)
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    manager = SessionManager()
    yield manager
    SessionManager._instance = None


def _register(agent_id: str) -> None:
    reg = get_agent_root() / "agents" / "agents.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if reg.exists():
        raw = json.loads(reg.read_text(encoding="utf-8")) or {}
    raw[agent_id] = {"name": agent_id}
    reg.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def test_reads_do_not_mint_agent_dirs(sm):
    assert sm.get_history("ghost", "s1") == []
    # get_session 对缺失会话合成空记录（既有行为），但**不得落盘建目录**
    rec = sm.get_session("ghost", "s1")
    assert rec.total_messages == 0
    assert sm.iter_session_files("ghost") == []
    assert sm.read_timeline("ghost", "s1") == []
    assert not (get_agent_root() / "ghost").exists(), "读路径不得建出 agent 根"


def test_save_message_unknown_agent_raises_and_leaves_no_dir(sm):
    with pytest.raises(UnknownAgentError):
        sm.save_message("ghost", "s1", "user", "hi", user_id="u1")
    assert not (get_agent_root() / "ghost").exists()


def test_add_message_unknown_agent_raises_and_leaves_no_dir(sm):
    with pytest.raises(UnknownAgentError):
        sm.add_message("ghost", "s1", "hi", "hello", user_id="u1")
    assert not (get_agent_root() / "ghost").exists()


def test_create_session_unknown_agent_raises(sm):
    with pytest.raises(UnknownAgentError):
        sm.create_session("ghost", user_id="u1")
    assert not (get_agent_root() / "ghost").exists()


def test_timeline_unknown_agent_fail_open(sm):
    assert sm.append_timeline_event("ghost", "s1", {"type": "x"}) is False
    assert not (get_agent_root() / "ghost").exists()


def test_archive_unknown_agent_graceful_noop(sm):
    assert sm.archive_session("ghost", "s1") is False
    assert not (get_agent_root() / "ghost").exists()


def test_registered_agent_writes_normally(sm):
    _register("kai")
    assert sm.save_message("kai", "s1", "user", "hi", user_id="u1") is True
    assert (get_agent_root() / "kai" / "sessions").exists()
    # 登记册里的 id 随便读也不炸、不重复建
    assert sm.get_history("kai", "s1")
    assert sm.iter_session_files("kai")


def test_default_agent_always_allowed(sm):
    sid = sm.create_session("", user_id="u1")
    assert sid
    assert (get_agent_root() / "default" / "sessions").exists()


def test_injected_sessions_dir_skips_gate(tmp_path):
    """测试隔离根（构造参数注入 sessions_dir）不设登记册门——隔离边界即注入本身。
    注入形态的会话文件直接落在 <root>/<agent_id>/ 下（无 sessions 子目录）。"""
    manager = SessionManager(sessions_dir=str(tmp_path / "injected"))
    assert manager.save_message("ghost", "s1", "user", "hi", user_id="u1") is True
    assert (tmp_path / "injected" / "ghost" / "session_s1_2026-11-24.json").exists()


def test_reserved_name_cannot_get_session_dirs(sm):
    """保留名（全局命名空间）即使被当成 agent_id 传进来也不建目录。

    保留名在 _resolve_agent_id 就被拒（ValueError）；未登记 id 在建目录门被拒
    （UnknownAgentError，同为 ValueError 子类）——两形都算拒绝。
    """
    with pytest.raises(ValueError):
        sm.save_message("knowledge", "s1", "user", "hi", user_id="u1")
    assert not (get_agent_root() / "knowledge").exists()
    assert is_registered_agent_id("knowledge") is False
