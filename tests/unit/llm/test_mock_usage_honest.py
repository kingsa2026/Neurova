# -*- coding: utf-8 -*-
"""mock 响应的 usage 诚实化（fullrepo 审计 2026-11-18 D 组）。

红灯依据：_build_mock_response 把最后一条用户消息的**字符长度**当作
prompt_tokens 记账（completion 恒 8）——mock 本不产生真实 token，假计数
会经 usage_history.record 链污染用量/成本面。改为如实报 0。
"""
from neurova.llm.multi_model_client import _build_mock_response


def test_mock_response_usage_is_zero_not_char_count():
    resp = _build_mock_response([{"role": "user", "content": "hello world"}])
    assert resp.content.startswith("[mock-llm]"), "mock 回显契约不变"
    assert resp.usage["prompt_tokens"] == 0, "mock 不产真实 token，不得拿字符数冒充"
    assert resp.usage["completion_tokens"] == 0
    assert resp.usage["total_tokens"] == 0
