# -*- coding: utf-8 -*-
"""legacy 流式路的错误分类只许有一处实现。

`_raise_for_llm_error_dict`（管线侧）与 `BaseAgentLoop._raise_for_error_dict`
（环侧）本是同一件事的两份：同一张五类键表、同一套消息兜底、只是文案与兜底
类型略有出入。两份并存的结果是「同一条上游错误，走环路被判成可重试、
走 legacy 路被判成不可重试」——供应商错误守卫据此决定要不要 fallback，
于是同一份坏配置在两路上表现不同。

判据：两路对同一份错误 dict 必须给出**同一个类别**，且 legacy 路不得再持有
自己的分类实现。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.legacy_stream_reader import LegacyStreamReader
from neurova.agent.loops.base import BaseAgentLoop
from neurova.llm_client import (
    LLMAuthError,
    LLMBadRequestError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
)

CASES = [
    ({"error": "x", "error_type": "rate_limited"}, LLMRateLimitError),
    ({"error": "x", "error_type": "service_unavailable"}, LLMServiceUnavailableError),
    ({"error": "x", "error_type": "connection_failed"}, LLMConnectionError),
    ({"error": "x", "error_type": "auth_failed"}, LLMAuthError),
    ({"error": "x", "error_type": "bad_request"}, LLMBadRequestError),
    # 无 error_type 的历史 dict：消息兜底也得走同一张表
    ({"error": "404 model route not found"}, LLMBadRequestError),
    ({"error": "429 too many requests"}, LLMRateLimitError),
    ({"error": "401 unauthorized"}, LLMAuthError),
]


@pytest.mark.parametrize("chunk,expected", CASES)
def testLegacyStreamRaisesTheLoopCategory(chunk, expected):
    """错误 dict 经 legacy 读取循环抛出的类别，与环侧分类器一致。"""
    pipeline = ChatPipeline.__new__(ChatPipeline)
    agent = SimpleNamespace(llm_client=SimpleNamespace(chat_stream=None))
    pipeline._agent = agent

    async def stream(_messages):
        yield chunk

    ctx = ChatContext(user_input="hi", stream=True, context=[{"role": "user", "content": "hi"}])
    reader = LegacyStreamReader()
    with pytest.raises(expected):
        asyncio.run(reader.consume(stream(None), {"metadata": {}}))


def testPipelineHoldsNoSecondClassifier():
    """管线不得再留一份分类实现（同一件事两个事实源）。"""
    assert not hasattr(ChatPipeline, "_raise_for_llm_error_dict")
    assert callable(BaseAgentLoop._raise_for_error_dict)
