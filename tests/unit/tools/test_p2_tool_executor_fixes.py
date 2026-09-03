"""
P2 修复测试（2026-08 代码审计）— ToolExecutor

覆盖 bug:
1. _execute_single_tool 及多处用 getattr(self._agent, "user_id"/"agent_id", None)
   取身份，但这两个属性在 Agent 实例上不存在（位于 agent.config）→ 恒 None，
   ToolEngine 的审计/安全防护失去用户身份
2. list 模式参数 JSON 解析失败时静默 arguments={} 继续执行 →
   file_write/run_code 等破坏性工具可能以空参数执行（文本模式已有修复，list 模式遗漏）
3. _execute_web_search/_execute_weather 在 async 函数内直接调用阻塞的
   urllib.request.urlopen（timeout=10s）→ 卡死整个事件循环
4. list/text 模式写入 _tool_messages_list 的消息缺少 type/success/timestamp 字段，
   与 agent/loops/base.py 的格式不一致 → post_chat_pipeline._step_marketplace_publish
   的 `tm.get("type")=="tool_result" and tm.get("success")` 恒 False，发布步骤成死步骤
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import neurova.tool_executor as tool_executor_module
from neurova.tool_executor import ToolExecutor


def _make_executor(monkeypatch, config_user_id="u1", config_agent_id="a1"):
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id=config_user_id, agent_id=config_agent_id),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="do the thing",
    )
    executor = ToolExecutor(agent)
    monkeypatch.setattr(ToolExecutor, "tool_engine", property(lambda self: None))
    monkeypatch.setattr(
        tool_executor_module,
        "get_builtin_tool_params",
        lambda name: {"type": "object"} if name == "fake_builtin" else None,
    )
    return executor, agent


class TestToolEngineIdentity:
    @pytest.mark.asyncio
    async def test_tool_engine_receives_identity_from_config(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        captured = {}
        engine = MagicMock()

        async def fake_execute(tool_name, parameters, user_id=None, agent_id=None):
            captured["user_id"] = user_id
            captured["agent_id"] = agent_id
            return {"ok": True}

        engine.execute_with_safeguards = fake_execute
        monkeypatch.setattr(ToolExecutor, "tool_engine", property(lambda self: engine))

        await executor._execute_single_tool("some_tool", {"x": 1})

        assert captured["user_id"] == "u1", (
            "user_id 必须从 agent.config 解析，getattr(agent, 'user_id') 恒 None"
        )
        assert captured["agent_id"] == "a1", (
            "agent_id 必须从 agent.config 解析，getattr(agent, 'agent_id') 恒 None"
        )


class TestListModeArgumentsParsing:
    @pytest.mark.asyncio
    async def test_invalid_json_arguments_not_executed(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        executed = []

        async def fake_single(tool_name, params, skip_governance=False):
            executed.append((tool_name, params))
            return {"ok": True}

        monkeypatch.setattr(executor, "_execute_single_tool", fake_single)

        results = await executor.execute_text_tool_calls(
            [{"id": "c1", "function": {"name": "file_write", "arguments": "{not valid json"}}],
            messages=[],
        )

        assert not executed, (
            "参数 JSON 解析失败时不得以空参数执行工具（破坏性工具空参数执行风险）"
        )
        assert results[0]["success"] is False
        result_payload = results[0].get("result")
        assert "error" in str(result_payload).lower() or results[0].get("error")

    @pytest.mark.asyncio
    async def test_dict_arguments_passthrough(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        executed = []

        async def fake_single(tool_name, params, skip_governance=False):
            executed.append((tool_name, params))
            return {"ok": True}

        monkeypatch.setattr(executor, "_execute_single_tool", fake_single)

        results = await executor.execute_text_tool_calls(
            [{"id": "c1", "function": {"name": "some_tool", "arguments": {"a": 1}}}],
            messages=[],
        )

        assert executed == [("some_tool", {"a": 1})], (
            "部分 provider 直接传 dict 参数，必须原样透传而非 json.loads(dict) 报错"
        )
        assert results[0]["success"] is True


class TestBlockingHttpOffloaded:
    @pytest.mark.asyncio
    async def test_web_search_does_not_block_event_loop(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        import urllib.request

        def fake_urlopen(req, timeout=None):
            time.sleep(0.3)
            raise RuntimeError("network disabled in test")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        result = await executor._execute_web_search({"query": "test query"})
        stop = True
        task.cancel()

        assert ticks >= 10, (
            f"web_search 期间事件循环被阻塞（ticks={ticks}），"
            "阻塞式 urlopen 必须移出事件循环（如 asyncio.to_thread）"
        )
        assert result.get("query") == "test query"

    @pytest.mark.asyncio
    async def test_weather_does_not_block_event_loop(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        import urllib.request

        def fake_urlopen(req, timeout=None):
            time.sleep(0.3)
            raise RuntimeError("network disabled in test")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        result = await executor._execute_weather({"location": "Xuchang"})
        stop = True
        task.cancel()

        assert ticks >= 10, (
            f"weather 查询期间事件循环被阻塞（ticks={ticks}），"
            "阻塞式 urlopen 必须移出事件循环"
        )
        assert result.get("location") == "Xuchang"


class TestToolMessageFormatConsistency:
    @pytest.mark.asyncio
    async def test_list_mode_message_has_type_and_success(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)

        async def fake_single(tool_name, params, skip_governance=False):
            return {"data": "ok"}

        monkeypatch.setattr(executor, "_execute_single_tool", fake_single)

        await executor.execute_text_tool_calls(
            [{"id": "c1", "function": {"name": "my_tool", "arguments": "{}"}}],
            messages=[],
        )

        messages = getattr(agent, "_tool_messages_list", [])
        assert messages, "工具消息必须写入 _tool_messages_list"
        msg = messages[-1]
        assert msg.get("type") == "tool_result", (
            "必须与 agent/loops/base.py 的格式一致，"
            "否则 _step_marketplace_publish 的 type/success 判定恒 False（死步骤）"
        )
        assert msg.get("success") is True
        assert msg.get("timestamp"), "缺少 timestamp 字段"

    @pytest.mark.asyncio
    async def test_list_mode_message_success_false_on_error_result(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)

        async def fake_single(tool_name, params, skip_governance=False):
            return {"error": "boom"}

        monkeypatch.setattr(executor, "_execute_single_tool", fake_single)

        await executor.execute_text_tool_calls(
            [{"id": "c1", "function": {"name": "my_tool", "arguments": "{}"}}],
            messages=[],
        )

        messages = getattr(agent, "_tool_messages_list", [])
        assert messages
        msg = messages[-1]
        assert msg.get("type") == "tool_result"
        assert msg.get("success") is False, "结果为 error 时消息必须标记 success=False"

    @pytest.mark.asyncio
    async def test_text_mode_message_has_type_and_success(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)

        async def fake_single(tool_name, params, skip_governance=False):
            return {"data": "ok"}

        monkeypatch.setattr(executor, "_execute_single_tool", fake_single)

        await executor._execute_from_text(
            '好的，我来处理。[TOOL_CALL:my_tool({"x": 1})]', "user input"
        )

        messages = getattr(agent, "_tool_messages_list", [])
        assert messages, "文本模式工具消息必须写入 _tool_messages_list"
        msg = messages[-1]
        assert msg.get("type") == "tool_result"
        assert msg.get("success") is True
        assert msg.get("timestamp")
