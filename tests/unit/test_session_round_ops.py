"""红绿灯 TDD：SessionManager 轮次操作（删除一轮 / 消息 metadata 补丁）。

支撑前端 chat 页面三个新能力：
1. 编辑最后一条用户消息 = 删除旧轮 + 原链路重发（覆写 session/上下文/记忆）
2. 删除任意一轮记录（user+assistant 对，或流式中断留下的孤立尾 user 消息）
3. 点赞/点踩反馈持久化到消息 metadata

轮次定位键：msg.timestamp（后端写入）或 msg.metadata.client_timestamp
（前端发送时携带、随 metadata 持久化），双路定位解决实时轮次
"客户端时间戳未落盘"的定位失败问题。
"""
from __future__ import annotations

import time

import pytest

from neurova.session_manager import SessionManager


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """隔离 CWD 的 SessionManager（sessions/ 目录相对 CWD）。

    SessionManager 是单例，__init__ 只在首个用例的 tmp_path 创建过
    sessions/ 目录；后续用例 chdir 到新 tmp_path 后需手动补建父目录。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sessions").mkdir(exist_ok=True)
    return SessionManager()


def _add_round(sm, agent_id, session_id, q, a, date=None, metadata=None):
    kw = {} if date is None else {"date": date}
    return sm.add_message(
        agent_id=agent_id,
        session_id=session_id,
        user_content=q,
        assistant_content=a,
        metadata=metadata,
        **kw,
    )


def _history(sm, agent_id, session_id):
    return sm.get_history(agent_id=agent_id, session_id=session_id)


class TestDeleteRound:
    def test_removes_user_assistant_pair(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        time.sleep(0.01)
        _add_round(sm, "a1", "s1", "Q2", "A2")

        history = _history(sm, "a1", "s1")
        first_user_ts = history[0]["timestamp"]

        deleted = sm.delete_round(agent_id="a1", session_id="s1", timestamp=first_user_ts)

        assert [m["content"] for m in deleted] == ["Q1", "A1"]
        remaining = _history(sm, "a1", "s1")
        assert [m["content"] for m in remaining] == ["Q2", "A2"]

    def test_lone_trailing_user_message(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        time.sleep(0.01)
        # 流式中断场景：只有 user 消息落盘（save_message 单条写入）
        sm.save_message(agent_id="a1", session_id="s1", role="user", content="Q2-only")
        lone_ts = _history(sm, "a1", "s1")[-1]["timestamp"]

        deleted = sm.delete_round(agent_id="a1", session_id="s1", timestamp=lone_ts)

        assert [m["content"] for m in deleted] == ["Q2-only"]
        remaining = _history(sm, "a1", "s1")
        assert [m["content"] for m in remaining] == ["Q1", "A1"]

    def test_locates_by_metadata_client_timestamp(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        time.sleep(0.01)
        # 实时轮次：前端 client_timestamp 随 metadata 持久化到两条消息
        _add_round(
            sm, "a1", "s1", "Q2", "A2",
            metadata={"client_timestamp": "2026-08-29T10:00:00.123+08:00"},
        )

        deleted = sm.delete_round(
            agent_id="a1", session_id="s1", timestamp="2026-08-29T10:00:00.123+08:00"
        )

        assert [m["content"] for m in deleted] == ["Q2", "A2"]
        assert [m["content"] for m in _history(sm, "a1", "s1")] == ["Q1", "A1"]

    def test_spans_multiple_date_files(self, sm):
        _add_round(sm, "a1", "s1", "Q-old", "A-old", date="2026-08-27")
        time.sleep(0.01)
        _add_round(sm, "a1", "s1", "Q-new", "A-new")  # 今天

        old_ts = sm.get_history(agent_id="a1", session_id="s1")[0]["timestamp"]
        deleted = sm.delete_round(agent_id="a1", session_id="s1", timestamp=old_ts)

        assert [m["content"] for m in deleted] == ["Q-old", "A-old"]
        assert [m["content"] for m in _history(sm, "a1", "s1")] == ["Q-new", "A-new"]

    def test_missing_timestamp_returns_empty_and_keeps_file(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")

        deleted = sm.delete_round(agent_id="a1", session_id="s1", timestamp="1999-01-01T00:00:00")

        assert deleted == []
        assert [m["content"] for m in _history(sm, "a1", "s1")] == ["Q1", "A1"]


class TestUpdateMessageMetadata:
    def test_merges_patch_into_assistant_message(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        ts = _history(sm, "a1", "s1")[0]["timestamp"]  # 同轮同戳

        ok = sm.update_message_metadata(
            agent_id="a1", session_id="s1", timestamp=ts,
            metadata_patch={"feedback": "like"}, role="assistant",
        )

        assert ok is True
        msgs = _history(sm, "a1", "s1")
        assert msgs[0].get("metadata") is None or "feedback" not in (msgs[0].get("metadata") or {})
        assert msgs[1]["metadata"]["feedback"] == "like"

    def test_preserves_existing_metadata_keys(self, sm):
        sm.save_message(
            agent_id="a1", session_id="s1", role="assistant", content="A1",
            metadata={"reasoning_content": " thinking..."},
        )
        ts = _history(sm, "a1", "s1")[0]["timestamp"]

        sm.update_message_metadata(
            agent_id="a1", session_id="s1", timestamp=ts,
            metadata_patch={"feedback": "dislike"}, role="assistant",
        )

        meta = _history(sm, "a1", "s1")[0]["metadata"]
        assert meta["reasoning_content"] == " thinking..."
        assert meta["feedback"] == "dislike"

    def test_feedback_can_be_cleared_with_none_value(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        ts = _history(sm, "a1", "s1")[0]["timestamp"]
        sm.update_message_metadata(
            agent_id="a1", session_id="s1", timestamp=ts,
            metadata_patch={"feedback": "like"}, role="assistant",
        )

        sm.update_message_metadata(
            agent_id="a1", session_id="s1", timestamp=ts,
            metadata_patch={"feedback": None}, role="assistant",
        )

        assert _history(sm, "a1", "s1")[1]["metadata"]["feedback"] is None

    def test_missing_message_returns_false(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        ok = sm.update_message_metadata(
            agent_id="a1", session_id="s1", timestamp="1999-01-01T00:00:00",
            metadata_patch={"feedback": "like"}, role="assistant",
        )
        assert ok is False


class TestGetRound:
    def test_returns_user_and_assistant_contents(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        ts = _history(sm, "a1", "s1")[0]["timestamp"]

        round_data = sm.get_round(agent_id="a1", session_id="s1", timestamp=ts)

        assert round_data["user"]["content"] == "Q1"
        assert round_data["assistant"]["content"] == "A1"

    def test_locates_by_metadata_client_timestamp(self, sm):
        _add_round(
            sm, "a1", "s1", "Q1", "A1",
            metadata={"client_timestamp": "2026-08-29T10:00:00+08:00"},
        )

        round_data = sm.get_round(
            agent_id="a1", session_id="s1", timestamp="2026-08-29T10:00:00+08:00"
        )

        assert round_data["user"]["content"] == "Q1"
        assert round_data["assistant"]["content"] == "A1"

    def test_lone_user_message_returns_none_assistant(self, sm):
        sm.save_message(agent_id="a1", session_id="s1", role="user", content="Q-only")
        ts = _history(sm, "a1", "s1")[0]["timestamp"]

        round_data = sm.get_round(agent_id="a1", session_id="s1", timestamp=ts)

        assert round_data is not None
        assert round_data["user"]["content"] == "Q-only"
        assert round_data["assistant"] is None

    def test_missing_timestamp_returns_none(self, sm):
        _add_round(sm, "a1", "s1", "Q1", "A1")
        assert sm.get_round(agent_id="a1", session_id="s1", timestamp="1999-01-01T00:00:00") is None
