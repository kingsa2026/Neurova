"""
测试：session_manager — 会话管理器

测试 SessionManager 的单例模式、消息写入/读取、搜索、删除、统计等功能。
通过 monkeypatch _get_session_dir 将文件写入临时目录，避免污染真实目录。
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from neurova.session_manager import (
    SessionManager,
    SessionMessage,
    SessionRecord,
    get_session_manager,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path) -> SessionManager:
    """创建 SessionManager 并 patch _get_session_dir 指向 tmp_path。"""
    mgr = SessionManager()

    # 直接替换实例属性（不通过 __get__ 绑定，避免 bound method 额外传 self）
    def _fake_dir(agent_id_arg):
        d = tmp_path / "agents" / agent_id_arg / "session"
        d.mkdir(parents=True, exist_ok=True)
        return d

    mgr._get_session_dir = _fake_dir
    return mgr


# ======================================================
# 测试 Dataclass
# ======================================================

class TestSessionMessage:
    """SessionMessage 数据类"""

    def test_default_timestamp(self):
        msg = SessionMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.timestamp is not None
        assert msg.metadata is None

    def test_with_metadata(self):
        msg = SessionMessage(role="assistant", content="world", metadata={"key": "val"})
        assert msg.metadata == {"key": "val"}


class TestSessionRecord:
    """SessionRecord 数据类"""

    def test_defaults(self):
        record = SessionRecord(agent_id="agent_a", session_id="sess_01", session_date="2025-01-01")
        assert record.messages == []
        assert record.total_messages == 0
        assert record.created_at is not None
        assert record.updated_at is not None

    def test_with_messages(self):
        msgs = [SessionMessage(role="user", content="hi")]
        record = SessionRecord(
            agent_id="a", session_id="s1", session_date="2025-01-01",
            messages=msgs, total_messages=1,
        )
        assert len(record.messages) == 1
        assert record.total_messages == 1


# ======================================================
# 测试 Singleton
# ======================================================

class TestSingleton:
    """SessionManager 单例模式"""

    def test_singleton_returns_same_instance(self):
        m1 = SessionManager()
        m2 = SessionManager()
        assert m1 is m2

    def test_get_session_manager_helper(self):
        m1 = get_session_manager()
        m2 = get_session_manager()
        assert m1 is m2

    def test_init_once(self):
        """_initialized 标志确保 __init__ 只执行一次"""
        m1 = SessionManager()
        # 直接修改内容来验证第二次 __init__ 不会重置
        m1._dummy_flag = "set"
        m2 = SessionManager()
        assert hasattr(m2, "_dummy_flag")


# ======================================================
# 测试 add_message 与 get_session
# ======================================================

class TestAddAndGetSession:
    """写入和读取会话"""

    def test_add_message_creates_file(self, tmp_path):
        mgr = _make_manager(tmp_path)
        key = mgr.add_message("agent_a", "sess_01", "hi", "hello")
        # 检查文件是否存在
        session_dir = tmp_path / "agents" / "agent_a" / "session"
        files = list(session_dir.glob("session_sess_01_*.json"))
        assert len(files) == 1

    def test_get_session_returns_record(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_02", "hi", "hello")
        record = mgr.get_session("agent_a", "sess_02")
        assert record is not None
        assert record.agent_id == "agent_a"
        assert record.session_id == "sess_02"
        assert len(record.messages) == 2
        assert record.messages[0].role == "user"
        assert record.messages[0].content == "hi"
        assert record.messages[1].role == "assistant"
        assert record.messages[1].content == "hello"
        assert record.total_messages == 2

    def test_get_session_not_found(self, tmp_path):
        mgr = _make_manager(tmp_path)
        record = mgr.get_session("nonexistent", "no_such_session")
        # 返回默认空记录（agent_id 和 session_id 被覆盖）
        assert record is not None
        assert record.agent_id == "nonexistent"
        assert record.session_id == "no_such_session"
        assert record.messages == []

    def test_add_message_appends(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_03", "q1", "a1")
        mgr.add_message("agent_a", "sess_03", "q2", "a2")
        record = mgr.get_session("agent_a", "sess_03")
        assert len(record.messages) == 4
        assert record.total_messages == 4
        assert record.messages[2].content == "q2"
        assert record.messages[3].content == "a2"

    def test_add_message_returns_key(self, tmp_path):
        mgr = _make_manager(tmp_path)
        key = mgr.add_message("agent_b", "s_01", "hello", "world")
        assert "agent_b" in key
        assert "s_01" in key

    def test_add_message_with_metadata(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_md", "hi", "hello", metadata={"source": "test"})
        record = mgr.get_session("agent_a", "sess_md")
        assert record.messages[0].metadata == {"source": "test"}


# ======================================================
# 测试 search_session
# ======================================================

class TestSearchSession:
    """会话搜索"""

    def test_search_finds_keyword(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_search", "hello world", "goodbye")
        results = mgr.search_session("agent_a", "sess_search", "hello")
        assert len(results) >= 1
        assert results[0]["role"] == "user"
        assert "hello" in results[0]["content"]

    def test_search_finds_in_assistant(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_search2", "hi", "the answer is 42")
        results = mgr.search_session("agent_a", "sess_search2", "42")
        assert len(results) >= 1
        assert results[0]["role"] == "assistant"

    def test_search_case_insensitive(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_cs", "Hello World", "OK")
        results = mgr.search_session("agent_a", "sess_cs", "hello")
        assert len(results) >= 1

    def test_search_not_found(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_nf", "alpha", "beta")
        results = mgr.search_session("agent_a", "sess_nf", "gamma")
        assert results == []


# ======================================================
# 测试 create_session / get_sessions / get_sessions_by_id
# ======================================================

class TestListSessions:
    """会话列表查询"""

    def test_create_session_returns_id(self, tmp_path):
        mgr = _make_manager(tmp_path)
        session_id = mgr.create_session("agent_a")
        assert isinstance(session_id, str)
        assert len(session_id) == 8  # uuid4()[:8]

    # ── 幽灵 session 防御 (chat.loadHistoryFailed toast 后端根因修复) ───
    # 旧契约: create_session 调 _write_session_file 不检查返回值, 文件写入失败
    # 时仍返回 session_id 给前端 → 前端拿到 ID 加入 sidebar → 用户点击 GET
    # /history → 404 → toast "加载历史对话失败" (chat.loadHistoryFailed).
    # _write_session_file_unlocked except 块只 logger.debug 返回 False, 但
    # create_session 不检查, 是 silent failure antipattern.
    # 新契约: create_session 文件写入失败时抛 RuntimeError, 让 HTTP 端点返回
    # 500 错误, 前端 onError 弹 toast, 不创建幽灵 session.
    # 详见 docs/bugfix-delete-session-userid-mismatch.md "§8 幽灵 session 自愈".
    def test_create_session_raises_when_file_write_fails(self, tmp_path):
        from unittest.mock import MagicMock
        mgr = _make_manager(tmp_path)
        # 模拟文件写入失败: _write_session_file 返回 False ( silent failure )
        mgr._write_session_file = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="Failed to persist session file"):
            mgr.create_session("agent_a", user_id="alice", title="test")

        # 确保没有遗留任何 session_id 返回给调用方
        mgr._write_session_file.assert_called_once()

    def test_create_session_succeeds_when_file_write_succeeds(self, tmp_path):
        from unittest.mock import MagicMock
        mgr = _make_manager(tmp_path)
        mgr._write_session_file = MagicMock(return_value=True)

        session_id = mgr.create_session("agent_a", user_id="alice", title="test")

        assert isinstance(session_id, str)
        assert len(session_id) == 8
        mgr._write_session_file.assert_called_once()

    def test_get_sessions_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        sessions = mgr.get_sessions("agent_a")
        assert sessions == []

    def test_get_sessions_returns_list(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_list_1", "hi", "hello")
        mgr.add_message("agent_a", "sess_list_2", "hi", "hello")
        sessions = mgr.get_sessions("agent_a")
        assert len(sessions) >= 2

    def test_get_sessions_by_id(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_multi_day", "hi", "hello")
        # 手动模拟另一个日期的文件
        session_dir = tmp_path / "agents" / "agent_a" / "session"
        # 再写入一个不同日期的文件
        fake_path = session_dir / "session_sess_multi_day_2099-12-31.json"
        fake_data = {
            "agent_id": "agent_a",
            "session_id": "sess_multi_day",
            "session_date": "2099-12-31",
            "messages": [],
            "total_messages": 0,
        }
        fake_path.write_text(json.dumps(fake_data), encoding="utf-8")

        sessions = mgr.get_sessions_by_id("agent_a", "sess_multi_day")
        assert len(sessions) >= 2
        assert any("2099-12-31" in s for s in sessions)

    def test_get_sessions_by_id_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_sessions_by_id("agent_a", "no_such") == []


# ======================================================
# 测试 delete_session
# ======================================================

class TestDeleteSession:
    """删除会话"""

    def test_delete_session_removes_file(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_del", "hi", "hello")
        session_dir = tmp_path / "agents" / "agent_a" / "session"
        files_before = list(session_dir.glob("session_sess_del_*.json"))
        assert len(files_before) == 1
        mgr.delete_session("agent_a", "sess_del")
        files_after = list(session_dir.glob("session_sess_del_*.json"))
        assert len(files_after) == 0

    def test_delete_nonexistent_session_does_not_raise(self, tmp_path):
        mgr = _make_manager(tmp_path)
        # 不会报错
        mgr.delete_session("agent_a", "no_such_session")

    def test_delete_session_with_specific_date(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_date", "hi", "hello")
        # 获取实际日期
        record = mgr.get_session("agent_a", "sess_date")
        date = record.session_date
        mgr.delete_session("agent_a", "sess_date", date)
        record = mgr.get_session("agent_a", "sess_date")
        assert record.messages == []  # 被删后重新读取返回空记录


# ======================================================
# 测试 get_session_stats
# ======================================================

class TestGetSessionStats:
    """会话统计"""

    def test_stats_basic(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message("agent_a", "sess_stat", "hi", "hello")
        stats = mgr.get_session_stats("agent_a", "sess_stat")
        assert stats["agent_id"] == "agent_a"
        assert stats["session_id"] == "sess_stat"
        assert stats["total_files"] >= 1
        assert stats["total_messages"] >= 2
        assert stats["total_size_bytes"] > 0
        assert len(stats["dates"]) >= 1

    def test_stats_nonexistent(self, tmp_path):
        mgr = _make_manager(tmp_path)
        stats = mgr.get_session_stats("agent_a", "no_such")
        assert stats["total_files"] == 0
        assert stats["total_messages"] == 0
        assert stats["total_size_bytes"] == 0
        assert stats["dates"] == []


# ======================================================
# 测试线程锁
# ======================================================

class TestFileLock:
    """文件锁机制"""

    def test_get_file_lock_same_path(self, tmp_path):
        mgr = _make_manager(tmp_path)
        lock1 = mgr._get_file_lock(tmp_path / "a.json")
        lock2 = mgr._get_file_lock(tmp_path / "a.json")
        assert lock1 is lock2

    def test_get_file_lock_different_path(self, tmp_path):
        mgr = _make_manager(tmp_path)
        lock1 = mgr._get_file_lock(tmp_path / "a.json")
        lock2 = mgr._get_file_lock(tmp_path / "b.json")
        assert lock1 is not lock2
