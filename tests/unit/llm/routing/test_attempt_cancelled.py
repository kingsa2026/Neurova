# -*- coding: utf-8 -*-
"""R2 收尾（批一遗留清偿）：消费方中断/取消 → CANCELLED 结局标定。

批一执行记录遗留：CANCELLED 枚举已备但消费方中断路径未单独标定——
GeneratorExit 经 finally 收尾，attempt 记录悬在默认 failed 态。本组契约：
- 流式消费方 aclose（GeneratorExit）→ CANCELLED；
- 流式消费任务取消（CancelledError 打进生成器挂起点）→ CANCELLED；
- 非流式 chat 任务取消（CancelledError）→ CANCELLED。
取消不是 provider 失败：不得 increment_request(success=False)。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from neurova.llm.multi_model_client import ModelClient, MultiModelLLMClient
from neurova.llm_client import LLMResponse


class _HangAfterFirstStream:
    """流式内层桩：吐一个内容分片后永久挂起（模拟上游停滞/消费方中途放弃）。"""

    def __init__(self):
        self.calls = 0

    async def chat_stream_async(self, messages, **kwargs):
        self.calls += 1
        yield SimpleNamespace(content="first", reasoning_content=None,
                              usage=None, tool_calls=None, finish_reason=None)
        await asyncio.Event().wait()  # 永不置位


class _HangingChat:
    """非流式内层桩：chat 永久挂起。"""

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        await asyncio.Event().wait()
        return LLMResponse(content="never")


def _one_provider_pm(tmp_path):
    from neurova.llm.provider_manager import LLMProviderManager

    pm = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    pm.add_provider(name="ad-only", provider="openai", base_url="http://127.0.0.1:1/v1",
                    api_key="sk-only", models=["stub-model"], default_model="stub-model",
                    priority=20)
    return pm


def _wire(inner):
    def fake_create(self, provider, model):
        mc = ModelClient(inner, provider, model)
        self._clients[f"{provider.id}/{model}"] = mc
        return mc

    return patch.object(MultiModelLLMClient, "_create_model_client", fake_create)


class TestStreamConsumerCancel:
    @pytest.mark.asyncio
    async def test_stream_aclose_marks_cancelled(self, tmp_path):
        """消费方 aclose（GeneratorExit）→ 台账 CANCELLED，不悬 failed。"""
        pm = _one_provider_pm(tmp_path)
        inner = _HangAfterFirstStream()
        with _wire(inner):
            mmc = MultiModelLLMClient(provider_manager=pm)
            agen = mmc.chat_stream([{"role": "user", "content": "hi"}])
            first = await agen.__anext__()
            assert getattr(first, "content", "") == "first"
            await agen.aclose()

        assert mmc._lastAttemptLedger is not None
        assert mmc._lastAttemptLedger.outcomes == ["cancelled"]

    @pytest.mark.asyncio
    async def test_stream_task_cancel_marks_cancelled(self, tmp_path):
        """消费任务取消（CancelledError 打进生成器挂起点）→ 台账 CANCELLED。"""
        pm = _one_provider_pm(tmp_path)
        inner = _HangAfterFirstStream()
        with _wire(inner):
            mmc = MultiModelLLMClient(provider_manager=pm)

            async def consume():
                # 持续消费（不 break），让取消打进生成器内部的挂起 await
                async for _chunk in mmc.chat_stream([{"role": "user", "content": "hi"}]):
                    pass

            task = asyncio.ensure_future(consume())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert mmc._lastAttemptLedger.outcomes == ["cancelled"]


class TestChatTaskCancel:
    @pytest.mark.asyncio
    async def test_chat_cancel_marks_cancelled(self, tmp_path):
        """非流式 chat 任务取消 → 台账 CANCELLED。"""
        pm = _one_provider_pm(tmp_path)
        inner = _HangingChat()
        with _wire(inner):
            mmc = MultiModelLLMClient(provider_manager=pm)
            task = asyncio.ensure_future(
                mmc.chat([{"role": "user", "content": "hi"}]))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert mmc._lastAttemptLedger.outcomes == ["cancelled"]
