# -*- coding: utf-8 -*-
"""ASR 惰性加载（2026-11-24）：启动只标记待加载，首次转写/理解/描述才初始化引擎。

生产态启动路径上的 funasr/torch 模型加载（~19s，且内存压力下 torch.load
原生段错误、api 回归两次实崩）是启动耗时的最大单项——惰性化后启动不再
触碰大模型，首次使用才走 fallback 链。测试态 mock 链首语义不变。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.asr.manager import ASRConfig, ASRManager


class _StubEngine:
    def __init__(self):
        self._initialized = True

    @property
    def is_initialized(self):
        return self._initialized

    async def initialize(self):
        return True

    async def transcribe(self, audio_bytes, **kwargs):
        return {"text": "stub"}

    async def understand(self, audio_bytes, query=""):
        return {"answer": "stub"}

    async def caption(self, audio_bytes):
        return {"caption": "stub"}

    async def shutdown(self):
        return None


@pytest.fixture()
def harness(monkeypatch):
    monkeypatch.delenv("NEUROVA_ENV", raising=False)
    calls = {"engines": []}

    async def fake_init(self, engine_name):
        calls["engines"].append(engine_name)
        self._engine = _StubEngine()
        self._engine_name = engine_name
        self._initialized = True
        self._available_engines[engine_name] = True
        return True

    monkeypatch.setattr(ASRManager, "_initialize_engine", fake_init)
    manager = ASRManager()  # 默认 config：engine=auto, lazy=True
    return manager, calls


def test_initialize_lazy_defers_engine_load(harness):
    manager, calls = harness
    assert asyncio.run(manager.initialize()) is True
    assert manager._engine is None, "惰性初始化不得加载引擎实例"
    assert calls["engines"] == [], "惰性初始化不得走 fallback 链（funasr/torch 零接触）"
    assert manager.is_initialized is True, "惰性待载应被视为可用（读面 503 门放行）"


def test_transcribe_triggers_engine_load_on_first_use(harness):
    manager, calls = harness
    assert asyncio.run(manager.initialize()) is True
    assert asyncio.run(manager.transcribe(b"audio")) == {"text": "stub"}
    # pytest 在场 = 测试态：链首 mock（funasr/torch 不进测试进程）
    assert calls["engines"] == ["mock"]


def test_understand_and_caption_trigger_load(harness):
    manager, calls = harness
    asyncio.run(manager.initialize())
    assert asyncio.run(manager.understand(b"a", "q"))["answer"] == "stub"
    assert asyncio.run(manager.caption(b"a"))["caption"] == "stub"
    # 测试态链首 mock（见上）
    assert calls["engines"] == ["mock"]


def test_lazy_chain_failure_returns_honest_error(harness, monkeypatch):
    async def fail_init(self, engine_name):
        self._available_engines[engine_name] = False
        return False

    monkeypatch.setattr(ASRManager, "_initialize_engine", fail_init)
    manager, _ = harness
    asyncio.run(manager.initialize())
    result = asyncio.run(manager.transcribe(b"audio"))
    assert result.get("text") == "" and "error" in result, "链全失败必须诚实报错"


def test_non_lazy_mode_loads_at_initialize(monkeypatch):
    """显式 lazy=False 保持既有行为：initialize 即走链加载。"""
    monkeypatch.delenv("NEUROVA_ENV", raising=False)
    calls = {"engines": []}

    async def fake_init(self, engine_name):
        calls["engines"].append(engine_name)
        return True

    monkeypatch.setattr(ASRManager, "_initialize_engine", fake_init)
    manager = ASRManager(ASRConfig(lazy=False))
    assert asyncio.run(manager.initialize()) is True
    assert calls["engines"], "非惰性模式保持启动即加载（既有行为）"


def test_shutdown_without_engine_safe(harness):
    manager, _ = harness
    asyncio.run(manager.initialize())
    asyncio.run(manager.shutdown())  # 无引擎实例时 shutdown 不得报错
    assert manager.is_initialized is False
