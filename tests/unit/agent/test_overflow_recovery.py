"""
P1-1① 上下文管线期① — openai_loop 溢出恢复接线测试

语义（对标 QP scroll 的单次恢复重试）：
- 请求打开即 token_limit → 折叠消息后单次重试
- 重试仍溢出 → 原样抛 TokenLimitExceeded（不做第二次重试，防循环）
- 流中途溢出（已有 content 产出）→ 原样抛（重试会造成内容重复）
- 非 overflow 错误（rate_limit 等）→ 不触发恢复
"""

import json
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse, TokenLimitExceeded


def _make_loop():
    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t-agent"),
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
        if isinstance(behavior, Exception):
            # 流式错误以 dict 形式出现（openai_loop._raise_for_error_dict 契约）
            yield {
                "error": str(behavior),
                "error_type": getattr(behavior, "error_type_name", "token_limit"),
            }
            return
        for piece in behavior:
            yield piece


def _token_limit_error():
    err = TokenLimitExceeded("This model's maximum context length is exceeded")
    err.error_type_name = "token_limit"
    return err


def _rate_limit_error():
    from neurova.llm_client import LLMRateLimitError

    err = LLMRateLimitError("rate limited")
    err.error_type_name = "rate_limit"
    return err


def _big_messages():
    """构造 5 轮工具轮的大消息序列（含合法 tool 配对）。"""
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(5):
        msgs.append({"role": "user", "content": f"question {i}"})
        msgs.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"c{i}", "type": "function",
                "function": {"name": "t", "arguments": "{}"},
            }],
        })
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i} " * 200})
        msgs.append({"role": "assistant", "content": f"answer {i}"})
    return msgs


class TestPredictStreamOverflowRecovery:
    @pytest.mark.asyncio
    async def test_retry_once_with_compacted_messages(self):
        loop = _make_loop()
        ok_stream = [LLMResponse(content="recovered")]
        client = _ScriptedClient([_token_limit_error(), ok_stream])
        loop.llm_client = client

        events = [e async for e in loop._predict_stream({"messages": _big_messages()})]

        assert len(client.calls) == 2  # 原始请求 + 单次重试
        assert len(client.calls[1]) < len(client.calls[0])  # 重试消息已折叠
        assert any(e.get("type") == "content" and e.get("data") == "recovered" for e in events)

    @pytest.mark.asyncio
    async def test_second_overflow_raises_no_third_call(self):
        loop = _make_loop()
        client = _ScriptedClient([_token_limit_error(), _token_limit_error()])
        loop.llm_client = client

        with pytest.raises(TokenLimitExceeded):
            _ = [e async for e in loop._predict_stream({"messages": _big_messages()})]

        assert len(client.calls) == 2  # 单次重试语义，无第三次

    @pytest.mark.asyncio
    async def test_mid_stream_overflow_propagates(self):
        """已有 content 产出后再溢出：重试会造成内容重复，必须原样抛。"""
        loop = _make_loop()
        client = _ScriptedClient([
            [LLMResponse(content="partial"), {"error": "max context", "error_type": "token_limit"}],
        ])
        loop.llm_client = client

        with pytest.raises(TokenLimitExceeded):
            _ = [e async for e in loop._predict_stream({"messages": _big_messages()})]

        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_non_overflow_error_no_recovery(self):
        loop = _make_loop()
        client = _ScriptedClient([_rate_limit_error()])
        loop.llm_client = client

        with pytest.raises(Exception) as exc_info:
            _ = [e async for e in loop._predict_stream({"messages": _big_messages()})]
        assert not isinstance(exc_info.value, TokenLimitExceeded)
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_retry_messages_remain_protocol_valid(self):
        loop = _make_loop()
        client = _ScriptedClient([_token_limit_error(), [LLMResponse(content="ok")]])
        loop.llm_client = client

        _ = [e async for e in loop._predict_stream({"messages": _big_messages()})]

        retried = client.calls[1]
        for idx, msg in enumerate(retried):
            if msg.get("role") == "tool":
                prev = retried[idx - 1]
                assert prev.get("role") == "assistant" and prev.get("tool_calls"), (
                    f"重试序列存在孤儿 tool 消息 @ {idx}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
