# -*- coding: utf-8 -*-
"""批次 A 的 live-verify：claude 在流式下真的走原生工具环，不再回退 legacy。

跑的真生产对象：
1. 真消费点 `ChatPipeline._call_agent_loop` → `_call_loop_stream`（就是改前抛
   `TypeError: 'LLMResponse' object is not async iterable` 的那一处 `async for`）；
2. 真 `AnthropicLoop`：门控装配、轮次态、消息转换、`handle_tool_calls` 全走实现本体；
3. 真执行咽喉 `ToolExecutor`（技能执行体是替身，边界止于执行体）；
4. 真落盘 `PostChatPipeline._step_save_session` + 真读回
   `SessionManager.get_recent_model_context`（下一轮模型实际看到的上下文）。

唯一替身是供应商客户端（假 `chat_stream` 产 LLMResponse 分片，与真实契约同形）——
本机没有 claude 凭证，这一层能证"编排真走到这条环、工具真跑了、结果真进了历史与台账"，
**不证**真供应商的流式分片形状（那要真 key + 真网络，属发布前动作）。

判据（缺一条这条链就是断的）：
1. `_predict_stream` 被真走到（用构造/调用计数 wrapper 证，不用 grep 调用方）；
2. 全程没有 "falling back to legacy" 警告（改前每次流式都会打）；
3. 工具经真咽喉执行，`tool_result` 事件转发到了 emitter（SSE 出口那条通道）；
4. 被执行的调用在 `ctx.context` 里有配对的 assistant 声明 + tool 结果；
5. 落盘后下一轮读回能看到该结果（写→读→反馈闭合）。

一条命令复现：PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/anthropicLoopStreamLive.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()

TOOL_NAME = "probe_reader"
MODEL = "claude-3-5-sonnet-20241022"
AGENT_ID = "a_anth_live"
SESSION_ID = "sess_anth_live"


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "A 批 live 探针技能"
        self.config = {}


class _StubRegistry:
    def __init__(self, name, execute):
        self._skill = _StubSkill(name)
        self.skills = {name: self._skill}
        self.execute_skill = execute

    def get_skill(self, name):
        return self._skill if name == self._skill.name else None

    def has_skill(self, name):
        return name == self._skill.name

    def list_skills(self):
        return []


class FakeProviderStream:
    """与 MultiModelLLMClient.chat_stream 同契约的假供应商：产 LLMResponse 分片。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []
        self.config = SimpleNamespace()

    async def chat_stream(self, messages=None, **kwargs):
        self.calls.append(list(messages or []))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk

    async def chat(self, messages=None, **kwargs):
        self.calls.append(list(messages or []))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        return self.rounds[idx][-1]


def buildAgent(client):
    from neurova.agent_core import Agent
    from neurova.core.turn_context import set_turn_identity
    from neurova.mem_core import MemCore
    from neurova.session_manager import get_session_manager

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "anthLive"
    agent.config.agent_id = AGENT_ID
    agent.config.llm_model = MODEL
    agent.config.workspace_path = tempfile.mkdtemp(prefix="anthLive-ws-")
    agent.user_id = "u1"
    agent.agent_id = AGENT_ID
    set_turn_identity("读一下", SESSION_ID, "u1")
    agent.session_manager = get_session_manager()
    agent.memory_agent = MemCore(agent)
    agent._current_user_id = "u1"
    agent.tool_memory = None
    agent.tool_lifecycle = None
    agent.skill_packer = None
    agent.tool_router = None
    agent.skill_registry = None
    agent._tool_messages_list = []
    agent.llm_client = client
    # `current_session_id` 是 Agent 上的只读 property（背后是轮次上下文单源），
    # 归属已经由上面的 `set_turn_identity` 登记，这里不再另设一份

    records = []

    def _append(recs):
        records.extend(recs or [])

    agent.append_tool_messages = _append
    agent.get_tool_messages_snapshot = lambda: list(records)
    agent._collect_tool_messages = lambda: list(records)
    agent.reset_tool_messages = lambda: records.clear()
    agent._skill_registry = _StubRegistry(
        TOOL_NAME,
        AsyncMock(side_effect=lambda *a, **kw: {"content": f"探针正文 args={a} kwargs={kw}"}),
    )
    return agent, records


def main() -> int:
    from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
    from neurova.agent.loops.anthropic_loop import AnthropicLoop
    from neurova.llm_client import LLMResponse
    from neurova.post_chat_pipeline import PostChatPipeline
    from neurova.tool_executor import ToolExecutor

    rounds = [
        [
            LLMResponse(content="我先"),
            LLMResponse(content="读一下。"),
            LLMResponse(tool_calls=[{
                "index": 0, "id": "call_anth_1", "type": "function",
                "function": {"name": TOOL_NAME, "arguments": json.dumps({"p": "s1"})},
            }], finish_reason="tool_calls"),
        ],
        [LLMResponse(content="读完了，正文在上面。", finish_reason="stop")],
    ]
    client = FakeProviderStream(rounds)
    agent, records = buildAgent(client)
    agent.tool_executor = ToolExecutor(agent)

    loop = AnthropicLoop(agent)
    loop.llm_client = client
    agent.loop = loop

    # 计数 wrapper：证「生产编排真的走到了这条环的流式分支」，不靠 grep 调用方
    entered = {"stream": 0}
    originalStream = loop._predict_stream

    def countingStream(messages, drive, state):
        entered["stream"] += 1
        return originalStream(messages, drive, state)

    loop._predict_stream = countingStream

    pipeline = ChatPipeline(agent)

    events = []

    def emitter(etype, data):
        events.append((etype, data))

    ctx = ChatContext(
        user_input="读一下",
        stream=True,
        session_id=SESSION_ID,
        context=[{"role": "user", "content": "读一下"}],
        event_emitter=emitter,
        metadata={"emit_tool_events": True},
    )

    logging.getLogger("neurova.agent.chat_pipeline").setLevel(logging.WARNING)
    import io

    logCapture = io.StringIO()
    handler = logging.StreamHandler(logCapture)
    logging.getLogger("neurova.agent.chat_pipeline").addHandler(handler)
    try:
        reply = asyncio.run(pipeline._call_agent_loop(ctx, None))
    finally:
        logging.getLogger("neurova.agent.chat_pipeline").removeHandler(handler)

    print(f"1) _predict_stream 进入次数 = {entered['stream']}")
    assert entered["stream"] == 1, "claude 流式没有走进原生环（改前形态：消费点 TypeError 后回退 legacy）"
    print(f"2) 供应商往返次数 = {len(client.calls)}（工具轮后应有续写）")
    assert len(client.calls) == 2, f"工具执行后没发起续写：{len(client.calls)}"

    logText = logCapture.getvalue()
    print(f"3) 是否回退 legacy = {'falling back to legacy' in logText}")
    assert "falling back to legacy" not in logText, f"仍回退了 legacy：{logText[:400]}"

    etypes = [e for e, _ in events]
    print(f"   emitter 收到的事件 = {etypes}")
    assert "content" in etypes, "token 分片没转发到 SSE 出口（流式 UX 断）"
    assert "tool_result" in etypes, "工具结果没转发到 SSE 出口"

    toolMsgs = [m for m in ctx.context if m.get("role") == "tool"]
    declared = {
        c.get("id")
        for m in ctx.context
        if m.get("role") == "assistant" and m.get("tool_calls")
        for c in m["tool_calls"]
    }
    print(f"4) 历史里的 tool 结果 = {[m.get('tool_call_id') for m in toolMsgs]}，声明 = {sorted(declared)}")
    assert [m.get("tool_call_id") for m in toolMsgs] == ["call_anth_1"], toolMsgs
    assert "call_anth_1" in declared, "缺 assistant.tool_calls 声明——Anthropic 协议会判续写非法"
    # tool 正文是 JSON 串（ensure_ascii 把中文落成转义），判据要在解出的文本上做——
    # 直接在转义串上找中文是假红（与 B 批同一形态）
    _toolBody = json.loads(toolMsgs[0]["content"])
    _toolText = _toolBody.get("content") if isinstance(_toolBody, dict) else str(_toolBody)
    print(f"   回环正文 = {str(_toolText)[:120]!r}")
    assert "探针正文" in str(_toolText), f"回环的不是真执行结果（咽喉未走到？）：{_toolBody}"
    print(f"   回复文本 = {reply!r}")
    assert "读完了" in (reply or ""), reply

    pipeline2 = PostChatPipeline(agent)
    pipeline2._step_results = []
    saved = asyncio.run(
        pipeline2._step_save_session(
            user_input="读一下",
            reply=reply,
            session_id=SESSION_ID,
            save_memory=True,
            metadata={"session_title": "anthLive"},
        )
    )
    from neurova.session_manager import get_session_manager

    context = get_session_manager().get_recent_model_context(AGENT_ID, SESSION_ID, max_messages=20)
    readBack = [m.get("tool_call_id") for m in context if m.get("role") == "tool"]
    print(f"5) 落盘 {saved!r} → 下一轮读回的 tool 结果 = {readBack}")
    assert "call_anth_1" in readBack, f"读侧拿不到这一轮的下文：{readBack}"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
