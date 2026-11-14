"""LLM 弹性包（P2-9）：进程级准入票据 + 时间窗重试预算。

对照 ZCode 的 request-admission 与 retry-budget 两件套：

- **准入票据**（AdmissionTickets）：全进程在飞 LLM 调用上限。默认
  ``NEUROVA_LLM_MAX_INFLIGHT=0``＝不限（多用户平台不因全局闸自我限流）；
  运营设上限后，抢不到票的调用在时限内排队、超时快速失败为
  「系统繁忙」（LLMServiceUnavailableError，可 fallback）；
- **重试预算**（RetryBudget）：时间窗内全进程重试次数上限（默认
  ``NEUROVA_LLM_RETRY_BUDGET_PER_MIN=200``/分钟）。仅可重试类别在
  重试时消耗预算；预算耗尽立即停止重试（走 fallback/失败）——
  上游故障时不许把重试雪崩放大成全进程风暴。

两者均为进程级单例（DCL + RLock，AGENTS.md §3），env 可调、测试可重置。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional


class AdmissionTickets:
    """进程级在飞调用票据（信号量语义 + in-flight 计数）。"""

    def __init__(self, maxInFlight: int = 0):
        self._max = max(0, int(maxInFlight))
        self._sem = threading.Semaphore(self._max) if self._max > 0 else None
        self._lock = threading.RLock()
        self._inFlight = 0

    @property
    def maxInFlight(self) -> int:
        return self._max

    @property
    def inFlight(self) -> int:
        with self._lock:
            return self._inFlight

    def tryAcquire(self, timeout: float = 0.0) -> bool:
        """取一张票；不限流时恒 True。timeout>0 时阻塞等待至多 timeout 秒。"""
        if self._sem is None:
            with self._lock:
                self._inFlight += 1
            return True
        if timeout > 0:
            acquired = self._sem.acquire(timeout=timeout)
        else:
            acquired = self._sem.acquire(blocking=False)
        if acquired:
            with self._lock:
                self._inFlight += 1
        return acquired

    def release(self) -> None:
        with self._lock:
            self._inFlight = max(0, self._inFlight - 1)
        if self._sem is not None:
            self._sem.release()

    async def acquireAsync(self, timeout: float = 30.0) -> bool:
        """异步获取：先非阻塞试取，失败按 50ms 轮询至超时（不阻塞事件循环）。"""
        import asyncio

        if self.tryAcquire():
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            if self.tryAcquire():
                return True
        return False


class RetryBudget:
    """时间窗重试预算：窗内全进程重试次数上限（固定窗，到期重置）。"""

    def __init__(self, maxRetries: int = 200, windowSeconds: float = 60.0):
        self.maxRetries = max(1, int(maxRetries))
        self.windowSeconds = max(0.001, float(windowSeconds))
        self._lock = threading.RLock()
        self._windowStart = time.monotonic()
        self._used = 0

    def tryConsume(self) -> bool:
        """消耗一次重试名额；窗内耗尽返回 False（调用方立即停止重试）。"""
        with self._lock:
            now = time.monotonic()
            if now - self._windowStart >= self.windowSeconds:
                self._windowStart = now
                self._used = 0
            if self._used >= self.maxRetries:
                return False
            self._used += 1
            return True

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.maxRetries - self._used)


_sharedRetryBudget: Optional[RetryBudget] = None
_sharedAdmission: Optional[AdmissionTickets] = None
_resilienceLock = threading.RLock()


def getSharedRetryBudget() -> RetryBudget:
    """进程级重试预算单例（DCL）。上限 env：NEUROVA_LLM_RETRY_BUDGET_PER_MIN。"""
    global _sharedRetryBudget
    if _sharedRetryBudget is None:
        with _resilienceLock:
            if _sharedRetryBudget is None:
                try:
                    perMin = int(os.environ.get("NEUROVA_LLM_RETRY_BUDGET_PER_MIN", "200"))
                except ValueError:
                    perMin = 200
                _sharedRetryBudget = RetryBudget(maxRetries=perMin, windowSeconds=60.0)
    return _sharedRetryBudget


def getSharedAdmission() -> AdmissionTickets:
    """进程级准入票据单例（DCL）。上限 env：NEUROVA_LLM_MAX_INFLIGHT（0=不限）。"""
    global _sharedAdmission
    if _sharedAdmission is None:
        with _resilienceLock:
            if _sharedAdmission is None:
                try:
                    maxInFlight = int(os.environ.get("NEUROVA_LLM_MAX_INFLIGHT", "0"))
                except ValueError:
                    maxInFlight = 0
                _sharedAdmission = AdmissionTickets(maxInFlight=maxInFlight)
    return _sharedAdmission
