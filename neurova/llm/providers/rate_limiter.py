"""
重试和速率限制
"""

import asyncio
import enum
import functools
from neurova.core.logger import get_logger
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RateLimitConfig:
    max_requests: int = 60
    window_seconds: float = 60.0
    block_when_exceeded: bool = True
    burst_allowance: int = 0


@dataclass
class RetryConfig:
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.1
    retryable_exceptions: tuple = (Exception,)


class ExponentialBackoff:
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: float = 0.1,
        retryable_exceptions: tuple = (Exception,),
    ) -> None:
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        self._lock = threading.RLock()
        self._attempt = 0

    def calculate_delay(self, attempt: int) -> float:
        with self._lock:
            if attempt < 0:
                attempt = 0
            base = self.initial_delay * (self.multiplier**attempt)
            delay = min(base, self.max_delay)
            if self.jitter > 0:
                spread = delay * self.jitter
                delay = delay + random.uniform(-spread, spread)
            return max(0.0, delay)

    def is_retryable(self, attempt: int) -> bool:
        with self._lock:
            return attempt < self.max_attempts

    def should_retry_exception(self, exc: BaseException) -> bool:
        with self._lock:
            return isinstance(exc, self.retryable_exceptions)

    def retry(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_attempts):
            try:
                return func(*args, **kwargs)
            except BaseException as exc:
                last_exc = exc
                if not self.should_retry_exception(exc):
                    raise
                if not self.is_retryable(attempt):
                    raise
                delay = self.calculate_delay(attempt)
                if delay > 0:
                    time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        return None

    async def aretry(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_attempts):
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except BaseException as exc:
                last_exc = exc
                if not self.should_retry_exception(exc):
                    raise
                if not self.is_retryable(attempt):
                    raise
                delay = self.calculate_delay(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
        if last_exc is not None:
            raise last_exc
        return None


class RateLimiter:
    def __init__(self, config: Optional[RateLimitConfig] = None) -> None:
        self.config = config or RateLimitConfig()
        self._lock = threading.RLock()
        self._requests: List[float] = []
        self._total_allowed: int = 0
        self._total_blocked: int = 0
        self._total_wait_seconds: float = 0.0

    def _now(self) -> float:
        return time.monotonic()

    def _purge(self, now: float) -> None:
        window = self.config.window_seconds
        cutoff = now - window
        kept: List[float] = []
        for ts in self._requests:
            if ts >= cutoff:
                kept.append(ts)
        self._requests = kept

    def can_make_request(self) -> bool:
        with self._lock:
            now = self._now()
            self._purge(now)
            cap = self.config.max_requests + self.config.burst_allowance
            return len(self._requests) < cap

    def record_request(self) -> None:
        with self._lock:
            now = self._now()
            self._purge(now)
            cap = self.config.max_requests + self.config.burst_allowance
            if len(self._requests) < cap:
                self._requests.append(now)
                self._total_allowed += 1
            else:
                self._total_blocked += 1

    def get_wait_time(self) -> float:
        with self._lock:
            now = self._now()
            self._purge(now)
            cap = self.config.max_requests + self.config.burst_allowance
            if len(self._requests) < cap:
                return 0.0
            if not self._requests:
                return 0.0
            window = self.config.window_seconds
            oldest = self._requests[0]
            return max(0.0, (oldest + window) - now)

    def block_over_limit(self) -> bool:
        with self._lock:
            return not self.can_make_request()

    async def wait_for_slot(self, timeout: Optional[float] = None) -> bool:
        deadline = None
        if timeout is not None:
            deadline = self._now() + timeout
        while True:
            wait = self.get_wait_time()
            if wait <= 0:
                if self.can_make_request():
                    self.record_request()
                    return True
            if deadline is not None:
                remaining = deadline - self._now()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining) if wait > 0 else remaining
            if wait <= 0:
                await asyncio.sleep(0.001)
                continue
            await asyncio.sleep(wait)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            now = self._now()
            self._purge(now)
            return {
                "max_requests": self.config.max_requests,
                "window_seconds": self.config.window_seconds,
                "current_count": len(self._requests),
                "available": max(0, self.config.max_requests - len(self._requests)),
                "total_allowed": self._total_allowed,
                "total_blocked": self._total_blocked,
                "total_wait_seconds": round(self._total_wait_seconds, 6),
            }


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
        expected_exceptions: tuple = (Exception,),
        name: str = "default",
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.expected_exceptions = expected_exceptions
        self.name = name
        self._lock = threading.RLock()
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._opened_at: Optional[float] = None
        self._total_success: int = 0
        self._total_failure: int = 0
        self._total_rejected: int = 0
        self._total_half_open: int = 0

    def _now(self) -> float:
        return time.monotonic()

    def _transition(self, new_state: CircuitState) -> None:
        if new_state == CircuitState.OPEN and self._state != CircuitState.OPEN:
            self._opened_at = self._now()
        if new_state == CircuitState.HALF_OPEN and self._state != CircuitState.HALF_OPEN:
            self._total_half_open += 1
            self._success_count = 0
        if new_state == CircuitState.CLOSED:
            self._opened_at = None
        self._state = new_state

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if self._opened_at is None:
                    self._transition(CircuitState.HALF_OPEN)
                    return True
                elapsed = self._now() - self._opened_at
                if elapsed >= self.recovery_timeout:
                    self._transition(CircuitState.HALF_OPEN)
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._total_success += 1
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._failure_count = 0
                    self._transition(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._total_failure += 1
            if self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
                return
            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._transition(CircuitState.OPEN)

    def opens_after_failures(self) -> int:
        with self._lock:
            return self.failure_threshold

    def reset(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None
            self._transition(CircuitState.CLOSED)

    def get_state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN and self._opened_at is not None:
                if (self._now() - self._opened_at) >= self.recovery_timeout:
                    self._transition(CircuitState.HALF_OPEN)
            return self._state

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "total_success": self._total_success,
                "total_failure": self._total_failure,
                "total_rejected": self._total_rejected,
                "total_half_open": self._total_half_open,
                "opened_at": self._opened_at,
            }


class CircuitBreakerOpen(Exception):
    pass


def with_retry_and_circuit_breaker(
    func: Optional[Callable[..., Any]] = None,
    *,
    retry_config: Optional[RetryConfig] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    max_attempts: Optional[int] = None,
    initial_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[float] = None,
) -> Any:
    if (
        func is not None
        and callable(func)
        and not any(
            v is not None
            for v in (
                retry_config,
                circuit_breaker,
                max_attempts,
                initial_delay,
                max_delay,
                failure_threshold,
                recovery_timeout,
            )
        )
    ):

        @functools.wraps(func)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return _wrapped

    rc = retry_config or RetryConfig(
        max_attempts=max_attempts if max_attempts is not None else 3,
        initial_delay=initial_delay if initial_delay is not None else 1.0,
        max_delay=max_delay if max_delay is not None else 60.0,
    )
    cb = circuit_breaker or CircuitBreaker(
        failure_threshold=failure_threshold if failure_threshold is not None else 5,
        recovery_timeout=recovery_timeout if recovery_timeout is not None else 60.0,
    )
    backoff = ExponentialBackoff(
        max_attempts=rc.max_attempts,
        initial_delay=rc.initial_delay,
        max_delay=rc.max_delay,
        multiplier=rc.multiplier,
        jitter=rc.jitter,
        retryable_exceptions=rc.retryable_exceptions,
    )

    def _decorator(target: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(target):

            @functools.wraps(target)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not cb.can_execute():
                    cb._total_rejected += 1
                    raise CircuitBreakerOpen(f"circuit '{cb.name}' is open")
                try:
                    result = await backoff.aretry(target, *args, **kwargs)
                except BaseException as exc:
                    if isinstance(exc, rc.retryable_exceptions):
                        cb.record_failure()
                    raise
                else:
                    cb.record_success()
                    return result

            return _async_wrapper

        @functools.wraps(target)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not cb.can_execute():
                cb._total_rejected += 1
                raise CircuitBreakerOpen(f"circuit '{cb.name}' is open")
            try:
                result = backoff.retry(target, *args, **kwargs)
            except BaseException as exc:
                if isinstance(exc, rc.retryable_exceptions):
                    cb.record_failure()
                raise
            else:
                cb.record_success()
                return result

        return _sync_wrapper

    if func is not None and callable(func):
        return _decorator(func)
    return _decorator
