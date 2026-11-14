# -*- coding: utf-8 -*-
"""LLM 弹性包（P2-9）：进程级准入票据 + 时间窗重试预算。

- 准入票据：全进程在飞 LLM 调用上限（默认 0=不限），抢不到票快速失败
  为可 fallback 的「系统忙」，不无限排队；
- 重试预算：时间窗内全进程重试次数上限（防失败风暴的重试雪崩）——
  预算耗尽立即停止重试（走 fallback/失败）；
- 两者均为进程级单例（DCL），env 可调。
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from neurova.llm.providers.rate_limiter import (
    ExponentialBackoff,
    RetryConfig,
    with_retry_and_circuit_breaker,
)
from neurova.llm.resilience import (
    AdmissionTickets,
    RetryBudget,
    getSharedAdmission,
    getSharedRetryBudget,
)


class TestAdmissionTickets:
    def test_unlimited_when_max_zero(self):
        adm = AdmissionTickets(maxInFlight=0)
        assert adm.maxInFlight == 0
        for _ in range(100):
            assert adm.tryAcquire() is True
        assert adm.inFlight == 100
        for _ in range(100):
            adm.release()
        assert adm.inFlight == 0

    def test_exhaustion_and_release(self):
        adm = AdmissionTickets(maxInFlight=2)
        assert adm.tryAcquire() is True
        assert adm.tryAcquire() is True
        assert adm.tryAcquire(timeout=0) is False
        assert adm.inFlight == 2
        adm.release()
        assert adm.tryAcquire(timeout=0) is True

    def test_acquire_with_timeout_waits_for_release(self):
        adm = AdmissionTickets(maxInFlight=1)
        assert adm.tryAcquire() is True

        async def scenario():
            async def releaser():
                await asyncio.sleep(0.05)
                adm.release()

            task = asyncio.create_task(releaser())
            got = await adm.acquireAsync(timeout=2.0)
            await task
            return got

        assert asyncio.run(scenario()) is True

    def test_acquire_async_timeout_returns_false(self):
        adm = AdmissionTickets(maxInFlight=1)
        adm.tryAcquire()

        async def scenario():
            return await adm.acquireAsync(timeout=0.05)

        assert asyncio.run(scenario()) is False


class TestRetryBudget:
    def test_consume_within_window(self):
        budget = RetryBudget(maxRetries=3, windowSeconds=60)
        assert [budget.tryConsume() for _ in range(3)] == [True, True, True]
        assert budget.tryConsume() is False
        assert budget.remaining == 0

    def test_window_reset(self, monkeypatch):
        import neurova.llm.resilience as rz

        clock = {"now": 1000.0}
        monkeypatch.setattr(rz.time, "monotonic", lambda: clock["now"])
        budget = RetryBudget(maxRetries=2, windowSeconds=10)
        assert budget.tryConsume() and budget.tryConsume()
        assert budget.tryConsume() is False
        clock["now"] += 11.0  # 跨窗：预算重置
        assert budget.tryConsume() is True

    def test_thread_safety_caps_total_consumption(self):
        budget = RetryBudget(maxRetries=5, windowSeconds=60)
        granted = []

        def worker():
            for _ in range(20):
                if budget.tryConsume():
                    granted.append(1)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(granted) == 5


class TestBackoffHonorsBudget:
    def _flaky(self, state):
        async def _call():
            state["attempts"] += 1
            if state["attempts"] < state["fail_until"]:
                raise ConnectionError("net down")
            return "ok"

        return _call

    def test_budget_exhausted_stops_retrying(self):
        budget = RetryBudget(maxRetries=1, windowSeconds=60)
        rc = RetryConfig(max_attempts=5, initial_delay=0, max_delay=0, retry_budget=budget)
        backoff = ExponentialBackoff(
            max_attempts=5, initial_delay=0, max_delay=0, retry_budget=budget
        )
        state = {"attempts": 0, "fail_until": 99}

        async def scenario():
            try:
                await backoff.aretry(self._flaky(state))
            except ConnectionError:
                return state["attempts"]
            return state["attempts"]

        # 预算只容 1 次重试：第 2 次重试被拒，总尝试停在 2（而非 5）
        assert asyncio.run(scenario()) == 2

    def test_no_budget_keeps_full_attempts(self):
        backoff = ExponentialBackoff(max_attempts=4, initial_delay=0, max_delay=0)
        state = {"attempts": 0, "fail_until": 99}

        async def scenario():
            try:
                await backoff.aretry(self._flaky(state))
            except ConnectionError:
                return state["attempts"]
            return state["attempts"]

        assert asyncio.run(scenario()) == 4

    def test_retry_config_carries_budget(self):
        budget = RetryBudget(maxRetries=7, windowSeconds=60)
        rc = RetryConfig(retry_budget=budget)
        assert rc.retry_budget is budget

    def test_decorator_passes_budget_to_backoff(self):
        budget = RetryBudget(maxRetries=1, windowSeconds=60)
        rc = RetryConfig(max_attempts=5, initial_delay=0, max_delay=0, retry_budget=budget)
        state = {"attempts": 0, "fail_until": 99}

        wrapped = with_retry_and_circuit_breaker(retry_config=rc)(self._flaky(state))

        async def scenario():
            try:
                await wrapped()
            except ConnectionError:
                return state["attempts"]
            return state["attempts"]

        assert asyncio.run(scenario()) == 2


class TestSharedSingletons:
    def test_shared_singletons_dcl(self):
        assert getSharedRetryBudget() is getSharedRetryBudget()
        assert getSharedAdmission() is getSharedAdmission()

    def test_shared_budget_env_tunable(self, monkeypatch):
        import neurova.llm.resilience as rz

        monkeypatch.setenv("NEUROVA_LLM_RETRY_BUDGET_PER_MIN", "42")
        monkeypatch.setattr(rz, "_sharedRetryBudget", None)
        assert getSharedRetryBudget().maxRetries == 42
        monkeypatch.setattr(rz, "_sharedRetryBudget", None)

    def test_shared_admission_env_tunable(self, monkeypatch):
        import neurova.llm.resilience as rz

        monkeypatch.setenv("NEUROVA_LLM_MAX_INFLIGHT", "9")
        monkeypatch.setattr(rz, "_sharedAdmission", None)
        assert getSharedAdmission().maxInFlight == 9
        monkeypatch.setattr(rz, "_sharedAdmission", None)


class TestMultiModelClientWiring:
    def _client(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient

        client = MultiModelLLMClient.__new__(MultiModelLLMClient)
        client._retry_guards_inst = {}
        return client

    def test_retry_guard_carries_shared_budget(self):
        client = self._client()
        fake = SimpleNamespace(provider=SimpleNamespace(id="p-x"))
        rc, cb = client._get_retry_guard(fake)
        assert rc.retry_budget is getSharedRetryBudget()
        assert cb.name == "llm:p-x"
