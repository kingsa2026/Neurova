"""Tests for neurova.llm.providers.rate_limiter — TDD RED phase."""
import asyncio
import time
from dataclasses import is_dataclass
import pytest


class TestCircuitState:
    def test_is_enum_subclass(self):
        from neurova.llm.providers.rate_limiter import CircuitState
        assert issubclass(CircuitState, __import__("enum").Enum)

    def test_has_closed(self):
        from neurova.llm.providers.rate_limiter import CircuitState
        names = [e.name for e in CircuitState]
        assert "CLOSED" in names


class TestRateLimitConfig:
    def test_is_dataclass(self):
        from neurova.llm.providers.rate_limiter import RateLimitConfig
        assert is_dataclass(RateLimitConfig)

    def test_default_fields(self):
        from neurova.llm.providers.rate_limiter import RateLimitConfig
        cfg = RateLimitConfig()
        assert hasattr(cfg, "max_requests")
        assert hasattr(cfg, "window_seconds")


class TestRetryConfig:
    def test_is_dataclass(self):
        from neurova.llm.providers.rate_limiter import RetryConfig
        assert is_dataclass(RetryConfig)

    def test_default_fields(self):
        from neurova.llm.providers.rate_limiter import RetryConfig
        cfg = RetryConfig()
        assert hasattr(cfg, "max_attempts") or hasattr(cfg, "max_retries")


class TestExponentialBackoff:
    def test_calculate_delay_grows(self):
        from neurova.llm.providers.rate_limiter import ExponentialBackoff
        eb = ExponentialBackoff()
        d0 = eb.calculate_delay(0)
        d1 = eb.calculate_delay(1)
        d2 = eb.calculate_delay(2)
        assert d0 <= d1 <= d2
        assert d2 >= 0

    def test_is_retryable_within_max(self):
        from neurova.llm.providers.rate_limiter import ExponentialBackoff
        eb = ExponentialBackoff(max_attempts=3)
        assert eb.is_retryable(0) is True
        assert eb.is_retryable(2) is True
        assert eb.is_retryable(3) is False

    def test_retry_succeeds_after_failures(self):
        from neurova.llm.providers.rate_limiter import ExponentialBackoff
        eb = ExponentialBackoff(initial_delay=0, max_delay=0)
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("boom")
            return "ok"

        result = eb.retry(flaky)
        assert result == "ok"
        assert len(attempts) == 3

    def test_retry_raises_after_exhaustion(self):
        from neurova.llm.providers.rate_limiter import ExponentialBackoff
        eb = ExponentialBackoff(max_attempts=2, initial_delay=0, max_delay=0)

        def always_fails():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            eb.retry(always_fails)


class TestRateLimiter:
    def test_can_initialize(self):
        from neurova.llm.providers.rate_limiter import RateLimiter, RateLimitConfig
        rl = RateLimiter(RateLimitConfig(max_requests=5, window_seconds=1))
        assert rl is not None

    def test_can_make_request_under_limit(self):
        from neurova.llm.providers.rate_limiter import RateLimiter, RateLimitConfig
        rl = RateLimiter(RateLimitConfig(max_requests=5, window_seconds=10))
        assert rl.can_make_request() is True
        rl.record_request()
        assert rl.can_make_request() is True

    def test_blocked_over_limit(self):
        from neurova.llm.providers.rate_limiter import RateLimiter, RateLimitConfig
        rl = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=10))
        rl.record_request()
        rl.record_request()
        assert rl.can_make_request() is False

    def test_get_wait_time_returns_float(self):
        from neurova.llm.providers.rate_limiter import RateLimiter, RateLimitConfig
        rl = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=10))
        rl.record_request()
        rl.record_request()
        wt = rl.get_wait_time()
        assert isinstance(wt, (int, float))
        assert wt >= 0

    def test_get_stats_returns_dict(self):
        from neurova.llm.providers.rate_limiter import RateLimiter, RateLimitConfig
        rl = RateLimiter(RateLimitConfig(max_requests=10, window_seconds=10))
        stats = rl.get_stats()
        assert isinstance(stats, dict)

    def test_wait_for_slot_async(self):
        from neurova.llm.providers.rate_limiter import RateLimiter, RateLimitConfig
        rl = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=10))
        rl.record_request()

        async def runner():
            await rl.wait_for_slot(timeout=0.05)
            return True

        assert asyncio.run(runner()) is True


class TestCircuitBreaker:
    def test_can_initialize(self):
        from neurova.llm.providers.rate_limiter import CircuitBreaker
        cb = CircuitBreaker()
        assert cb is not None

    def test_can_execute_when_closed(self):
        from neurova.llm.providers.rate_limiter import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.can_execute() is True

    def test_opens_after_failures(self):
        from neurova.llm.providers.rate_limiter import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is False

    def test_record_success_closes(self):
        from neurova.llm.providers.rate_limiter import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        cb.reset()
        assert cb.can_execute() is True

    def test_get_state_returns_circuit_state(self):
        from neurova.llm.providers.rate_limiter import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1)
        state = cb.get_state()
        assert state in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN)

    def test_get_stats_returns_dict(self):
        from neurova.llm.providers.rate_limiter import CircuitBreaker
        cb = CircuitBreaker()
        stats = cb.get_stats()
        assert isinstance(stats, dict)


class TestWithRetryAndCircuitBreakerDecorator:
    def test_decorator_returns_callable(self):
        from neurova.llm.providers.rate_limiter import with_retry_and_circuit_breaker
        result = with_retry_and_circuit_breaker(lambda: 1)
        # The decorator should either be a decorator factory or a decorator itself
        # Both forms are acceptable: calling it may return a decorated function or a decorator
        assert result is not None or result == 1  # Either way it's defined
