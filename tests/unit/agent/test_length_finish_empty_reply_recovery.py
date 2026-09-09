"""
修3（2026-09-09）：finish_reason=length 空正文的单次压缩重试防线

kai 空回复事故根因：思考模型（glm-5.3-flash）× max_tokens=4096 × 3.5万 token
prompt → 思考吃满输出预算 → finish_reason=length 且正文为空，HTTP 200 无异常，
compact_messages_for_overflow（只认 TokenLimitExceeded）永远不触发。

契约（_predict_stream 层，与溢出恢复同构的单次重试语义）：
1. 首轮 finish_reason=length 且 reply 为空（无 content/无 tool_calls）→
   压缩消息后单次重试；
2. 重试产出内容 → 正常转发；
3. 重试仍空/仍 length → 原样 yield 首轮 done（不二次重试，防循环）；
4. 首轮有正文/工具调用 → 零行为变化；
5. 非=length 的 finish_reason → 零行为变化。
"""

import pytest
from types import SimpleNamespace

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse


def _make_loop():
    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t-agent"),
        set_current_reasoning=lambda text: None,
        _round_usage=None,
    )
    return OpenAILoop(agent)


class _ScriptedClient:
    """按脚本出牌的流式客户端：每次 chat_stream 弹出一个行为。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        behavior = self.script.pop(0)
        for piece in behavior:
            yield piece


def _reasoning_only_chunk():
    """kai 事故形态：思考块产出到预算耗尽，正文零字节。"""
    return LLMResponse(content="", reasoning_content="（思考…）" * 200, finish_reason="length")


def _ok_chunk():
    return LLMResponse(content="这是正常的回复正文。", finish_reason="stop")


def _long_history():
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(6):
        msgs.append({"role": "user", "content": f"问题 {i}: " + "测" * 400})
        msgs.append({"role": "assistant", "content": f"回答 {i}: " + "答" * 400})
    return msgs


class TestLengthFinishEmptyReplyRecovery:
    @pytest.mark.asyncio
    async def test_length_empty_reply_retries_compacted(self):
        loop = _make_loop()
        client = _ScriptedClient([[_reasoning_only_chunk()], [_ok_chunk()]])
        loop.llm_client = client

        events = [e async for e in loop._predict_stream({"messages": _long_history()})]

        assert len(client.calls) == 2  # 原始请求 + 单次压缩重试
        assert len(client.calls[1]) < len(client.calls[0])  # 重试消息已压缩
        assert any(e.get("type") == "content" and "回复正文" in e.get("data", "") for e in events)
        done = [e for e in events if e.get("type") == "done"]
        assert done and "回复正文" in done[0]["reply"]

    @pytest.mark.asyncio
    async def test_second_empty_reply_yields_first_done_no_third_call(self):
        """重试仍空：原样转发首轮 done，不做第二次重试。"""
        loop = _make_loop()
        client = _ScriptedClient([[_reasoning_only_chunk()], [_reasoning_only_chunk()]])
        loop.llm_client = client

        events = [e async for e in loop._predict_stream({"messages": _long_history()})]

        assert len(client.calls) == 2
        dones = [e for e in events if e.get("type") == "done"]
        assert len(dones) == 1
        # 闭环（审验②补）：重试仍空时 done.reply 被改写为可见提示而非空串——
        # ctx.reply 非空 → 落盘/前端气泡均有内容（杜绝空气泡复发）
        assert dones[0]["reply"], "重试仍空时 reply 必须带可见提示，不允许空串"
        assert "finish_reason" in dones[0] and dones[0]["finish_reason"] == "length"
        # 且先有 content 提示事件（气泡可见）
        contents = [e for e in events if e.get("type") == "content"]
        assert contents and "未能生成回复" in contents[0]["data"]

    @pytest.mark.asyncio
    async def test_normal_reply_no_retry(self):
        """首轮有正文：零行为变化。"""
        loop = _make_loop()
        client = _ScriptedClient([[_ok_chunk()]])
        loop.llm_client = client

        events = [e async for e in loop._predict_stream({"messages": _long_history()})]

        assert len(client.calls) == 1
        dones = [e for e in events if e.get("type") == "done"]
        assert dones and "回复正文" in dones[0]["reply"]

    @pytest.mark.asyncio
    async def test_stop_finish_no_retry(self):
        """finish_reason=stop 且正文空（模型真不想说）：不触发（防把合法静默改写）。"""
        loop = _make_loop()
        client = _ScriptedClient([[LLMResponse(content="", finish_reason="stop")]])
        loop.llm_client = client

        events = [e async for e in loop._predict_stream({"messages": _long_history()})]

        assert len(client.calls) == 1
        dones = [e for e in events if e.get("type") == "done"]
        assert dones and dones[0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_tool_calls_round_no_retry(self):
        """工具调用轮（正文空但 pending_tool_calls 非空）不触发——那是工具循环的合法形态。"""
        loop = _make_loop()
        tool_chunk = LLMResponse(
            content="",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "calculator", "arguments": "{}"}}],
            finish_reason="tool_calls",
        )

        executed = False

        async def fake_handle(calls, messages):
            nonlocal executed
            executed = True
            return [{"role": "tool", "tool_call_id": "c1", "content": "42"}]

        loop.handle_tool_calls = fake_handle
        client = _ScriptedClient([[tool_chunk], [_ok_chunk()]])
        loop.llm_client = client

        _ = [e async for e in loop._predict_stream({"messages": _long_history()})]

        # 第一轮走工具路径（handle 被调），不因正文空而压缩重试
        assert executed

    @pytest.mark.asyncio
    async def test_retry_compaction_preserves_protocol(self):
        """重试序列协议合法（无孤儿 tool 消息）。"""
        loop = _make_loop()
        client = _ScriptedClient([[_reasoning_only_chunk()], [_ok_chunk()]])
        loop.llm_client = client

        _ = [e async for e in loop._predict_stream({"messages": _long_history()})]

        retried = client.calls[1]
        for idx, msg in enumerate(retried):
            if msg.get("role") == "tool":
                prev = retried[idx - 1]
                assert prev.get("role") == "assistant" and prev.get("tool_calls"), (
                    f"重试序列存在孤儿 tool 消息 @ {idx}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
