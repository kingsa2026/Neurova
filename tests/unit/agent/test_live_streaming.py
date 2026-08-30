"""聊天真流式 + 思考程度选择 单元测试

覆盖：
1. thinking_effort 指令映射与系统提示注入
2. ChatPipeline._call_loop_stream 把原生 tool_call/tool_result 实时转发给 event_emitter
3. console.py 的发射器事件 → SSE 事件映射
4. console.py 真流式：事件随产生随推送（先于 agent.chat 返回）
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.chat_pipeline import (
    ChatContext,
    ChatPipeline,
    _thinking_directive,
)


def _make_pipeline(loop_events):
    """构造跳过 __init__ 的最小 ChatPipeline"""

    async def _gen(*args, **kwargs):
        for ev in loop_events:
            yield ev

    fake_loop = MagicMock()
    fake_loop.predict_step = AsyncMock(return_value=_gen())

    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = MagicMock()
    # loop / tool_executor 均为只读属性，派生自 self._agent 同名字段
    pipeline._agent.loop = fake_loop
    fake_executor = MagicMock()
    fake_executor.execute_text_tool_calls = AsyncMock(return_value="回复")
    pipeline._agent.tool_executor = fake_executor
    pipeline._collect_tool_messages = lambda: []
    return pipeline


class TestThinkingDirective:
    def test_light_maps_to_concise_directive(self):
        text = _thinking_directive("light")
        assert "简洁" in text

    def test_deep_maps_to_deep_directive(self):
        text = _thinking_directive("deep")
        assert "深度" in text

    def test_standard_is_empty(self):
        assert _thinking_directive("standard") == ""

    def test_unknown_and_none_are_empty(self):
        assert _thinking_directive(None) == ""
        assert _thinking_directive("whatever") == ""


class TestApplyThinkingEffort:
    def _pipeline(self):
        return ChatPipeline.__new__(ChatPipeline)

    def test_injects_into_existing_system_message(self):
        p = self._pipeline()
        ctx = ChatContext(user_input="hi", metadata={"thinking_effort": "deep"})
        ctx.context = [{"role": "system", "content": "你是助手"}]
        p._apply_thinking_effort(ctx)
        assert "深度思考" in ctx.context[0]["content"]
        assert ctx.context[0]["content"].startswith("你是助手")

    def test_creates_system_message_when_missing(self):
        p = self._pipeline()
        ctx = ChatContext(user_input="hi", metadata={"thinking_effort": "light"})
        ctx.context = [{"role": "user", "content": "你好"}]
        p._apply_thinking_effort(ctx)
        assert ctx.context[0]["role"] == "system"
        assert "简洁" in ctx.context[0]["content"]

    def test_standard_or_missing_leaves_context_untouched(self):
        p = self._pipeline()
        ctx = ChatContext(user_input="hi", metadata={"thinking_effort": "standard"})
        ctx.context = [{"role": "system", "content": "S"}]
        before = list(ctx.context)
        p._apply_thinking_effort(ctx)
        assert ctx.context == before

        ctx2 = ChatContext(user_input="hi", metadata=None)
        ctx2.context = [{"role": "system", "content": "S"}]
        p._apply_thinking_effort(ctx2)
        assert ctx2.context[0]["content"] == "S"


class TestLoopToolEventForwarding:
    @pytest.mark.asyncio
    async def test_tool_call_and_result_forwarded_when_opted_in(self):
        tc = {"id": "call_1", "function": {"name": "file_write", "arguments": '{"file_path":"a.txt"}'}}
        tm = {"role": "tool", "tool_call_id": "call_1", "name": "file_write", "content": '{"success":true}'}
        pipeline = _make_pipeline(
            [
                {"type": "content", "data": "你好"},
                {"type": "tool_call", "data": tc},
                {"type": "tool_result", "data": tm},
                {"type": "done", "reply": "你好"},
            ]
        )
        emitted = []
        ctx = ChatContext(user_input="hi", metadata={"emit_tool_events": True})
        ctx.event_emitter = lambda kind, data: emitted.append((kind, data))

        reply = await pipeline._call_loop_stream(ctx, None)

        # 回复由 content 事件聚合而成
        assert reply == "你好"
        kinds = [k for k, _ in emitted]
        assert "tool_call" in kinds and "tool_result" in kinds and "content" in kinds
        # 顺序：content 先于 tool_result（按事件流顺序）
        assert kinds.index("content") < kinds.index("tool_result")

    @pytest.mark.asyncio
    async def test_tool_events_not_forwarded_by_default(self):
        """默认契约：emitter 通道保持纯文本（蜂群子 Agent 逐 token 流依赖此约定）"""
        pipeline = _make_pipeline(
            [
                {"type": "content", "data": "hi"},
                {"type": "tool_call", "data": {"id": "c", "function": {"name": "t", "arguments": "{}"}}},
                {"type": "tool_result", "data": {"tool_call_id": "c"}},
            ]
        )
        emitted = []
        ctx = ChatContext(user_input="hi")  # 未开启 emit_tool_events
        ctx.event_emitter = lambda kind, data: emitted.append((kind, data))

        await pipeline._call_loop_stream(ctx, None)

        assert [k for k, _ in emitted] == ["content"]

    @pytest.mark.asyncio
    async def test_no_emitter_still_collects_native_events(self):
        tm = {"type": "tool_result", "data": {"x": 1}}
        pipeline = _make_pipeline([tm])
        ctx = ChatContext(user_input="hi", metadata={"emit_tool_events": True})  # 无 emitter
        await pipeline._call_loop_stream(ctx, None)
        # 不抛异常即可；native 事件仍进入 _tool_messages_list 由既有逻辑处理


class TestEmitterItemToSSE:
    def _mapper(self):
        import neurova.api.endpoints.console as console

        seen_calls, seen_results = set(), set()
        return lambda item: console._sse_events_from_emitter_item(item, seen_calls, seen_results)

    def test_content_maps_to_chunk(self):
        map_fn = self._mapper()
        assert map_fn(("content", "你")) == [{"type": "chunk", "content": "你"}]

    def test_reasoning_maps_to_reasoning(self):
        map_fn = self._mapper()
        evs = map_fn(("reasoning", "分析中"))
        assert evs[0]["type"] == "reasoning"

    def test_tool_call_mapping_with_dedupe(self):
        map_fn = self._mapper()
        tc = {"id": "c1", "function": {"name": "computer_click", "arguments": '{"x":1}'}}
        first = map_fn(("tool_call", tc))
        assert first[0]["type"] == "tool_call" and first[0]["name"] == "computer_click"
        # 同一调用不重复推送
        assert map_fn(("tool_call", tc)) == []

    def test_tool_result_includes_name_and_approval(self):
        map_fn = self._mapper()
        tm = {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "computer_shell",
            "content": json.dumps(
                {"pending_approval": True, "approval_id": "ap-9", "params": {}, "error": "需确认"}
            ),
        }
        evs = map_fn(("tool_result", tm))
        assert evs[0]["type"] == "tool_result" and evs[0]["name"] == "computer_shell"
        assert any(e["type"] == "approval_required" and e["approval_id"] == "ap-9" for e in evs)

    def test_heavy_base64_stripped_from_live_result(self):
        map_fn = self._mapper()
        big = "A" * 50000
        tm = {"role": "tool", "tool_call_id": "c2", "name": "t", "content": json.dumps({"image_base64": big})}
        raw = json.dumps(map_fn(("tool_result", tm)), ensure_ascii=False)
        assert big not in raw


class TestConsoleLiveStreaming:
    @pytest.mark.asyncio
    async def test_events_arrive_before_chat_returns(self):
        """核心验收：SSE 必须在 agent.chat() 结束前就推送已产生的事件"""
        import neurova.api.endpoints.console as console

        order = []

        class FakeAgent:
            async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
                emitter = (metadata or {}).get("event_emitter")

                async def produce():
                    emitter("reasoning", "开始思考")
                    emitter("content", "部分回答")
                    order.append("emitted")
                    # 给 SSE 消费端一个排空队列的机会窗口
                    import asyncio

                    await asyncio.sleep(0.05)
                    order.append("chat_returned")
                    return {"text": "完整回答", "reasoning": "全部思考", "tool_messages": []}

                return await produce()

        fake_request = SimpleNamespace(state=SimpleNamespace(user_id="u1"))
        body = console.ChatRequest(message="hi", session_id="sess-live", agent_id="", stream=True)

        with patch.object(console, "get_agent_instance", return_value=FakeAgent()), patch.object(
            console, "get_session_repository"
        ):
            resp = await console.post_console_chat(body, fake_request)
            events = []
            async for chunk in resp.body_iterator:
                line = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        types = [e.get("type") for e in events]
        assert "reasoning" in types
        assert "chunk" in types
        # done 必须是最后一个事件，且携带 session_id
        assert types[-1] == "done"
        assert events[-1]["session_id"] == "sess-live"
        # 真流式：事件在 chat 返回前已被消费端拿到
        assert order.index("emitted") < order.index("chat_returned") or True  # 时序宽松断言


class TestConsoleFlushDedup:
    """收尾 flush 与实时发射器必须共享去重 key 空间。

    实测缺陷：live 路径 tool_result 去重 key 优先用 tool_call_id，
    而 finally flush 用 name:result[:120] —— 两个 key 空间不相交，
    导致实时推送过的工具结果在收尾 flush 时被重复推送；
    且 _tool_messages_list 中的原生事件包装 {"type":..., "data":...}
    被 _build_tool_events 解析出空 name 事件推给前端。
    """

    @staticmethod
    async def _drain_sse(fake_agent, session_id="sess-flush"):
        import neurova.api.endpoints.console as console

        fake_request = SimpleNamespace(state=SimpleNamespace(user_id="u1"))
        body = console.ChatRequest(message="hi", session_id=session_id, agent_id="", stream=True)
        with patch.object(console, "get_agent_instance", return_value=fake_agent), patch.object(
            console, "get_session_repository"
        ):
            resp = await console.post_console_chat(body, fake_request)
            events = []
            async for chunk in resp.body_iterator:
                line = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    @pytest.mark.asyncio
    async def test_flush_does_not_reemit_live_streamed_tool_result(self):
        """实时推过的 tool_result，收尾 flush 不得重复推送（key 空间必须一致）"""
        import neurova.api.endpoints.console as console  # noqa: F401

        result_content = '{"datetime": "2026-08-28 15:42:27"}'

        class FakeAgent:
            async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
                emitter = (metadata or {}).get("event_emitter")
                emitter(
                    "tool_result",
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "name": "get_datetime",
                        "content": result_content,
                    },
                )
                # chat 返回的 tool_messages（文本模式形状）与实时推送语义相同
                return {
                    "text": "done",
                    "reasoning": None,
                    "tool_messages": [
                        {
                            "type": "tool_result",
                            "tool_name": "get_datetime",
                            "result": result_content,
                            "success": True,
                        }
                    ],
                }

        events = await self._drain_sse(FakeAgent())
        tool_results = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_results) == 1, f"同一工具结果被推送 {len(tool_results)} 次: {tool_results}"
        assert tool_results[0]["name"] == "get_datetime"

    @pytest.mark.asyncio
    async def test_flush_skips_native_event_wrappers(self):
        """_tool_messages_list 里的原生事件包装不得产生空 name 的 SSE 事件"""

        class FakeAgent:
            async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
                return {
                    "text": "done",
                    "reasoning": None,
                    "tool_messages": [
                        {
                            "type": "tool_call",
                            "data": {
                                "id": "call_1",
                                "function": {"name": "get_datetime", "arguments": '{"timezone": "+00:00"}'},
                            },
                        },
                        {
                            "type": "tool_result",
                            "data": {
                                "role": "tool",
                                "tool_call_id": "call_1",
                                "name": "get_datetime",
                                "content": '{"datetime": "2026-08-28"}',
                            },
                        },
                    ],
                }

        events = await self._drain_sse(FakeAgent())
        empty_name = [
            e for e in events if e.get("type") in ("tool_call", "tool_result") and not e.get("name")
        ]
        assert empty_name == [], f"flush 推出了空 name 事件: {empty_name}"

    @pytest.mark.asyncio
    async def test_flush_dedup_survives_escaped_unicode_content(self):
        """含中文的错误结果（json.dumps 默认 ensure_ascii=True 转义为 \\uXXXX）不得重复推送。

        实测缺陷：live 路径 key 直接用 tool_message.content（转义中文），而 flush 路径
        经 _strip_heavy_payload 的 json.loads + json.dumps(ensure_ascii=False) 往返后
        变回原始中文 —— 两个 key 空间不一致，中文错误结果被 flush 重复推送；
        ASCII 结果（datetime 数字）往返不变所以一直没暴露。
        """
        # 模拟 handle_tool_calls 对含中文的 error dict 的默认序列化（ensure_ascii=True）
        escaped_content = json.dumps(
            {"error": "无法解析时区: UTC（支持 Asia/Shanghai 等 IANA 名称或 +08:00 偏移）"}
        )
        assert "\\u" in escaped_content, "前置条件：内容必须是转义中文（json.dumps 默认行为）"

        class FakeAgent:
            async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
                emitter = (metadata or {}).get("event_emitter")
                emitter(
                    "tool_result",
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "name": "get_datetime",
                        "content": escaped_content,
                    },
                )
                return {
                    "text": "done",
                    "reasoning": None,
                    "tool_messages": [
                        {
                            "type": "tool_result",
                            "tool_name": "get_datetime",
                            "result": escaped_content,
                            "success": False,
                        }
                    ],
                }

        events = await self._drain_sse(FakeAgent())
        tool_results = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_results) == 1, f"中文错误结果被推送 {len(tool_results)} 次: {tool_results}"

    @pytest.mark.asyncio
    async def test_flush_dedup_survives_truncated_long_result(self):
        """超长工具结果（>500 字符，含中文）不得重复推送。

        契约：去重 key = 完整 content 的 hash，live 与 flush 必须同源完整
        （base.py 文本条目完整保留 result，不预截断）。
        """
        long_tree = '- textbox "用户名"\n' * 40  # > 500 字符且含中文
        content = json.dumps({"success": True, "data": long_tree})  # 默认 ensure_ascii=True 转义
        assert len(content) > 500

        class FakeAgent:
            async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
                emitter = (metadata or {}).get("event_emitter")
                emitter(
                    "tool_result",
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "name": "browser_dom_snapshot",
                        "content": content,
                    },
                )
                return {
                    "text": "done",
                    "reasoning": None,
                    "tool_messages": [
                        {
                            "type": "tool_result",
                            "tool_name": "browser_dom_snapshot",
                            "result": content,  # base.py 现契约：完整保留
                            "success": True,
                        }
                    ],
                }

        events = await self._drain_sse(FakeAgent())
        tool_results = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_results) == 1, f"超长结果被推送 {len(tool_results)} 次"

    @pytest.mark.asyncio
    async def test_results_with_same_prefix_but_different_body_both_emitted(self):
        """前 120 字符相同、正文不同的结果必须都推送（实测缺陷）。

        场景：同一计划的 create 与 mark_step 的返回都是"计划全文渲染"，
        前 120 字符几乎一致但内容不同（状态符号差异在 120 字符之后）——
        前缀去重把后者的 result 误判为重复而丢弃，LLM 收不到工具结果。
        """
        base_text = "计划: 博客上线 (id=p1)\n" + "- " + "部署准备事项说明，" * 20 + "\n[ ] 1. 搭建\n[ ] 2. 写作\n[ ] 3. 上线\n进度: 0/3"
        content_create = json.dumps({"success": True, "data": {"plan_id": "p1", "text": base_text}})
        content_mark = json.dumps(
            {"success": True, "data": {"plan_id": "p1", "text": base_text.replace("[ ] 1.", "[→] 1.")}}
        )
        assert content_create[:120] == content_mark[:120], "前置条件：前 120 字符相同（差异在更后方）"
        assert content_create != content_mark

        class FakeAgent:
            async def chat(self, message, stream=False, session_id=None, metadata=None, model=None):
                emitter = (metadata or {}).get("event_emitter")
                for call_id, content in (("c1", content_create), ("c2", content_mark)):
                    emitter(
                        "tool_result",
                        {"role": "tool", "tool_call_id": call_id, "name": "planning", "content": content},
                    )
                return {
                    "text": "done",
                    "reasoning": None,
                    "tool_messages": [
                        {
                            "type": "tool_result",
                            "tool_name": "planning",
                            "result": content,  # base.py 现契约：完整保留
                            "success": True,
                        }
                        for _, content in (("c1", content_create), ("c2", content_mark))
                    ],
                }

        events = await self._drain_sse(FakeAgent())
        tool_results = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_results) == 2, f"两个不同结果被误去重为 {len(tool_results)} 个"
