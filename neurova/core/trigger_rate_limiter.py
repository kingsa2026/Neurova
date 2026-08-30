"""
触发器限流器（P1 Step 4）

Token bucket 算法：每 key 独立桶，容量 = limit_per_minute，
按流逝时间匀速回填（速率 = limit / 60 token 每秒）。
纯内存实现 O(1)，clock 可注入便于测试。
"""

import threading
import time
from typing import Callable, Dict, Optional

# 惰性清理阈值：桶数量超过此值时，清理长期未用的桶
_MAX_BUCKETS = 4096
_IDLE_SECONDS = 3600.0


class TriggerRateLimiter:
    """按 key 限流的 token bucket（线程安全）。"""

    def __init__(
        self,
        limit_per_minute: Optional[int],
        clock: Optional[Callable[[], float]] = None,
    ):
        # None / 0 / 负数 → 不限流
        self._unlimited = not limit_per_minute or limit_per_minute <= 0
        self._limit = int(limit_per_minute) if limit_per_minute and limit_per_minute > 0 else 0
        self._rate_per_second = (self._limit / 60.0) if not self._unlimited else 0.0
        self._clock: Callable[[], float] = clock or time.monotonic
        self._buckets: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> bool:
        """尝试取一个 token；允许返回 True，超额返回 False。"""
        if self._unlimited:
            return True
        with self._lock:
            now = self._clock()
            bucket = self._buckets.get(key)
            if bucket is None:
                self._maybe_cleanup(now)
                # 新桶满容量；随后走统一扣减
                bucket = {"tokens": float(self._limit), "ts": now}
                self._buckets[key] = bucket

            # 按流逝时间回填（不超过容量）
            elapsed = max(0.0, now - bucket["ts"])
            bucket["tokens"] = min(
                float(self._limit), bucket["tokens"] + elapsed * self._rate_per_second
            )
            bucket["ts"] = now

            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return True
            return False

    def remaining(self, key: str) -> int:
        """该 key 当前可立即取用的 token 数（不消耗）。"""
        if self._unlimited:
            return -1
        with self._lock:
            now = self._clock()
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._limit
            elapsed = max(0.0, now - bucket["ts"])
            tokens = min(
                float(self._limit), bucket["tokens"] + elapsed * self._rate_per_second
            )
            return int(tokens)

    def _maybe_cleanup(self, now: float) -> None:
        """桶过多时清理长期空闲的（在持锁区间内调用）。

        P0-7/N5 修复：原实现清理体缩进在 return 之后不可达（桶满后
        永不清理，慢性内存泄漏）。
        """
        if len(self._buckets) < _MAX_BUCKETS:
            return
        stale = [
            k
            for k, b in self._buckets.items()
            if now - b.get("ts", 0.0) > _IDLE_SECONDS
        ]
        for k in stale:
            del self._buckets[k]
