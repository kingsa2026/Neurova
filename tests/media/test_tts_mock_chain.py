# -*- coding: utf-8 -*-
"""TTS 默认 fallback 链不含 mock（fullrepo 审计 2026-11-18 D 组，对齐 ASR 补课 4.1）。

红灯依据：TTSManager 默认链 [moss-nano, edge-tts, sapi5, mock]——生产里
三真引擎全倒下时静默落 mock（假音频），仅有 info 级日志。mock 只允许
显式 engine="mock" 或 NEUROVA_ENV=test 时参与（本地追加，不污染全局链）。
"""
import asyncio

from neurova.tts.manager import TTSConfig, TTSManager, FALLBACK_CHAIN


def test_default_chain_excludes_mock():
    assert "mock" not in FALLBACK_CHAIN, "默认链里的 mock 会在生产静默吐假音频"
    mgr = TTSManager(TTSConfig(engine="auto"))
    assert "mock" not in mgr.fallback_chain


def test_test_env_appends_mock_locally(monkeypatch):
    monkeypatch.setenv("NEUROVA_ENV", "test")
    mgr = TTSManager(TTSConfig(engine="auto"))
    assert mgr.fallback_chain[-1] == "mock", "测试态 mock 追加到本地链尾"
    assert "mock" not in FALLBACK_CHAIN, "全局链不被改写"


def test_explicit_mock_engine_still_works():
    mgr = TTSManager(TTSConfig(engine="mock"))
    assert asyncio.run(mgr.initialize()) is True
    assert mgr.engine_name == "mock"
    assert mgr.stats.get("mock_active") is True


def test_fallback_landing_on_mock_warns_and_marks_stats(monkeypatch, caplog):
    monkeypatch.setenv("NEUROVA_ENV", "test")

    async def fake_init(self, engine_name):
        # 桩须与真 _initialize_engine 一样在成功时落实例状态，
        # 否则 initialize() 后 engine_name 仍是 None
        if engine_name == "mock":
            self._engine_name = "mock"
            self._initialized = True
            return True
        return False

    monkeypatch.setattr(TTSManager, "_initialize_engine", fake_init)
    mgr = TTSManager(TTSConfig(engine="auto"))
    assert asyncio.run(mgr.initialize()) is True
    assert mgr.engine_name == "mock"
    assert mgr.stats.get("mock_active") is True, "落到 mock 必须在 stats 里如实标注"
    assert any(
        "mock" in r.getMessage().lower() and r.levelname == "WARNING"
        for r in caplog.records
    ), "落到 mock 必须打警告（不能只有 info）"
