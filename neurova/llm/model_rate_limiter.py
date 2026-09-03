# -*- coding: utf-8 -*-
"""
每模型限流器（P2-a，对标 QP beta.5 per-model 限流语义）

"dream/cron 的 429 不拖垮用户聊天"——限流状态按模型隔离：
- QPM 滑动窗口（0 = 不限）
- 并发上限（信号量语义：acquire/release）
- 429 全局暂停带抖动（该模型暂停期间快速失败），report_success 清除陈旧暂停
- 共享单例 _shared_limiter：multi_model_client.chat 路径接线用
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from typing import Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(Exception):
    """模型限流：暂停中 / 并发满 / QPM 窗口满"""


class ModelRateLimiter:
    """每模型独立限流器（线程安全）。"""

    # 429 指数退避封顶（30min）：连续限流时暂停时长 30s→60s→120s→…→封顶
    BACKOFF_CAP_SECONDS = 1800.0

    def __init__(
        self,
        qpm: int = 0,
        max_concurrent: int = 8,
        pause_jitter: float = 0.5,
        window_seconds: float = 60.0,
    ):
        self.qpm = qpm
        self.max_concurrent = max_concurrent
        self.pause_jitter = pause_jitter
        self.window_seconds = window_seconds

        self._lock = threading.Lock()
        self._windows: Dict[str, deque] = {}       # model -> 最近调用时间戳
        self._concurrent: Dict[str, int] = {}      # model -> 当前并发数
        self._pause_until: Dict[str, float] = {}   # model -> 暂停截止（monotonic）
        self._consecutive_429: Dict[str, int] = {}  # model -> 连续 429 计数（退避指数，成功复位）

    # 时钟（测试注入）
    def _now(self) -> float:
        return time.monotonic()

    # ── 对外 API ──

    def acquire(self, model: str, blocking: bool = True, timeout: float = 30.0) -> None:
        """获取调用许可；blocking=False 时不可立即满足即抛 RateLimitExceeded。"""
        deadline = self._now() + timeout if blocking else self._now()
        while True:
            with self._lock:
                self._cleanup_window(model)
                # 1) 429 暂停检查
                pause_until = self._pause_until.get(model)
                if pause_until is not None:
                    if self._now() < pause_until:
                        remaining = pause_until - self._now()
                        if not blocking:
                            raise RateLimitExceeded(
                                f"模型 {model} 因 429 暂停中（剩余 {remaining:.1f}s）"
                            )
                    else:
                        self._pause_until.pop(model, None)  # 暂停过期
                # 2) 并发上限
                cur = self._concurrent.get(model, 0)
                if self.max_concurrent and cur >= self.max_concurrent:
                    if not blocking:
                        raise RateLimitExceeded(f"模型 {model} 并发已达上限 {self.max_concurrent}")
                # 3) QPM 窗口
                if self.qpm:
                    window = self._windows.setdefault(model, deque())
                    if len(window) >= self.qpm:
                        if not blocking:
                            raise RateLimitExceeded(f"模型 {model} QPM 窗口已满（{self.qpm}/min）")

                # 全部通过 → 占位
                if self._pause_until.get(model) is None and (
                    not self.max_concurrent or cur < self.max_concurrent
                ) and (not self.qpm or len(self._windows.get(model, deque())) < self.qpm):
                    self._concurrent[model] = cur + 1
                    if self.qpm:
                        self._windows.setdefault(model, deque()).append(self._now())
                    return

            # 阻塞模式：短暂让出后重试；超时退出
            if not blocking or self._now() >= deadline:
                raise RateLimitExceeded(f"模型 {model} 限流等待超时")
            time.sleep(0.05)

    def release(self, model: str) -> None:
        with self._lock:
            cur = self._concurrent.get(model, 0)
            self._concurrent[model] = max(0, cur - 1)

    def current_concurrent(self, model: str) -> int:
        with self._lock:
            return self._concurrent.get(model, 0)

    def report_429(self, model: str, pause_seconds: float = 30.0) -> None:
        """上游 429 反馈 → 该模型全局暂停（±jitter 抖动）。

        指数退避：连续 429 时暂停时长按 2^n 增长（30s→60s→120s→240s→…），
        封顶 ``BACKOFF_CAP_SECONDS``，成功调用即复位 —— 避免限流期间以固定
        间隔反复撞上游。
        """
        jitter = 1.0 + random.uniform(-self.pause_jitter, self.pause_jitter)
        with self._lock:
            consecutive = self._consecutive_429.get(model, 0) + 1
            self._consecutive_429[model] = consecutive
            base = min(pause_seconds * (2 ** (consecutive - 1)), self.BACKOFF_CAP_SECONDS)
            effective = max(1.0, base * jitter)
            self._pause_until[model] = self._now() + effective
        logger.warning(
            "模型 %s 收到 429（连续第 %s 次），暂停 %.1fs（抖动后）", model, consecutive, effective
        )

    def report_success(self, model: str) -> None:
        """成功调用清除陈旧暂停并复位退避计数（限流恢复信号）。"""
        with self._lock:
            self._pause_until.pop(model, None)
            self._consecutive_429.pop(model, None)

    def pause_remaining(self, model: str) -> float:
        with self._lock:
            until = self._pause_until.get(model)
            if until is None:
                return 0.0
            return max(0.0, until - self._now())

    # ── 内部 ──

    def _cleanup_window(self, model: str) -> None:
        window = self._windows.get(model)
        if not window:
            return
        cutoff = self._now() - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()


_shared_limiter: Optional[ModelRateLimiter] = None
_shared_lock = threading.Lock()


def get_shared_limiter() -> ModelRateLimiter:
    """共享限流器单例（multi_model_client.chat 路径用）。"""
    global _shared_limiter
    with _shared_lock:
        if _shared_limiter is None:
            _shared_limiter = ModelRateLimiter()
        return _shared_limiter


def reset_shared_limiter() -> None:
    global _shared_limiter
    with _shared_lock:
        _shared_limiter = None
