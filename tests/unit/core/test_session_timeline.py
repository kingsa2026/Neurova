# -*- coding: utf-8 -*-
"""P1-2 会话时间线 JSONL（追加流）+ 读取 + 删除联动。

- append-only JSONL（<sessions>/<agent>/_timeline/<sid>.jsonl），逐事件一行
- 读取容错：坏行跳过不炸；limit 取最近 N 条（重放语义）
- delete_session 联动清理时间线（不留孤儿文件）
"""
import json

import pytest


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    from neurova.session_manager import SessionManager

    # 单例 + env 覆盖通道（NEUROVA_SESSIONS_DIR 是官方测试隔离口）
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    mgr = SessionManager()
    yield mgr
    SessionManager._instance = None


class TestSessionTimeline:
    def test_append_and_read_roundtrip(self, sm, tmp_path):
        agent = "a1"
        sid = sm.create_session(agent_id=agent, user_id="u1")
        assert sm.append_timeline_event(agent, sid, {"type": "chunk", "content": "hello"})
        assert sm.append_timeline_event(agent, sid, {"type": "tool_call", "name": "x"})
        events = sm.read_timeline(agent, sid)
        assert [e["type"] for e in events] == ["chunk", "tool_call"]
        assert events[0]["content"] == "hello"

    def test_read_limit_returns_latest(self, sm):
        agent = "a1"
        sid = sm.create_session(agent_id=agent)
        for i in range(5):
            sm.append_timeline_event(agent, sid, {"type": "chunk", "content": str(i)})
        events = sm.read_timeline(agent, sid, limit=2)
        assert [e["content"] for e in events] == ["3", "4"]

    def test_missing_timeline_returns_empty(self, sm):
        agent = "a1"
        sid = sm.create_session(agent_id=agent)
        assert sm.read_timeline(agent, sid) == []

    def test_corrupt_lines_skipped(self, sm):
        agent = "a1"
        sid = sm.create_session(agent_id=agent)
        sm.append_timeline_event(agent, sid, {"type": "chunk", "content": "ok"})
        tl = sm._get_timeline_file(agent, sid)
        with open(tl, "a", encoding="utf-8") as f:
            f.write("{broken json\n")
            f.write("not-json-at-all\n")
        sm.append_timeline_event(agent, sid, {"type": "done"})
        events = sm.read_timeline(agent, sid)
        assert [e["type"] for e in events] == ["chunk", "done"]

    def test_jsonl_file_format(self, sm):
        agent = "a1"
        sid = sm.create_session(agent_id=agent)
        sm.append_timeline_event(agent, sid, {"type": "chunk", "content": "x"})
        tl = sm._get_timeline_file(agent, sid)
        assert tl.suffix == ".jsonl"
        lines = tl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["type"] == "chunk"

    def test_delete_session_removes_timeline(self, sm):
        agent = "a1"
        sid = sm.create_session(agent_id=agent)
        sm.append_timeline_event(agent, sid, {"type": "chunk", "content": "x"})
        tl = sm._get_timeline_file(agent, sid)
        assert tl.exists()
        assert sm.delete_session(agent, sid) is True
        assert not tl.exists()

    def test_append_failure_fail_open(self, sm, monkeypatch):
        """时间线写失败不影响主链路（返回 False，不抛异常）。"""
        agent = "a1"
        sid = sm.create_session(agent_id=agent)
        tl_dir = sm._get_timeline_file(agent, sid).parent
        tl_dir.mkdir(parents=True, exist_ok=True)
        tl_file = sm._get_timeline_file(agent, sid)
        tl_file.mkdir()  # 占位成目录 → 写入必失败
        assert sm.append_timeline_event(agent, sid, {"type": "chunk"}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
