"""
Session 文件损坏自愈 + WS 事件序列化兜底测试（2026-09-03）

背景（logs/server.log 持续两条 ERROR）：
1) "读取session文件失败: Expecting value: line 13 column 26 / line 1 column 1"
   —— 损坏/截断 session 文件每次读取都报错且永远失败；
2) "WebSocket send error: Object of type function is not JSON serializable"
   —— AGENT_REPLY 事件 payload 携带 function（event_emitter），事件入历史后
   WS 连接回放历史必炸。

契约：
1. 读侧：非法 JSON 文件被隔离（.corrupt-*.bak），返回 None，不重复报错；
2. 写侧：内容中途异常不触碰原文件；正常写入后无 .tmp 残留；
3. SessionEvent 含 callable payload 时 to_json 不抛异常，函数降级为字符串。
"""
import json
import os
import threading
from datetime import datetime

import pytest

os.environ["NEUROVA_SESSIONS_DIR"] = "sessions-test-quarantine"

from neurova.sync.session_sync_manager import SessionEvent, EventType, _json_safe
from neurova.session_manager import SessionManager


@pytest.fixture
def sm(tmp_path):
    """隔离单例：env 是 SessionManager 单例唯一的测试隔离通道。"""
    os.environ["NEUROVA_SESSIONS_DIR"] = str(tmp_path / "sessions")
    SessionManager._instances = {} if hasattr(SessionManager, "_instances") else None
    # 单例 __new__ 缓存重置（防御性：若实现有变直接 new 一个）
    inst = object.__new__(SessionManager)
    inst.__init__()
    yield inst


class TestSessionEventJsonSafe:
    def test_callable_payload_does_not_break_to_json(self):
        def emitter(*args, **kwargs):
            return args

        event = SessionEvent(
            event_type=EventType.USER_MESSAGE,
            session_id="s1",
            source_channel="agent",
            payload={"metadata": {"event_emitter": emitter, "user_id": "u1"}},
        )
        text = event.to_json()
        data = json.loads(text)
        assert data["payload"]["metadata"]["user_id"] == "u1"
        # callable 降级为字符串描述，不再包含函数对象
        assert callable(data["payload"]["metadata"]["event_emitter"]) is False
        assert "<" in data["payload"]["metadata"]["event_emitter"]
        assert "user_message" in data["event_type"]

    def test_nested_unserializable_fallback_to_str(self):
        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            session_id="s2",
            source_channel="agent",
            payload={"obj": object()},
        )
        data = json.loads(event.to_json())
        assert data["payload"]["obj"].startswith("<")


class TestSessionQuarantine:
    def test_invalid_json_quarantined_and_returns_none(self, sm, tmp_path):
        target = tmp_path / "sessions" / "agent_xyz_session_s1_2026-09-03.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"messages": [{"role": "user",', encoding="utf-8")

        result = sm._read_session_file(target)

        assert result is None
        # 损坏文件被改名隔离，原路径不再存在（后续请求不再重复报错）
        assert not target.exists()
        quarantined = list(target.parent.glob("*.corrupt-*.bak"))
        assert len(quarantined) == 1

    def test_empty_file_quarantined(self, sm, tmp_path):
        target = tmp_path / "sessions" / "agent_xyz_session_s2_2026-09-03.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")

        assert sm._read_session_file(target) is None
        assert not target.exists()
        assert len(list(target.parent.glob("*.corrupt-*.bak"))) == 1

    def test_valid_file_untouched(self, sm, tmp_path):
        target = tmp_path / "sessions" / "agent_xyz_session_s3_2026-09-03.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        good = {"messages": [], "updated_at": "2026-09-03T00:00:00"}
        target.write_text(json.dumps(good), encoding="utf-8")

        assert sm._read_session_file(target) == good
        assert target.exists()
        assert not list(target.parent.glob("*.corrupt-*.bak"))


class TestAtomicWrite:
    def test_write_produces_valid_json_and_no_tmp_residue(self, sm, tmp_path):
        target = tmp_path / "sessions" / "agent_xyz_session_s4_2026-09-03.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {"messages": [{"role": "user", "content": "你好"}], "updated_at": "now"}

        assert sm._write_session_file_unlocked(target, data) is True
        assert json.loads(target.read_text(encoding="utf-8")) == data
        assert not list(target.parent.glob("*.tmp")), "原子写后不得残留 tmp 文件"

    def test_nonserializable_data_does_not_touch_existing_file(self, sm, tmp_path):
        target = tmp_path / "sessions" / "agent_xyz_session_s5_2026-09-03.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = {"messages": ["内容", "保留"]}
        target.write_text(json.dumps(existing), encoding="utf-8")

        bad = {"fn": lambda: 1}
        assert sm._write_session_file_unlocked(target, bad) is False
        assert json.loads(target.read_text(encoding="utf-8")) == existing
