"""
测试：会话持久化须保留 assistant 专属元数据（reasoning 思考过程）

根因（R-2）: post_chat_pipeline._step_save_session 已构造
assistant_meta = {"reasoning_content": ...} 并经 _save_to_session →
mem_core.save_to_session 传递，但 save_to_session 调用
sm.add_message(...) 时只传 metadata（用户元数据），assistant_metadata
参数被静默丢弃；session_manager.add_message 本身也只给两条消息写同一份
metadata，导致 assistant 消息的 reasoning 永不落盘 → 切换页面重新打开
会话后思考过程不显示。

修复契约：
  1. add_message 支持 assistant_metadata 参数，仅写入 assistant 消息；
     metadata 仍只写入 user 消息（保持既有语义，user/assistant 同元数据
     的旧行为不变——调用方不传 assistant_metadata 时二者仍共享）。
  2. get_history / get_session 回读时 assistant 消息携带 reasoning_content。
"""

import json
from pathlib import Path

from neurova.session_manager import SessionManager


def _make_manager(tmp_path: Path) -> SessionManager:
    mgr = SessionManager()

    def _fake_dir(agent_id_arg):
        d = tmp_path / "agents" / agent_id_arg / "session"
        d.mkdir(parents=True, exist_ok=True)
        return d

    mgr._get_session_dir = _fake_dir
    return mgr


class TestAssistantMetadataPersist:
    """assistant_metadata 必须写入 assistant 消息并可从历史回读"""

    def test_add_message_assistant_metadata_written(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            "agent_a", "sess_rs_01", "hi", "hello",
            assistant_metadata={"reasoning_content": "我在思考"},
        )

        record = mgr.get_session("agent_a", "sess_rs_01")
        assert record is not None
        user_msg, asst_msg = record.messages[0], record.messages[1]

        # assistant 消息携带思考过程
        asst_meta = asst_msg.metadata or {}
        assert asst_meta.get("reasoning_content") == "我在思考"

        # 复用"共享同一 metadata"惯例冲突不成立：不传 assistant_metadata
        # 时旧行为保持（本例传了，因此 user 消息不应携带 reasoning）
        user_meta = user_msg.metadata or {}
        assert "reasoning_content" not in user_meta

    def test_get_history_returns_reasoning(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            "agent_a", "sess_rs_02", "q", "a",
            assistant_metadata={"reasoning_content": "思考 A"},
        )
        history = mgr.get_history("agent_a", "sess_rs_02")
        assert len(history) == 2
        asst = history[1]
        assert asst["role"] == "assistant"
        assert (asst.get("metadata") or {}).get("reasoning_content") == "思考 A"

    def test_tool_calls_also_land_in_assistant_metadata(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            "agent_a", "sess_rs_03", "q", "a",
            assistant_metadata={"reasoning_content": "r", "tool_calls": [{"name": "calc"}]},
        )
        record = mgr.get_session("agent_a", "sess_rs_03")
        asst_meta = record.messages[1].metadata or {}
        assert asst_meta["reasoning_content"] == "r"
        assert asst_meta["tool_calls"] == [{"name": "calc"}]

    def test_no_assistant_metadata_keeps_legacy_shared_metadata(self, tmp_path):
        """不传 assistant_metadata 时维持旧行为：metadata 仍是双方共享。"""
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            "agent_a", "sess_rs_04", "hi", "hello",
            metadata={"client_timestamp": "t1"},
        )
        record = mgr.get_session("agent_a", "sess_rs_04")
        assert (record.messages[0].metadata or {}).get("client_timestamp") == "t1"
        assert (record.messages[1].metadata or {}).get("client_timestamp") == "t1"

    def test_persisted_file_contains_reasoning(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            "agent_a", "sess_rs_05", "q", "a",
            assistant_metadata={"reasoning_content": "归档后可见"},
        )
        session_dir = tmp_path / "agents" / "agent_a" / "session"
        files = list(session_dir.glob("session_sess_rs_05_*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        asst = [m for m in data["messages"] if m.get("role") == "assistant"][0]
        assert (asst.get("metadata") or {}).get("reasoning_content") == "归档后可见"
