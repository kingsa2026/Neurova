"""S1 双写冲突 RED 测试

Bug (Critical #1): console.py + post_chat_pipeline 各自独立写 session 文件,
单次对话后 messages 数组含 4 条 [user, user, assistant, assistant],而非 2 条.

链路 (BUG 状态):
  Step 1: console.py:125 repo.save_message(role="user")   → 文件: [user]
  Step 2: pipeline _step_save_session → sm.add_message()   → 文件: [user, user, assistant]
  Step 3: console.py:165 repo.save_message(role="assistant") → 文件: [user, user, assistant, assistant]

修复策略: 保留 pipeline 写入 (成对原子),删除 console.py 的 2 处 save_message.
  - pipeline 的 add_message 是原子配对写入,语义更正确
  - console 不再独立持久化,只负责调用 agent.chat
  - 历史恢复仍由 pipeline._restore_session_history 负责 (读 session 文件)
  - console 的 SSE event_stream 仍可使用变量 reply/tool_messages (从 agent.chat 返回值取)

参考: ADR 0008 候选 #1 (删除 _CHAT_SESSIONS,console 接入 SessionRepository)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def isolated_sessions_dir(tmp_path, monkeypatch):
    """隔离的临时 sessions 目录,避免污染项目数据.

    通过 monkeypatch Path("sessions") 让 SessionManager 把文件写到 tmp_path/sessions.
    同时重置单例,确保每次测试拿到干净实例.
    """
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    # 重置 SessionManager 单例
    from neurova.session_manager import SessionManager

    SessionManager._instance = None

    # 重置 session_repository 工厂缓存
    from neurova import session_repository

    monkeypatch.setattr(session_repository, "_repository_instance", None)

    # 让 SessionManager._sessions_dir 指向 tmp_path/sessions
    # 通过 patch Path() 让 SessionManager.__init__ 中的 Path("sessions") 返回我们的临时目录
    original_path = Path

    def fake_path(p):
        if p == "sessions":
            return sessions_dir
        return original_path(p)

    monkeypatch.setattr("neurova.session_manager.Path", fake_path)

    yield sessions_dir

    # 清理:重置单例,避免影响后续测试
    SessionManager._instance = None


@pytest.fixture
def app_client(isolated_sessions_dir):
    """TestClient with mocked agent that simulates pipeline's session save.

    模拟 agent.chat 内部调用 sm.add_message (paired write),
    就像真实 ChatPipeline._step_save_session → _save_to_session → sm.add_message 一样.
    若 console 也调 save_message,文件最终会有 4 条消息 (BUG).
    """
    from neurova.api.endpoints import console as console_mod

    app = FastAPI()
    app.include_router(console_mod.router, prefix="/api/v1/console")

    # /chat 端点现在要求认证（Depends(get_current_user)）；本测试验证的是
    # 会话不双写，与认证无关——override 掉认证依赖
    from neurova.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "1",
        "username": "test",
        "role": "admin",
    }

    async def mock_chat(message, stream=False, session_id=None, metadata=None, model=None):
        """模拟 pipeline 的 add_message 调用 (paired user+assistant write)."""
        from neurova.session_repository import get_session_repository

        repo = get_session_repository()
        # 与 mem_core.py:758 sm.add_message(agent_id=..., user_content=..., assistant_content=...) 一致
        repo.add_message(
            agent_id="default",
            session_id=session_id,
            user_content=message,
            assistant_content="mock reply",
        )
        return {"text": "mock reply", "tool_messages": [], "reasoning": None}

    mock_agent = MagicMock()
    mock_agent.chat = mock_chat

    with patch("neurova.api.endpoints.console.get_agent_instance", return_value=mock_agent):
        client = TestClient(app)
        yield client


def _read_session_messages(sessions_dir: Path, agent_id: str, session_id: str) -> list:
    """读取指定 session 的 messages 数组."""
    today = datetime.now().strftime("%Y-%m-%d")
    session_file = sessions_dir / agent_id / f"session_{session_id}_{today}.json"
    assert session_file.exists(), f"Session file not created: {session_file}"
    data = json.loads(session_file.read_text(encoding="utf-8"))
    return data.get("messages", [])


# ── Behavior contracts ─────────────────────────────────


class TestConsoleChatNoDoubleWrite:
    """S1: 单次 console chat 后 session 文件应只有 1 user + 1 assistant.

    Bug: 当前为 [user, user, assistant, assistant] (4 条)
    Fixed: 应为 [user, assistant] (2 条)
    """

    def test_messages_count_exactly_two(self, app_client, isolated_sessions_dir):
        """RED: 修复后 messages 长度应 == 2, 不是 4.

        pipeline 的 add_message 已写入 [user, assistant],
        console 不应再调 save_message 重复写入.
        """
        # Act: 单次 chat
        response = app_client.post(
            "/api/v1/console/chat",
            json={"message": "hi", "session_id": "test-sid-001", "agent_id": "default"},
        )
        assert response.status_code == 200, f"Chat failed: {response.text}"

        # Assert: session 文件 messages 数组
        messages = _read_session_messages(isolated_sessions_dir, "default", "test-sid-001")
        assert len(messages) == 2, (
            f"Expected exactly 2 messages [user, assistant], got {len(messages)}: "
            f"{[m.get('role') for m in messages]}. "
            f"BUG: console + pipeline 双写导致重复消息."
        )

    def test_messages_role_sequence(self, app_client, isolated_sessions_dir):
        """RED: role 序列应为 [user, assistant], 不是 [user, user, assistant, assistant]."""
        response = app_client.post(
            "/api/v1/console/chat",
            json={"message": "hi", "session_id": "test-sid-002", "agent_id": "default"},
        )
        assert response.status_code == 200

        messages = _read_session_messages(isolated_sessions_dir, "default", "test-sid-002")
        roles = [m["role"] for m in messages]

        assert roles == ["user", "assistant"], (
            f"Expected role sequence [user, assistant], got {roles}. "
            f"BUG: console 在 pipeline 之外重复 save_message 导致 role 序列重复."
        )

    def test_no_duplicate_content(self, app_client, isolated_sessions_dir):
        """RED: 同一 role 不应出现重复 content (user 消息内容不应重复)."""
        response = app_client.post(
            "/api/v1/console/chat",
            json={"message": "unique-question-xyz", "session_id": "test-sid-003", "agent_id": "default"},
        )
        assert response.status_code == 200

        messages = _read_session_messages(isolated_sessions_dir, "default", "test-sid-003")
        user_messages = [m for m in messages if m["role"] == "user"]
        assistant_messages = [m for m in messages if m["role"] == "assistant"]

        assert len(user_messages) == 1, f"Expected 1 user message, got {len(user_messages)}"
        assert len(assistant_messages) == 1, f"Expected 1 assistant message, got {len(assistant_messages)}"


# ── Static contract (surgical changes 验证) ─────────────


class TestConsoleChatNoDirectSaveMessage:
    """S1 静态契约: console.post_console_chat 源码不应再调用 repo.save_message.

    持久化完全委托给 pipeline._step_save_session (用 add_message 成对原子写).
    """

    def test_post_console_chat_source_no_save_message_call(self):
        """RED: post_console_chat 函数源码不应包含 repo.save_message 调用."""
        import inspect

        from neurova.api.endpoints import console as console_mod

        source = inspect.getsource(console_mod.post_console_chat)
        # 允许出现在注释中,但不应作为实际调用
        # 通过查找 "repo.save_message(" 模式 (实际调用语法)
        assert "repo.save_message(" not in source, (
            "post_console_chat 不应再调用 repo.save_message — "
            "持久化由 pipeline._step_save_session (sm.add_message) 负责. "
            "console 双写会导致 session 文件含 [user, user, assistant, assistant] 重复消息."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
