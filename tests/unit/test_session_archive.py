"""会话存档/恢复 TDD 测试（SessionManager 文件层）

需求：删除变为存档——存档后历史会话列表不再显示，存档会话可随时恢复。

存储设计（目录移动式，最小侵入）：
  sessions/{agent_id}/session_{sid}_{date}.json        ← 正常会话
  sessions/{agent_id}/archived/session_{sid}_{date}.json ← 已存档会话

现有 list/get/delete/rename 全部基于 agent_dir 的 session_*.json glob，
文件移入 archived/ 子目录后自动从所有现有查询中消失，无需改动；
恢复即移回。SessionManager 无内存缓存，无复活问题。
"""

import json
from pathlib import Path

import pytest

from neurova.session_manager import SessionManager


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """CWD 指向 tmp_path（SessionManager 的 sessions/ 是 CWD 相对），重置单例。"""
    monkeypatch.chdir(tmp_path)
    SessionManager._instance = None
    manager = SessionManager()
    yield manager
    SessionManager._instance = None


def _seed_session(sm: SessionManager, agent_id: str, session_id: str, dates: list[str], user_id: str = "u1"):
    """造一个跨多日期文件的真实会话。"""
    for date in dates:
        path = sm._get_session_file(agent_id, session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agent_id": agent_id,
            "session_id": session_id,
            "session_date": date,
            "user_id": user_id,
            "title": f"会话 {session_id}",
            "created_at": f"{date}T10:00:00",
            "updated_at": f"{date}T10:00:00",
            "total_messages": 2,
            "messages": [
                {"role": "user", "content": "你好", "timestamp": f"{date}T10:00:00"},
                {"role": "assistant", "content": "你好！", "timestamp": f"{date}T10:00:01"},
            ],
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class TestArchiveSession:
    def test_archive_moves_all_date_files_to_archived_dir(self, sm, tmp_path):
        _seed_session(sm, "kai", "sess-a", ["2026-08-28", "2026-08-29"])
        assert sm.archive_session(agent_id="kai", session_id="sess-a") is True

        agent_dir = tmp_path / "sessions" / "kai"
        assert list(agent_dir.glob("session_sess-a_*.json")) == [], "存档后主目录不得残留会话文件"
        archived = list((agent_dir / "archived").glob("session_sess-a_*.json"))
        assert len(archived) == 2, "跨日期文件必须全部移入 archived/"

    def test_archived_session_hidden_from_list_and_visible_in_archived_list(self, sm):
        _seed_session(sm, "kai", "sess-b", ["2026-08-29"])
        sm.archive_session(agent_id="kai", session_id="sess-b")

        normal = [s["session_id"] for s in sm.list_sessions(agent_id="kai")]
        assert "sess-b" not in normal, "存档会话不得出现在正常历史列表"

        archived = [s["session_id"] for s in sm.list_archived_sessions(agent_id="kai")]
        assert "sess-b" in archived, "存档会话必须出现在存档列表"

    def test_unarchive_restores_session_to_normal_list(self, sm):
        _seed_session(sm, "kai", "sess-c", ["2026-08-29"])
        sm.archive_session(agent_id="kai", session_id="sess-c")

        assert sm.unarchive_session(agent_id="kai", session_id="sess-c") is True
        normal = [s["session_id"] for s in sm.list_sessions(agent_id="kai")]
        assert "sess-c" in normal
        assert sm.list_archived_sessions(agent_id="kai") == []

    def test_archive_nonexistent_session_returns_false(self, sm):
        assert sm.archive_session(agent_id="kai", session_id="no-such") is False

    def test_unarchive_non_archived_session_returns_false(self, sm):
        _seed_session(sm, "kai", "sess-d", ["2026-08-29"])
        assert sm.unarchive_session(agent_id="kai", session_id="sess-d") is False

    def test_archive_isolated_per_agent(self, sm):
        """同名 session_id 只在目标 agent 目录内存档，其他 agent 不受影响。"""
        _seed_session(sm, "kai", "shared-sid", ["2026-08-29"])
        _seed_session(sm, "default", "shared-sid", ["2026-08-29"])

        sm.archive_session(agent_id="kai", session_id="shared-sid")

        assert [s["session_id"] for s in sm.list_sessions(agent_id="kai")] == []
        assert [s["session_id"] for s in sm.list_sessions(agent_id="default")] == ["shared-sid"]

    def test_list_archived_sessions_scans_all_agents_without_filter(self, sm):
        _seed_session(sm, "kai", "sess-k", ["2026-08-29"], user_id="alice")
        _seed_session(sm, "default", "sess-d2", ["2026-08-29"], user_id="")
        _seed_session(sm, "default", "sess-bob", ["2026-08-29"], user_id="bob")
        sm.archive_session(agent_id="kai", session_id="sess-k")
        sm.archive_session(agent_id="default", session_id="sess-d2")
        sm.archive_session(agent_id="default", session_id="sess-bob")

        all_archived = {s["session_id"] for s in sm.list_archived_sessions()}
        assert {"sess-k", "sess-d2", "sess-bob"} <= all_archived

        alice_only = {s["session_id"] for s in sm.list_archived_sessions(user_id="alice")}
        assert "sess-k" in alice_only, "自己的会话必须可见"
        assert "sess-d2" in alice_only, "空 user_id 视为共享，对所有人可见（与 list_sessions 一致）"
        assert "sess-bob" not in alice_only, "他人的非空 user_id 会话必须被过滤"

    def test_unarchive_overwrites_stale_main_dir_file(self, sm, tmp_path):
        """恢复时若主目录已有同名残留（存档后在途写入），archived 版本为准覆盖。"""
        _seed_session(sm, "kai", "sess-e", ["2026-08-29"])
        sm.archive_session(agent_id="kai", session_id="sess-e")
        # 存档后主目录意外出现同名新文件（模拟在途写入复活）
        stale = tmp_path / "sessions" / "kai" / "session_sess-e_2026-08-29.json"
        stale.write_text(json.dumps({"session_id": "sess-e", "title": "复活残留"}), encoding="utf-8")

        assert sm.unarchive_session(agent_id="kai", session_id="sess-e") is True
        restored = json.loads(stale.read_text(encoding="utf-8"))
        assert restored.get("title") == "会话 sess-e", "恢复应以 archived 版本覆盖主目录残留"
