# -*- coding: utf-8 -*-
"""R2（参照系 ad 追平批一）：attempt 生命周期账本 + 流式空响应换路。

契约（源自 docs/04-plans/2026-11-22-reference-ad-llm-routing-catchup-
implementation-plan.md R2 卡）：
- 一次逻辑请求内每次 (provider, model) 尝试在 AttemptLedger 记一条，
  结局五态封闭：completed/empty/interrupted/cancelled/failed；
- 空响应（上游正常收流但零载荷）视作**可切换失败**：首可见内容前换下一
  候选，消费方无感；无候选时如实空收流但台账留 empty 痕；
- 中流死亡（已吐可见内容）→ interrupted，走既有 reset+切换协议。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("openai")

import neurova.llm.multi_model_client as _mmc_mod
from neurova.llm.multi_model_client import ModelClient, MultiModelLLMClient
from neurova.llm_client import LLMResponse


def _chunk(text):
    return SimpleNamespace(content=text, reasoning_content=None, usage=None,
                           tool_calls=None, finish_reason=None)


class _ScriptedInner:
    """非流式内层桩（真实 _chat_single_attempt 消费）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        behavior = self.script.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


class _ScriptedStreamInner:
    """流式内层桩：脚本项 Exception→立即抛；list→逐个 yield。"""

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


def _stream_client(inner, model, provider):
    return SimpleNamespace(client=inner, model=model,
                           provider=SimpleNamespace(id=provider),
                           increment_request=lambda success: None)


def _two_provider_pm(tmp_path):
    from neurova.llm.provider_manager import LLMProviderManager

    pm = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    pm.add_provider(name="ad-bad", provider="openai", base_url="http://127.0.0.1:1/v1",
                    api_key="sk-bad", models=["stub-model"], default_model="stub-model",
                    priority=20)
    pm.add_provider(name="ad-good", provider="openai", base_url="http://127.0.0.1:2/v1",
                    api_key="sk-good", models=["stub-model"], default_model="stub-model",
                    priority=10)
    return pm


def _wire_stream(inners):
    def fake_create(self, provider, model):
        mc = ModelClient(inners[provider.id], provider, model)
        self._clients[f"{provider.id}/{model}"] = mc
        return mc

    return patch.object(MultiModelLLMClient, "_create_model_client", fake_create)


async def _collect(agen):
    return [c async for c in agen]


class TestStreamEmptyResponseSwitch:
    @pytest.mark.asyncio
    async def test_empty_stream_switches_to_next_candidate(self, tmp_path):
        """空响应（零载荷收流）必须视作可切换失败，消费方拿到下一候选的完整输出。"""
        pm = _two_provider_pm(tmp_path)
        inners = {
            "ad-bad": _ScriptedStreamInner([[]]),          # 空流：正常收流但零载荷
            "ad-good": _ScriptedStreamInner([[_chunk("b-ok")]]),
        }
        with _wire_stream(inners):
            mmc = MultiModelLLMClient(provider_manager=pm)
            items = await _collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

        chunks = [c for c in items if not isinstance(c, dict)]
        assert [c.content for c in chunks] == ["b-ok"]

    @pytest.mark.asyncio
    async def test_empty_stream_without_candidate_is_honest_empty(self, tmp_path):
        """无候选可切时保持诚实空收流（不造内容），但台账必须留 empty 痕。"""
        from neurova.llm.provider_manager import LLMProviderManager

        pm = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
        pm.add_provider(name="ad-only", provider="openai", base_url="http://127.0.0.1:1/v1",
                        api_key="sk-only", models=["stub-model"], default_model="stub-model",
                        priority=20)
        inners = {"ad-only": _ScriptedStreamInner([[]])}
        with _wire_stream(inners):
            mmc = MultiModelLLMClient(provider_manager=pm)
            items = await _collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

        chunks = [c for c in items if not isinstance(c, dict)]
        assert chunks == []
        ledger = mmc._lastAttemptLedger
        assert ledger is not None
        assert ledger.outcomes == ["empty"]


class TestAttemptLedger:
    @pytest.mark.asyncio
    async def test_stream_ledger_failed_then_completed(self, tmp_path):
        """首可见内容前 401 → failed；换候选成功 → completed。"""
        pm = _two_provider_pm(tmp_path)
        inners = {
            "ad-bad": _ScriptedStreamInner([Exception("Error code: 401 - invalid api key")]),
            "ad-good": _ScriptedStreamInner([[_chunk("b-ok")]]),
        }
        with _wire_stream(inners):
            mmc = MultiModelLLMClient(provider_manager=pm)
            await _collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

        ledger = mmc._lastAttemptLedger
        assert ledger is not None
        assert ledger.outcomes == ["failed", "completed"]
        assert ledger.records[0].provider_id == "ad-bad"
        assert ledger.records[1].provider_id == "ad-good"

    @pytest.mark.asyncio
    async def test_midstream_death_marks_interrupted(self, tmp_path):
        """已吐可见内容后中流死亡 → interrupted（非 failed），换候选重出全文。"""
        pm = _two_provider_pm(tmp_path)
        inners = {
            "ad-bad": _ScriptedStreamInner([[_chunk("半截"), Exception("connection reset by peer")]]),
            "ad-good": _ScriptedStreamInner([[_chunk("完整")]]),
        }
        with _wire_stream(inners):
            mmc = MultiModelLLMClient(provider_manager=pm)
            items = await _collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

        chunks = [c for c in items if not isinstance(c, dict)]
        assert [c.content for c in chunks] == ["半截", "完整"]
        assert mmc._lastAttemptLedger.outcomes == ["interrupted", "completed"]

    @pytest.mark.asyncio
    async def test_chat_failover_ledger(self, tmp_path):
        """非流式：transient 失败 → 换候选成功，台账 [failed, completed]。"""
        pm = _two_provider_pm(tmp_path)
        inners = {
            "ad-bad": _ScriptedInner([Exception("Connection error: refused")]),
            "ad-good": _ScriptedInner([LLMResponse(content="ok-reply")]),
        }
        with _wire_stream(inners):
            mmc = MultiModelLLMClient(provider_manager=pm)
            result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result.get("success") is True
        assert mmc._lastAttemptLedger.outcomes == ["failed", "completed"]
