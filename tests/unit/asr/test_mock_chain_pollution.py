# -*- coding: utf-8 -*-
"""ASR 测试态 mock 不得污染全局 fallback 链（fullrepo 审计 2026-11-18 D 组）。

红灯依据：manager.initialize() 在 NEUROVA_ENV=test 时对模块级
FALLBACK_CHAIN 原地 append("mock") 且永不恢复——同进程后续所有实例
（含非测试态）都会把 mock 纳入 fallback（动态探针已实证：
chain after m1 = ['funasr', 'remote_whisper', 'whisper', 'mock']）。
"""
import asyncio

from neurova.asr.manager import ASRConfig, ASRManager, FALLBACK_CHAIN


def _stub_all_real_engines_fail(monkeypatch):
    """真引擎（funasr/remote_whisper/whisper）全部初始化失败，仅 mock 成功。"""

    async def fake_init(self, engine_name):
        # 桩须与真 _initialize_engine 一样在成功时落实例状态
        if engine_name == "mock":
            self._engine_name = "mock"
            self._initialized = True
            return True
        return False

    monkeypatch.setattr(ASRManager, "_initialize_engine", fake_init)


def test_test_env_mock_stays_local_to_the_instance_chain(monkeypatch):
    monkeypatch.setenv("NEUROVA_ENV", "test")
    _stub_all_real_engines_fail(monkeypatch)
    original = list(FALLBACK_CHAIN)
    try:
        m1 = ASRManager(ASRConfig(engine="auto", lazy=False))
        assert asyncio.run(m1.initialize()) is True
        assert m1.engine_name == "mock", "测试态仍应能落到 mock（本地链副本）"
        # 全局链不被改写：mock 只存在于本次初始化的本地链副本
        assert "mock" not in FALLBACK_CHAIN, "测试态把 mock 写进了全局链且不恢复"
        # 同进程后续实例：链同样干净
        m2 = ASRManager(ASRConfig(engine="auto", lazy=False))
        assert asyncio.run(m2.initialize()) is True
        assert "mock" not in FALLBACK_CHAIN
    finally:
        # 红灯跑完也不让污染扩散到同会话其他用例
        FALLBACK_CHAIN[:] = original


def test_mock_landing_warns_and_marks_stats(monkeypatch, caplog):
    monkeypatch.setenv("NEUROVA_ENV", "test")
    _stub_all_real_engines_fail(monkeypatch)
    m1 = ASRManager(ASRConfig(engine="auto", lazy=False))
    assert asyncio.run(m1.initialize()) is True
    assert m1.engine_name == "mock"
    assert m1.stats.get("mock_active") is True, "落到 mock 必须在 stats 里如实标注"
    assert any(
        "mock" in r.getMessage().lower() and r.levelname == "WARNING"
        for r in caplog.records
    ), "落到 mock 必须打警告（不能只有 info）"
