# -*- coding: utf-8 -*-
"""R6（参照系 ad 追平批二）：usage 缺失诊断。

契约：流式收尾若 usage 缺失（走 tiktoken 估值），必须留下可诊断信息——
缺失原因、本流分片数、其中携带 usage 的分片数——挂在该客户端实例的
``_lastUsageDiagnostics`` 上（None=usage 真实回传，无缺失）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import neurova.llm.multi_model_client as _mmc_mod
from neurova.llm.multi_model_client import ModelClient, MultiModelLLMClient


def _chunk(text):
    return SimpleNamespace(content=text, reasoning_content=None, usage=None,
                           tool_calls=None, finish_reason=None)


class _ScriptedStreamInner:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def chat_stream_async(self, messages, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        for piece in item:
            if isinstance(piece, Exception):
                raise piece
            yield piece


def _wire(inners):
    def fake_create(self, provider, model):
        mc = ModelClient(inners[provider.id], provider, model)
        self._clients[f"{provider.id}/{model}"] = mc
        return mc

    return patch.object(MultiModelLLMClient, "_create_model_client", fake_create)


def _single_pm(tmp_path):
    from neurova.llm.provider_manager import LLMProviderManager

    pm = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    pm.add_provider(name="ad-only", provider="openai", base_url="http://127.0.0.1:1/v1",
                    api_key="sk-only", models=["stub-model"], default_model="stub-model",
                    priority=20)
    return pm


@pytest.mark.asyncio
async def test_missing_usage_attaches_diagnostics(tmp_path):
    """流内有内容但末尾无 usage → 诊断：缺失原因 + 分片计数。"""
    pm = _single_pm(tmp_path)
    inners = {"ad-only": _ScriptedStreamInner([[_chunk("你"), _chunk("好")]])}
    with _wire(inners):
        mmc = MultiModelLLMClient(provider_manager=pm)
        items = await _collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

    assert [getattr(c, "content", None) for c in items if not isinstance(c, dict)] == ["你", "好"]
    diag = mmc._lastUsageDiagnostics
    assert diag is not None
    assert diag["reason"] == "stream_usage_missing"
    assert diag["chunks_seen"] == 2
    assert diag["usage_chunks_seen"] == 0


@pytest.mark.asyncio
async def test_present_usage_means_no_diagnostics(tmp_path):
    """usage 真实回传 → 无诊断（None），不制造假信息。"""
    pm = _single_pm(tmp_path)
    usage_chunk = SimpleNamespace(content="", reasoning_content=None,
                                  usage={"prompt_tokens": 3, "completion_tokens": 5},
                                  tool_calls=None, finish_reason="stop")
    inners = {"ad-only": _ScriptedStreamInner([[_chunk("ok"), usage_chunk]])}
    with _wire(inners):
        mmc = MultiModelLLMClient(provider_manager=pm)
        await _collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

    assert mmc._lastUsageDiagnostics is None


async def _collect(agen):
    return [c async for c in agen]
