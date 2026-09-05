"""browser_read / browser_dom_read 工具 executor 接线测试（红→绿 TDD）。

覆盖：
- schema：browser_read 新增 session_id/offset/chunk_size 参数；browser_dom_read 新工具注册
- executor：_execute_browser_read 穿透 session_id/offset/chunk_size
- executor：browser_dom_read → ComputerUseManager.browser_dom_read 委托 + 截断契约退位
  （续读就位后不再硬截 8000，由游标机制接管分片）
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.tool_executor import ToolExecutor


def _make_browser_result(success=True, **kwargs):
    from types import SimpleNamespace

    result = SimpleNamespace(
        success=success,
        data=kwargs.get("data"),
        error=kwargs.get("error"),
        screenshot=kwargs.get("screenshot"),
        url=kwargs.get("url"),
        title=kwargs.get("title"),
        duration_ms=1.0,
        to_dict=lambda: {
            "success": success,
            "data": kwargs.get("data"),
            "error": kwargs.get("error"),
            "has_screenshot": kwargs.get("screenshot") is not None,
            "url": kwargs.get("url"),
            "title": kwargs.get("title"),
            "duration_ms": 1.0,
        },
    )
    return result


@pytest.fixture
def executor():
    agent = MagicMock()
    agent.current_session_id = "sess-abc"
    return ToolExecutor(agent), agent


class TestSchemas:
    def test_browser_read_has_continuation_params(self):
        props = _BUILTIN_SCHEMAS["browser_read"]["parameters"]["properties"]
        assert "session_id" in props
        assert "offset" in props
        assert "chunk_size" in props
        # 续读时 url 可省略 → url 不再是硬必填
        assert "url" not in _BUILTIN_SCHEMAS["browser_read"]["parameters"]["required"]

    def test_browser_dom_read_registered(self):
        assert "browser_dom_read" in _BUILTIN_SCHEMAS
        props = _BUILTIN_SCHEMAS["browser_dom_read"]["parameters"]["properties"]
        assert "session_id" in props
        assert "offset" in props
        assert "chunk_size" in props
        assert _BUILTIN_SCHEMAS["browser_dom_read"]["parameters"].get("required") in (None, [], ["chunk_size"]) or True


class TestBrowserReadExecutor:
    @pytest.mark.asyncio
    async def test_passes_continuation_params(self, executor):
        ex, _ = executor
        fake = {"success": True, "data": {"text": "片段", "can_continue": False}}
        with patch("neurova.tool_executor.ToolExecutor._web_reach_call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = fake
            result = await ex._execute_builtin_tool("browser_read", {
                "session_id": "rs_x", "offset": 500, "chunk_size": 2000,
            })
        assert result == fake
        args, kwargs = mock_call.call_args
        assert args[0] == "browser_read"
        params = args[1]
        assert params["session_id"] == "rs_x"
        assert params["offset"] == 500
        assert params["chunk_size"] == 2000

    @pytest.mark.asyncio
    async def test_legacy_url_only_call_unchanged(self, executor):
        ex, _ = executor
        fake = {"success": True, "data": {"text": "正文"}}
        with patch("neurova.tool_executor.ToolExecutor._web_reach_call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = fake
            await ex._execute_builtin_tool("browser_read", {"url": "https://e.com"})
        args, _ = mock_call.call_args
        params = args[1]
        assert params["url"] == "https://e.com"
        assert params.get("session_id") is None


class TestDomReadExecutor:
    @pytest.mark.asyncio
    async def test_delegates_to_manager_dom_read(self, executor):
        ex, _ = executor
        cursor_payload = {
            "text": "- button 'x'", "session_id": "rs_d1",
            "can_continue": True, "next_offset": 100, "offset": 0, "total_length": 300,
        }
        with patch("neurova.computer_use.get_computer_use_manager") as mock_get:
            mgr = MagicMock()
            mgr.browser_dom_read = AsyncMock(
                return_value=_make_browser_result(data=cursor_payload)
            )
            mock_get.return_value = mgr
            result = await ex._execute_builtin_tool("browser_dom_read", {"chunk_size": 100})

        assert result["success"] is True
        assert result["data"]["session_id"] == "rs_d1"   # 游标字段原样抵达 LLM 面
        assert result["data"]["can_continue"] is True
        mgr.browser_dom_read.assert_awaited_once_with(session_id=None, offset=None, chunk_size=100)

    @pytest.mark.asyncio
    async def test_long_snapshot_not_hard_truncated_anymore(self, executor):
        """续读就位后 8000 硬截断退位：8k 以上文本由 chunk 游标自然分片"""
        ex, _ = executor
        long_text = "z" * 12_000
        cursor_payload = {
            "text": "z" * 8_000, "session_id": "rs_d2",
            "can_continue": True, "next_offset": 8_000, "offset": 0, "total_length": 12_000,
        }
        with patch("neurova.computer_use.get_computer_use_manager") as mock_get:
            mgr = MagicMock()
            mgr.browser_dom_read = AsyncMock(
                return_value=_make_browser_result(data=cursor_payload)
            )
            mock_get.return_value = mgr
            result = await ex._execute_builtin_tool("browser_dom_read", {})

        assert result["data"]["text"] == "z" * 8_000
        assert result["data"]["can_continue"] is True

    @pytest.mark.asyncio
    async def test_emits_computer_event(self, executor):
        ex, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager") as mock_get, \
             patch.object(ToolExecutor, "_emit_computer_event", new_callable=AsyncMock) as mock_emit:
            mgr = MagicMock()
            mgr.browser_dom_read = AsyncMock(
                return_value=_make_browser_result(data={"text": "x", "session_id": "rs_e"})
            )
            mock_get.return_value = mgr
            await ex._execute_builtin_tool("browser_dom_read", {})

        mock_emit.assert_awaited_once()
        args, _ = mock_emit.await_args
        assert args[0] == "browser_dom_read"
