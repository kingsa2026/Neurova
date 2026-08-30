"""legacy 流式 fallback 契约（LLMResponse 对象流）

实测缺陷：Agent Loop 抛错（如 LLM 限流）fallback 到 _call_legacy_stream 时，
llm_client.chat_stream 产出的已是 LLMResponse 对象（与 _predict_stream 同契约），
旧代码 `reply_parts.append(chunk)` 把对象当字符串 join →
TypeError: sequence item 0: expected str instance, LLMResponse found
—— 掩盖了真实的 LLM 错误（AGENTS.md：不得从表面抹除报错）。
"""

import pytest
from unittest.mock import MagicMock

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.llm_client import LLMResponse


def _pipeline_with_stream(chunks):
    agent = MagicMock()

    async def _stream(*args, **kwargs):
        for c in chunks:
            yield c

    llm = MagicMock()
    llm.chat_stream = _stream
    agent.llm_client = llm
    pipeline = ChatPipeline(agent)
    return pipeline


@pytest.mark.asyncio
async def test_legacy_stream_joins_llmresponse_content():
    """LLMResponse 流必须拼接 content 而非对象本身"""
    pipeline = _pipeline_with_stream(
        [
            LLMResponse(content="你", finish_reason=None),
            LLMResponse(content="好", finish_reason="stop"),
        ]
    )
    ctx = ChatContext(user_input="hi", stream=True)

    reply = await pipeline._call_legacy_stream(ctx)

    assert reply == "你好"


@pytest.mark.asyncio
async def test_legacy_stream_error_dict_raises_original_error():
    """错误 dict 必须以原始信息抛 RuntimeError，不得退化成 TypeError"""
    pipeline = _pipeline_with_stream(
        [
            {"error": "API 错误: Request rate increased too quickly"},
        ]
    )
    ctx = ChatContext(user_input="hi", stream=True)

    with pytest.raises(RuntimeError) as exc:
        await pipeline._call_legacy_stream(ctx)

    assert "Request rate" in str(exc.value)


@pytest.mark.asyncio
async def test_legacy_stream_forwards_content_to_emitter():
    """fallback 流式同样要向 emitter 转 content，前端才有流式输出"""
    events = []
    pipeline = _pipeline_with_stream(
        [
            LLMResponse(content="你", finish_reason=None),
            LLMResponse(content="好", finish_reason="stop"),
        ]
    )
    ctx = ChatContext(user_input="hi", stream=True, event_emitter=lambda k, d: events.append((k, d)))

    reply = await pipeline._call_legacy_stream(ctx)

    assert reply == "你好"
    assert ("content", "你") in events
    assert ("content", "好") in events
