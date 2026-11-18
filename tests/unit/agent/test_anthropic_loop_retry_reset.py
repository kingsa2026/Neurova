# -*- coding: utf-8 -*-
"""QwenPaw 对照批 C2：Anthropic 环的 retry_status/reset 契约。

multi_model_client.chat_stream 在流内 429/切换时产出 ``{"retry_status": ...}``
dict；reset=True 表示"半截回复作废，清空后重来"。OpenAI 环已接线
（openai_loop._predict_stream_once），Anthropic 环必须同一契约——否则
模型 A 的半截正文与模型 B 的续写拼接成一句（两模型缝合回复）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.llm_client import LLMResponse

MODEL = "claude-3-5-sonnet"


class StreamClient:
    """按轮次产出 chunk 的假流式客户端（与 test_anthropicLoopStreamContract 同形）。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat_stream(self, messages=None, **kwargs):
        self.calls.append({"messages": list(messages or []), "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


def makeLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.config.name = "anthropic-probe"
    agent.config.agent_id = "anthropic-probe-id"
    agent.config.llm_model = MODEL
    loop = AnthropicLoop(agent)
    loop.llm_client = client
    agent.llm_client = client
    return loop


def _switchStatus(reset=True):
    payload = {"phase": "switched", "model": "m2", "reason": "rate_limited",
               "fail_count": 1, "max_switches": 3, "switch_count": 1}
    if reset:
        payload["reset"] = True
    return {"retry_status": payload}


class TestAnthropicLoopRetryReset:
    def test_reset_clears_partial_reply_from_failed_candidate(self):
        """切换前已吐的半截正文必须作废：done.reply 只含切换后候选的产出。"""
        client = StreamClient([
            [
                LLMResponse(content="前半"),
                _switchStatus(reset=True),
                LLMResponse(content="后半", finish_reason="stop"),
            ],
        ])
        loop = makeLoop(client)
        messages = [{"role": "user", "content": "你好"}]

        async def go():
            gen = await loop.predict_step(messages, tools=None, stream=True)
            return [e async for e in gen]

        events = asyncio.run(go())
        rs = [e for e in events if isinstance(e, dict) and e.get("type") == "retry_status"]
        assert len(rs) == 1 and rs[0]["data"]["reset"] is True, (
            f"retry_status 事件未转成 typed 事件让出：{[e.get('type') for e in events]}"
        )
        done = [e for e in events if isinstance(e, dict) and e.get("type") == "done"][-1]
        assert done["reply"] == "后半", (
            f"半截回复未作废，两模型输出被拼接：{done['reply']!r}"
        )

    def test_switch_without_prior_content_needs_no_reset(self):
        """切换前无产出：无 reset 标记也不清空（无东西可清），回复完整。"""
        client = StreamClient([
            [
                _switchStatus(reset=False),
                LLMResponse(content="完整回复", finish_reason="stop"),
            ],
        ])
        loop = makeLoop(client)
        messages = [{"role": "user", "content": "你好"}]

        async def go():
            gen = await loop.predict_step(messages, tools=None, stream=True)
            return [e async for e in gen]

        events = asyncio.run(go())
        done = [e for e in events if isinstance(e, dict) and e.get("type") == "done"][-1]
        assert done["reply"] == "完整回复", done


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
