"""红绿灯 TDD：console /chat 流式接口必须把 stream=True 传给 agent.chat。

根因：post_console_chat 的 event_stream() 依赖 ChatPipeline 的流式路径
(_call_loop_stream) 把 reasoning/content 增量事件经 event_emitter 转发到 SSE，
但 run_chat() 调用 agent.chat() 时漏传 stream=True，ChatContext.stream 落到
默认值 False → 管线走 _call_loop_normal（非流式），思考过程与正文从不经过
发射器，前端只能收到收尾 flush 的工具事件，看不到任何 chunk/reasoning。

本测试直接调用端点函数 + 假 agent，断言：
1. body.stream=True 时 agent.chat 收到 stream=True；
2. 假 agent 经 metadata["event_emitter"] 发出的 reasoning/content 事件
   能以 SSE reasoning/chunk 事件形式出现在响应流中（桥接契约回归保护）。

注意：event_stream 是惰性生成器，必须在同一事件循环内消费 body_iterator，
agent.chat 才会真正执行。
"""
from __future__ import annotations

import asyncio
import json
import typing

from starlette.requests import Request
from starlette.responses import StreamingResponse

from neurova.api.endpoints import console as console_module


def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": [(b"content-type", b"application/json")],
    }
    return Request(scope, receive=receive)


class FakeRepo:
    def create_session(self, agent_id="", user_id="", title="新对话", config=None):
        return "sess-1"


class RecordingAgent:
    """记录 agent.chat 收到的 kwargs，并模拟管线经发射器推送事件。"""

    def __init__(self, emit_events: bool = False):
        self.chat_kwargs: typing.Optional[dict] = None
        self.emit_events = emit_events

    async def chat(self, message, **kwargs):
        self.chat_kwargs = kwargs
        if self.emit_events:
            emitter = (kwargs.get("metadata") or {}).get("event_emitter")
            assert emitter is not None, "stream 模式下 metadata 必须携带 event_emitter"
            emitter("reasoning", "思考片段")
            emitter("content", "你好")
        return {"text": "你好", "reasoning": "思考片段", "tool_messages": []}


def _patch(monkeypatch, agent) -> None:
    monkeypatch.setattr(console_module, "_get_user_id", lambda request: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: FakeRepo())
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id: agent)


async def _call_and_drain(body) -> typing.Tuple[typing.Any, typing.List[dict]]:
    """调用端点并消费 SSE 流，返回 (response, 解析后的事件列表)。"""
    resp = await console_module.post_console_chat(body, _make_request())
    events: typing.List[dict] = []
    if isinstance(resp, StreamingResponse):
        async for chunk in resp.body_iterator:
            for line in str(chunk).splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:"):].strip()))
    return resp, events


def test_console_chat_passes_stream_true_to_agent(monkeypatch):
    agent = RecordingAgent()
    _patch(monkeypatch, agent)
    body = console_module.ChatRequest(message="你好", session_id="s1", stream=True)
    resp, events = asyncio.run(_call_and_drain(body))
    assert isinstance(resp, StreamingResponse)
    assert agent.chat_kwargs is not None, "agent.chat 未被调用"
    assert agent.chat_kwargs.get("stream") is True, (
        "console 流式接口必须向 agent.chat 传 stream=True，"
        "否则 ChatPipeline 走非流式路径，思考过程无法经发射器转发"
    )
    assert events and events[-1].get("type") == "done"


def test_console_chat_relays_emitter_events_to_sse(monkeypatch):
    agent = RecordingAgent(emit_events=True)
    _patch(monkeypatch, agent)
    body = console_module.ChatRequest(message="你好", session_id="s1", stream=True)
    _, events = asyncio.run(_call_and_drain(body))
    types = [e.get("type") for e in events]
    assert "reasoning" in types, f"SSE 缺少 reasoning 事件: {types}"
    assert "chunk" in types, f"SSE 缺少 chunk 事件: {types}"
    reasoning_ev = next(e for e in events if e["type"] == "reasoning")
    assert reasoning_ev.get("content") == "思考片段"
    assert types[-1] == "done"
