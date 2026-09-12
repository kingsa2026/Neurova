# -*- coding: utf-8 -*-
"""LLM 测试套件共享 fixtures。

429 同模型等待重试（2026-09-11 ZCode 对齐）在 chat()/chat_stream 中引入
真实 10s 级等待——单元测试验证的是决策逻辑而非 wall-clock，统一桩掉
``MultiModelLLMClient._sleep_for_retry``（等待时长/次数契约的显式断言
见 test_chat_stream_429_retry.py，该文件按实例注入自己的记录桩）。
"""
import pytest

import neurova.llm.multi_model_client as _mmc_mod


@pytest.fixture(autouse=True)
def _fast_429_retry_sleep(monkeypatch, tmp_path):
    # 设置页持久化文件隔离：llm 套件不受真实 data/llm_retry_settings.json 影响
    monkeypatch.setenv("NEUROVA_LLM_RETRY_SETTINGS", str(tmp_path / "llm_retry.json"))

    async def _instant_sleep(self, seconds):
        return None

    monkeypatch.setattr(_mmc_mod.MultiModelLLMClient, "_sleep_for_retry", _instant_sleep)
    yield
