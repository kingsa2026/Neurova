"""批次 B3：taskName 执行摘要参数（v0 taskNameActive/Complete 启发）。

链路：builtin schema 单点注入 → base.py 执行层剥离（不污染真实参数）→
records 携带 task_name → console.py 双路径 SSE 透传（流式 emitter + flush）
→ 前端时间轴段标题（前端测试另文件）。

验收点：
1. to_openai_format 为每个内置工具注入 taskNameActive/taskNameComplete 可选参数
2. 执行层：taskName* 从真实参数中剥离；records.tool_call.task_name=active 值；
   records.tool_result.task_name=complete 值
3. console flush 路径（_build_tool_events）透传 task_name
4. console 流式路径（_sse_events_from_emitter_item）从 arguments JSON 提取
   taskNameActive → event.task_name；privacy redact 不剥 task_name
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.builtin_tools import BuiltinToolRegistry


def _make_loop():
    """构造最小 BaseAgentLoop 子类（仅实现抽象方法；__init__ 不跑）。"""
    from neurova.agent.loops.base import BaseAgentLoop

    class _StubLoop(BaseAgentLoop):
        async def predict_step(self, messages, tools=None, **kwargs):  # pragma: no cover
            return None

    agent = SimpleNamespace(
        skill_registry=None,
        tool_router=None,
        append_tool_messages=lambda records: None,
        config=SimpleNamespace(user_id="default", agent_id="test-agent"),
    )
    loop = _StubLoop.__new__(_StubLoop)
    loop.agent = agent
    return loop


def _router_result(success=True, data=None, error=None):
    return SimpleNamespace(success=success, result=data, error=error)


class TestSchemaInjection:
    def test_builtin_tool_schema_has_task_name_params(self):
        reg = BuiltinToolRegistry()
        for name in ("web_search", "computer_shell", "file_read", "memory_search"):
            fmt = reg.get_tool(name).to_openai_format()
            props = fmt["function"]["parameters"]["properties"]
            assert "taskNameActive" in props, f"{name} 缺 taskNameActive"
            assert "taskNameComplete" in props, f"{name} 缺 taskNameComplete"
            assert props["taskNameActive"]["type"] == "string"
        # 且不出现在 required
        assert "taskNameActive" not in reg.get_tool("web_search").to_openai_format()["function"]["parameters"].get("required", [])

    def test_injection_idempotent(self):
        reg = BuiltinToolRegistry()
        fmt = reg.get_tool("web_search").to_openai_format()
        assert list(fmt["function"]["parameters"]["properties"]).count("taskNameActive") == 1


class TestExecutionLayerStripping:
    @pytest.mark.asyncio
    async def test_task_name_extracted_and_stripped(self):
        loop = _make_loop()
        router = MagicMock()
        router.execute = AsyncMock(return_value=_router_result(success=True, data={"ok": 1}))
        loop.agent.tool_router = router

        tool_call = {
            "id": "call_1",
            "function": {
                "name": "web_search",
                "arguments": json.dumps(
                    {
                        "query": "北京天气",
                        "taskNameActive": "搜索天气",
                        "taskNameComplete": "已查天气",
                    },
                    ensure_ascii=False,
                ),
            },
        }
        tool_msg, records = await loop._execute_tool_call_worker(tool_call)

        # 真实参数不含 taskName*（模型参数不污染执行面）
        router.execute.assert_awaited_once()
        sent_params = router.execute.await_args.kwargs.get("params") or router.execute.await_args.kwargs
        blob = json.dumps(sent_params, ensure_ascii=False, default=str)
        assert "taskNameActive" not in blob and "已查天气" not in blob

        # records 携带 task_name
        call_rec = next(r for r in records if r["type"] == "tool_call")
        result_rec = next(r for r in records if r["type"] == "tool_result")
        assert call_rec.get("task_name") == "搜索天气"
        assert result_rec.get("task_name") == "已查天气"

    @pytest.mark.asyncio
    async def test_no_task_name_passes_clean(self):
        loop = _make_loop()
        router = MagicMock()
        router.execute = AsyncMock(return_value=_router_result(success=True, data={"ok": 1}))
        loop.agent.tool_router = router

        tool_call = {
            "id": "call_2",
            "function": {"name": "web_search", "arguments": json.dumps({"query": "x"})},
        }
        _, records = await loop._execute_tool_call_worker(tool_call)
        call_rec = next(r for r in records if r["type"] == "tool_call")
        result_rec = next(r for r in records if r["type"] == "tool_result")
        assert "task_name" not in call_rec
        assert "task_name" not in result_rec

    @pytest.mark.asyncio
    async def test_stripping_survives_skill_path(self):
        """SkillRegistry 路径同样收不到 taskName*（先于双通道分发剥离）。"""
        loop = _make_loop()
        registry = MagicMock()
        skill_result = SimpleNamespace(success=True, data={"done": True}, error=None, metadata={})
        registry.execute_skill = AsyncMock(return_value=skill_result)
        loop.agent.skill_registry = registry

        tool_call = {
            "id": "call_3",
            "function": {
                "name": "memory",
                "arguments": json.dumps({"action": "search", "taskNameActive": "查记忆"}),
            },
        }
        await loop._execute_tool_call_worker(tool_call)
        sent_args = registry.execute_skill.await_args.args[1]
        assert "taskNameActive" not in sent_args


class TestSSEPassThrough:
    def test_flush_path_carries_task_name(self):
        from neurova.api.endpoints.console import _build_tool_events

        events = _build_tool_events({"type": "tool_call", "tool_name": "web_search", "params": {"query": "x"}, "task_name": "搜索中"})
        assert events[0]["task_name"] == "搜索中"
        events = _build_tool_events({"type": "tool_result", "tool_name": "web_search", "result": "ok", "task_name": "已搜索"})
        assert events[0]["task_name"] == "已搜索"

    def test_stream_path_extracts_from_arguments(self):
        from neurova.api.endpoints.console import _sse_events_from_emitter_item

        item = (
            "tool_call",
            {
                "id": "c1",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": "x", "taskNameActive": "搜索中"}, ensure_ascii=False),
                },
            },
        )
        events = _sse_events_from_emitter_item(item, set(), set())
        assert events[0]["type"] == "tool_call"
        assert events[0]["task_name"] == "搜索中"

    def test_redact_keeps_task_name(self):
        from neurova.security.privacy_gate import redact_tool_messages_for_channel

        out = redact_tool_messages_for_channel(
            [{"type": "tool_call", "tool_name": "web_search", "params": {"query": "x"}, "task_name": "搜索中"}]
        )
        assert out[0].get("task_name") == "搜索中"


class TestStreamFlushDedup:
    """核验轮修复①：流式/收尾去重键与 taskName 剥离的交互。

    流式键基于 LLM 原始 arguments 串（含 taskName*），收尾键基于剥离后的
    params 串——taskName 出现时两键必然不同，flush 会重复推送同一 tool_call。
    修复：键规范化（解析→剔 taskName*→紧凑序列化），流式事件 arguments 同步
    清洗（前端 args 预览无噪声，且与 flush 事件一致）。
    """

    def _stream_then_flush(self):
        """与生产 flush 循环同构：去重发生在循环内的键计算，而非 _build_tool_events 内部。"""
        from neurova.api.endpoints.console import (
            _build_tool_events,
            _call_key,
            _sse_events_from_emitter_item,
        )

        seen_calls: set = set()
        seen_results: set = set()
        raw_args = json.dumps({"query": "北京天气", "taskNameActive": "搜索天气"}, ensure_ascii=False)
        stream_events = _sse_events_from_emitter_item(
            ("tool_call", {"id": "c1", "function": {"name": "web_search", "arguments": raw_args}}),
            seen_calls, seen_results,
        )
        tm = {"type": "tool_call", "tool_name": "web_search", "params": {"query": "北京天气"}, "task_name": "搜索天气"}
        flush_events = []
        for event in _build_tool_events(tm):
            key = _call_key(
                str(event.get("name", "")),
                json.dumps(tm.get("params", {}), ensure_ascii=False),
            )
            if key in seen_calls:
                continue
            seen_calls.add(key)
            flush_events.append(event)
        return stream_events, flush_events

    def test_flush_not_duplicate_after_stream(self):
        stream_events, flush_events = self._stream_then_flush()
        assert len(stream_events) == 1
        # 去重键必须把 taskName* 剔除后可比——否则 flush 重复推送同一调用
        assert flush_events == [], "同一 tool_call 在收尾 flush 被重复推送（核验轮修复①）"

    def test_stream_event_arguments_cleaned(self):
        stream_events, _ = self._stream_then_flush()
        args = stream_events[0]["arguments"]
        assert "taskNameActive" not in args, "流式事件 arguments 残留展示噪声"

    def test_spacing_variation_still_deduped(self):
        """预存隐患：LLM 紧凑 JSON vs json.dumps 空格差异也应去重。"""
        from neurova.api.endpoints.console import _build_tool_events, _call_key, _sse_events_from_emitter_item

        seen: set = set()
        _sse_events_from_emitter_item(
            ("tool_call", {"id": "c1", "function": {"name": "t", "arguments": '{"query":"x"}'}}),
            seen, set(),
        )
        tm = {"type": "tool_call", "tool_name": "t", "params": {"query": "x"}}
        flush = []
        for event in _build_tool_events(tm):
            key = _call_key(str(event.get("name", "")), json.dumps(tm.get("params", {}), ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            flush.append(event)
        assert flush == [], "键序/空格差异导致去重失效（预存隐患）"

    def test_non_json_arguments_fallback(self):
        from neurova.api.endpoints.console import _sse_events_from_emitter_item

        events = _sse_events_from_emitter_item(
            ("tool_call", {"id": "c1", "function": {"name": "t", "arguments": "not-json"}}),
            set(), set(),
        )
        assert events[0]["type"] == "tool_call"
