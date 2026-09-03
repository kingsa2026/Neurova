"""ACP server 数据类与服务单元测试（对齐真实实现）。

真实 API（neurova/core/acp_server.py）：
    枚举：ACPSessionStatus / ACPMessageRole / ACPStreamEventType
    数据类：ACPMessage / ACPStreamChunk / ACPToolCall(tool_name, arguments) /
            ACPToolResult / ACPThinkingStep(step_type, content) / ACPModelConfig /
            ACPSessionConfig(无 model_id，仅 to_dict) / ACPSession(session_id,user_id,model_config)
    ACPServer：create_session(user_id,...) async / load_session / close_session /
            get_session_status / switch_model async / get_available_models /
            detect_model_capabilities / update_session_config async / get_session_config /
            list_sessions。缺失会话/模型时抛 fastapi HTTPException(404/400)。
    默认模型：default / gpt4 / claude。
"""

import pytest
from fastapi import HTTPException

from neurova.core.acp_server import (
    ACPMessage,
    ACPMessageRole,
    ACPModelConfig,
    ACPServer,
    ACPSession,
    ACPSessionConfig,
    ACPSessionStatus,
    ACPStreamChunk,
    ACPStreamEventType,
    ACPThinkingStep,
    ACPToolCall,
    ACPToolResult,
)


@pytest.fixture
def server():
    return ACPServer()


@pytest.fixture
def model_config():
    return ACPModelConfig(model_id="m1", model_name="Model One", provider="openai")


class TestDataclasses:
    def test_tool_call_fields_and_to_dict(self):
        tc = ACPToolCall(tool_name="search", arguments={"q": "x"})
        d = tc.to_dict()
        assert d["tool_name"] == "search"
        assert d["arguments"] == {"q": "x"}
        assert "call_id" in d

    def test_tool_result_with_error(self):
        tr = ACPToolResult(call_id="c1", result=None, success=False, error="boom")
        d = tr.to_dict()
        assert d["success"] is False
        assert d["error"] == "boom"

    def test_thinking_step_fields(self):
        step = ACPThinkingStep(step_type="reasoning", content="thinking...")
        d = step.to_dict()
        assert d["step_type"] == "reasoning"
        assert d["content"] == "thinking..."

    def test_message_to_dict(self):
        msg = ACPMessage(role=ACPMessageRole.USER, content="hi")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "hi"

    def test_stream_chunk_to_sse(self):
        chunk = ACPStreamChunk(event_type=ACPStreamEventType.TEXT_DELTA, data="x")
        sse = chunk.to_sse()
        assert sse.startswith("event: text_delta")

    def test_session_config_defaults(self):
        cfg = ACPSessionConfig()
        assert cfg.auto_save is True
        assert cfg.stream_enabled is True
        assert cfg.max_context_length == 8192

    def test_session_config_to_dict(self):
        cfg = ACPSessionConfig(system_prompt="sp")
        assert cfg.to_dict()["system_prompt"] == "sp"

    def test_session_to_dict(self, model_config):
        session = ACPSession(session_id="s1", user_id="u1", model_config=model_config)
        d = session.to_dict()
        assert d["session_id"] == "s1"
        assert d["user_id"] == "u1"
        assert d["model_config"]["model_id"] == "m1"


class TestEnums:
    def test_stream_event_type_members(self):
        assert {m.value for m in ACPStreamEventType} == {
            "text_delta", "tool_call", "tool_result", "thinking", "error", "done",
        }

    def test_session_status_members(self):
        assert {m.value for m in ACPSessionStatus} == {
            "created", "active", "paused", "closed", "error",
        }

    def test_message_role_members(self):
        assert {m.value for m in ACPMessageRole} == {"user", "assistant", "system", "tool"}


class TestACPServerSessions:
    @pytest.mark.asyncio
    async def test_create_session(self, server):
        result = await server.create_session(user_id="u1", system_prompt="sp")
        assert result["user_id"] == "u1"
        assert result["status"] == "active"
        assert result["session_id"]

    @pytest.mark.asyncio
    async def test_load_session_and_missing(self, server):
        result = await server.create_session(user_id="u1")
        session = server.load_session(result["session_id"])
        assert session is not None
        assert server.load_session("nope") is None

    @pytest.mark.asyncio
    async def test_close_session(self, server):
        result = await server.create_session(user_id="u1")
        close = server.close_session(result["session_id"])
        assert close["success"] is True
        assert server.load_session(result["session_id"]).status == ACPSessionStatus.CLOSED

    def test_close_nonexistent_raises(self, server):
        with pytest.raises(HTTPException):
            server.close_session("nope")

    @pytest.mark.asyncio
    async def test_get_session_status(self, server):
        result = await server.create_session(user_id="u1")
        status = server.get_session_status(result["session_id"])
        assert status["status"] == "active"
        assert "message_count" in status

    def test_get_session_status_missing_raises(self, server):
        with pytest.raises(HTTPException):
            server.get_session_status("nope")

    @pytest.mark.asyncio
    async def test_list_sessions(self, server):
        await server.create_session(user_id="u1")
        sessions = server.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["user_id"] == "u1"


class TestACPServerModels:
    def test_get_available_models(self, server):
        ids = {m["model_id"] for m in server.get_available_models()}
        assert {"default", "gpt4", "claude"} <= ids

    @pytest.mark.asyncio
    async def test_switch_model(self, server):
        result = await server.create_session(user_id="u1")
        switch = await server.switch_model(result["session_id"], "gpt4")
        assert switch["success"] is True
        assert switch["new_model"] == "GPT-4"

    @pytest.mark.asyncio
    async def test_switch_to_nonexistent_model_raises(self, server):
        result = await server.create_session(user_id="u1")
        with pytest.raises(HTTPException):
            await server.switch_model(result["session_id"], "nope")

    def test_detect_model_capabilities(self, server):
        caps = server.detect_model_capabilities("gpt4")
        assert caps["model_id"] == "gpt4"
        assert "reasoning" in caps["capabilities"]

    def test_detect_capabilities_missing_raises(self, server):
        with pytest.raises(HTTPException):
            server.detect_model_capabilities("nope")


class TestACPServerConfig:
    @pytest.mark.asyncio
    async def test_update_and_get_session_config(self, server):
        result = await server.create_session(user_id="u1")
        sid = result["session_id"]
        update = await server.update_session_config(sid, {"thinking_visible": False})
        assert update["success"] is True
        cfg = server.get_session_config(sid)
        assert cfg["thinking_visible"] is False

    def test_get_session_config_missing_raises(self, server):
        with pytest.raises(HTTPException):
            server.get_session_config("nope")
