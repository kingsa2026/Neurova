"""
测试：session_manager JSON 安全 — 会话持久化防损坏

根因背景（2026-08-28 线上诊断）:
console SSE 桥接（neurova/api/endpoints/console.py event_stream）把
event_emitter（Python 函数）注入 chat metadata，metadata 经
PostChatPipeline._step_save_session → MemCore.save_to_session →
SessionManager.add_message 原样流到 json.dump，抛 TypeError；
而 _write_session_file_unlocked 先以 "w" 模式截断文件再序列化，
导致 session 文件被截断成非法 JSON（历史丢失 + 后续读取 JSONDecodeError）。

本文件验证持久化边界的两层防御:
1. add_message 净化 metadata 中不可 JSON 序列化的值
   （丢弃 callable，保留合法字段），写入成功且文件合法。
2. _write_session_file_unlocked 先序列化成字符串再写文件:
   任何序列化失败都不得触碰/截断已有文件内容。
"""

import json
from pathlib import Path

from neurova.session_manager import SessionManager


# ---------------------------------------------------------------------------
# 辅助函数（与 test_session_manager.py 保持一致的 tmp 目录隔离模式）
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path) -> SessionManager:
    """创建 SessionManager 并 patch _get_session_dir 指向 tmp_path。"""
    mgr = SessionManager()

    def _fake_dir(agent_id_arg):
        d = tmp_path / "agents" / agent_id_arg / "session"
        d.mkdir(parents=True, exist_ok=True)
        return d

    mgr._get_session_dir = _fake_dir
    return mgr


def _console_style_metadata() -> dict:
    """模拟 console.py event_stream 注入的运行时 metadata。

    event_emitter 是函数（SSE 队列回调），emit_tool_events 是布尔开关，
    两者都只应在运行时存在，不可进入持久化层。
    """

    def _emit(kind, data):  # noqa: ANN001 - 模拟 SSE 发射器
        return (kind, data)

    return {
        "user_id": "anonymous",
        "thinking_effort": "",
        "event_emitter": _emit,
        "emit_tool_events": True,
    }


# ======================================================
# 1. add_message 对含 callable 的 metadata 的容错
# ======================================================

class TestAddMessageMetadataSanitization:
    """add_message 必须能安全持久化含运行时对象的 metadata"""

    def test_add_message_with_callable_metadata_does_not_raise(self, tmp_path):
        """含函数的 metadata 不得使 add_message 抛异常（现状: TypeError→IOError）"""
        mgr = _make_manager(tmp_path)
        session_id = mgr.add_message(
            agent_id="default",
            session_id="s-json-1",
            user_content="现在几点了？",
            assistant_content="下午三点。",
            metadata=_console_style_metadata(),
        )
        assert session_id

        file_path = mgr._get_session_file("default", "s-json-1", None)
        assert file_path.exists()
        # 文件必须是合法 JSON（现状: 截断在 "event_emitter": 处）
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["total_messages"] == 2

    def test_callable_dropped_but_serializable_fields_kept(self, tmp_path):
        """净化只丢不可序列化值，合法字段（user_id 等）必须完整保留"""
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            agent_id="default",
            session_id="s-json-2",
            user_content="hi",
            assistant_content="hello",
            metadata=_console_style_metadata(),
        )
        file_path = mgr._get_session_file("default", "s-json-2", None)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        user_msg = data["messages"][0]
        saved_meta = user_msg.get("metadata") or {}
        assert saved_meta.get("user_id") == "anonymous"
        assert saved_meta.get("emit_tool_events") is True
        assert "event_emitter" not in saved_meta, "callable 不得进入持久化层"

    def test_nested_callable_sanitized(self, tmp_path):
        """嵌套结构中的 callable 也要被清理，同级合法值保留"""
        mgr = _make_manager(tmp_path)
        mgr.add_message(
            agent_id="default",
            session_id="s-json-3",
            user_content="u",
            assistant_content="a",
            metadata={"outer": {"fn": lambda: None, "keep": 42}, "top": "ok"},
        )
        file_path = mgr._get_session_file("default", "s-json-3", None)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        saved_meta = data["messages"][0]["metadata"]
        assert saved_meta["outer"] == {"keep": 42}
        assert saved_meta["top"] == "ok"

    def test_plain_metadata_preserved_verbatim(self, tmp_path):
        """纯 JSON 原生 metadata 不得被净化逻辑改动"""
        mgr = _make_manager(tmp_path)
        meta = {
            "user_id": "u1",
            "count": 3,
            "ratio": 0.5,
            "ok": True,
            "none": None,
            "tags": ["a", "b"],
            "nested": {"x": 1},
        }
        mgr.add_message(
            agent_id="default",
            session_id="s-json-4",
            user_content="u",
            assistant_content="a",
            metadata=meta,
        )
        file_path = mgr._get_session_file("default", "s-json-4", None)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["messages"][0]["metadata"] == meta


# ======================================================
# 2. _write_session_file_unlocked 序列化失败不得损坏已有文件
# ======================================================

class TestWriteAtomicity:
    """写入层防御: 序列化失败时已有文件内容必须原封不动"""

    def test_unserializable_data_does_not_corrupt_existing_file(self, tmp_path):
        mgr = _make_manager(tmp_path)
        # 先写入一份合法会话
        mgr.add_message(
            agent_id="default",
            session_id="s-atomic-1",
            user_content="第一条",
            assistant_content="回复",
        )
        file_path = mgr._get_session_file("default", "s-atomic-1", None)
        before = file_path.read_text(encoding="utf-8")
        json.loads(before)  # 前置断言: 写入前文件合法

        # 直接以不可序列化数据调用写入（模拟任何未来调用方传脏数据）
        ok = mgr._write_session_file_unlocked(file_path, {"bad": object()})
        assert ok is False

        after = file_path.read_text(encoding="utf-8")
        assert after == before, "序列化失败不得截断/污染已有文件"
        json.loads(after)  # 文件仍为合法 JSON

    def test_serializable_write_still_works(self, tmp_path):
        """正常写入路径不受防御逻辑影响"""
        mgr = _make_manager(tmp_path)
        file_path = tmp_path / "direct.json"
        ok = mgr._write_session_file_unlocked(file_path, {"a": 1, "b": ["x"]})
        assert ok is True
        assert json.loads(file_path.read_text(encoding="utf-8")) == {"a": 1, "b": ["x"]}
