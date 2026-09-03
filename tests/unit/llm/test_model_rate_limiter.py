# -*- coding: utf-8 -*-
"""
P2-a 每模型限流器防回归网（对标 QP beta.5 LLM 限流语义）

核心：per-model 独立限流（QPM 滑动窗 + 并发上限 + 429 全局暂停带抖动）。
"dream/cron 的 429 不拖垮用户聊天"→ 模型 A 的限流状态不影响模型 B。
"""
import time

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.llm.model_rate_limiter import ModelRateLimiter, RateLimitExceeded


class TestPerModelIsolation:
    def test_models_isolated(self):
        limiter = ModelRateLimiter()
        limiter.report_429("model-a", pause_seconds=10)
        # model-a 被暂停，model-b 不受影响
        with pytest.raises(RateLimitExceeded):
            limiter.acquire("model-a", blocking=False)
        limiter.acquire("model-b", blocking=False)  # 不抛

    def test_concurrent_cap_per_model(self):
        limiter = ModelRateLimiter(max_concurrent=2)
        limiter.acquire("m", blocking=False)
        limiter.acquire("m", blocking=False)
        with pytest.raises(RateLimitExceeded):
            limiter.acquire("m", blocking=False)
        limiter.release("m")
        limiter.acquire("m", blocking=False)  # 释放后可再进


class TestQpmWindow:
    def test_qpm_window_blocks_burst(self, monkeypatch):
        limiter = ModelRateLimiter(qpm=5)
        clock = {"t": 1000.0}
        monkeypatch.setattr(limiter, "_now", lambda: clock["t"])
        for _ in range(5):
            limiter.acquire("m", blocking=False)
        with pytest.raises(RateLimitExceeded):
            limiter.acquire("m", blocking=False)
        clock["t"] += 61  # 窗口滑过
        limiter.acquire("m", blocking=False)  # 可再进

    def test_qpm_zero_means_unlimited(self):
        limiter = ModelRateLimiter(qpm=0, max_concurrent=0)  # 0=不限
        for _ in range(50):
            limiter.acquire("m", blocking=False)
            limiter.release("m")


class TestGlobal429Pause:
    def test_429_pause_then_clear(self, monkeypatch):
        limiter = ModelRateLimiter()
        clock = {"t": 100.0}
        monkeypatch.setattr(limiter, "_now", lambda: clock["t"])
        # 固定抖动=1.0（否则 ±50% 随机抖动下快进 6s 可能仍在 7.5s 暂停内，
        # 抽样 flaky）；uniform 返回 0.0 = 区间中点 → jitter 恰为 1.0。
        # 指数退避首次 429 的 base 与旧固定语义一致
        monkeypatch.setattr(
            "neurova.llm.model_rate_limiter.random.uniform", lambda a, b: 0.0
        )
        limiter.report_429("m", pause_seconds=5)
        with pytest.raises(RateLimitExceeded):
            limiter.acquire("m", blocking=False)
        clock["t"] += 6  # 暂停过期
        limiter.acquire("m", blocking=False)

    def test_on_success_clears_pause(self):
        limiter = ModelRateLimiter()
        limiter.report_429("m", pause_seconds=60)
        limiter.report_success("m")  # 成功清除陈旧暂停
        limiter.acquire("m", blocking=False)  # 不抛

    def test_pause_has_jitter(self, monkeypatch):
        limiter = ModelRateLimiter()
        pauses = set()
        real_uniform = __import__("random").uniform
        monkeypatch.setattr(
            "neurova.llm.model_rate_limiter.random.uniform",
            lambda a, b: real_uniform(a, b),
        )
        for _ in range(10):
            limiter.report_429("m", pause_seconds=5)
            pauses.add(limiter.pause_remaining("m"))
        assert len(pauses) > 1  # 抖动生效（pause_remaining 有差异）


class TestChatWiring:
    """multi_model_client.chat 接线：限流 acquire 在 retry 之前；429 反馈暂停"""

    def _make_mmc(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from neurova.llm_client import LLMResponse

        inner_calls = {"n": 0}

        class Inner:
            def chat(self, messages, **kwargs):
                inner_calls["n"] += 1
                return LLMResponse(content="ok")

        client = SimpleNamespace(
            client=Inner(),
            model="test-model",
            provider=SimpleNamespace(id="p1"),
            increment_request=MagicMock(),
        )
        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        mmc._get_client_for_request = lambda model=None, provider_id=None: client
        return mmc, inner_calls

    @pytest.mark.asyncio
    async def test_chat_acquires_and_releases_slot(self, monkeypatch):
        from neurova.llm import model_rate_limiter as mrl

        mmc, calls = self._make_mmc()
        limiter = mrl.ModelRateLimiter(max_concurrent=1)
        monkeypatch.setattr(mrl, "_shared_limiter", limiter, raising=False)

        result = await mmc.chat([{"role": "user", "content": "hi"}])
        assert result["success"] is True
        assert calls["n"] == 1
        # 执行完槽位已释放（并发计数归零）
        assert limiter.current_concurrent("test-model") == 0

    @pytest.mark.asyncio
    async def test_429_error_feeds_pause(self, monkeypatch):
        from neurova.llm import model_rate_limiter as mrl
        from neurova.llm_client import LLMRateLimitError

        mmc, calls = self._make_mmc()
        limiter = mrl.ModelRateLimiter()
        monkeypatch.setattr(mrl, "_shared_limiter", limiter, raising=False)

        class RateLimitedInner:
            def chat(self, messages, **kwargs):
                calls["n"] += 1
                raise LLMRateLimitError("429 slow down")

        # 替换 inner 为限流错误脚本
        mmc._get_client_for_request = lambda model=None, provider_id=None: SimpleNamespace(
            client=RateLimitedInner(),
            model="test-model",
            provider=SimpleNamespace(id="p1"),
            increment_request=MagicMock(),
        )
        # 禁用重试（_chat_with_retry 走原实现会重试 4 次——此处 monkeypatch 跳过）
        async def no_retry(client, messages, **kwargs):
            return await client.client.chat(messages, **kwargs)

        monkeypatch.setattr(type(mmc), "_chat_with_retry", staticmethod(no_retry))

        result = await mmc.chat([{"role": "user", "content": "hi"}])
        assert result["success"] is False
        assert limiter.pause_remaining("test-model") > 0  # 429 反馈成暂停


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
