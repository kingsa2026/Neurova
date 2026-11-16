# -*- coding: utf-8 -*-
"""S5 移交悬空 R6：OpenAIAdapter.stream_call 空桩诚实化（教义第 2 条）。

`stream_call` 曾是 `pass` 空桩——签名许诺 `Generator[str]` 却静默返回
None：任何调用方迭代它都会以 `TypeError: 'NoneType' object is not
iterable` 在别处炸，报错点与根因无关。

修复判据：改 raise NotImplementedError 点名未实现，把隐式炸变显式炸。

grep 复核（2026-11-17）：全仓无生产消费方——基类
`LLMAbstractProvider.stream_call` 是 @abstractmethod 占位（adapters 目录
仅 openai_adapter.py 一份实现）；`tests/llm/test_usage_history_wiring.py`
的 stream 用例走 MultiModelLLMClient 自建 SimpleNamespace 桩，与
OpenAIAdapter 无关。实现真流式属新建能力，另立批次。
"""
import asyncio

import pytest

from neurova.llm.adapters.openai_adapter import OpenAIAdapter
from neurova.llm.interfaces.provider_interface import Message, ProviderConfig


def _adapter() -> OpenAIAdapter:
    return OpenAIAdapter(ProviderConfig(api_key="k", model_name="gpt-4o-mini"))


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def testStreamCallRaisesNotImplementedInsteadOfSilentNone():
    """调用 stream_call 必须显式抛 NotImplementedError 点名未实现。"""
    adapter = _adapter()
    with pytest.raises(NotImplementedError) as excInfo:
        asyncio.run(adapter.stream_call([_msg("user", "ping")]))
    message = str(excInfo.value)
    assert "stream_call" in message, f"报错未点名方法: {message}"
    assert "未实现" in message, f"报错未说明是未实现: {message}"
