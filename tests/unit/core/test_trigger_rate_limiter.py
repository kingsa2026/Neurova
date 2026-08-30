"""
NeurFlow P1 Step 4 — 触发器限流器测试（token bucket）

契约（neurova/core/trigger_rate_limiter.py）：
- TriggerRateLimiter(limit_per_minute) 单实例可服务多 key
- acquire(key) → bool：允许 True / 超额 False
- 每 key 独立桶（不同 webhook_id 互不影响）
- 桶容量 = limit_per_minute，按流逝时间匀速回填
- limit=None → 永远放行（不限流）
- 非法 limit（<=0）→ 视为不限流

TDD：先红后绿。纯逻辑测试，用 monkeypatch 时间避免真实 sleep。
"""
import pytest

from neurova.core.trigger_rate_limiter import TriggerRateLimiter


class TestAcquireBasics:
    def test_first_request_allowed(self):
        rl = TriggerRateLimiter(limit_per_minute=5)
        assert rl.acquire("wh_1") is True

    def test_blocks_after_limit_exhausted(self):
        rl = TriggerRateLimiter(limit_per_minute=3)
        assert rl.acquire("wh_1") is True
        assert rl.acquire("wh_1") is True
        assert rl.acquire("wh_1") is True
        assert rl.acquire("wh_1") is False  # 第 4 次被拒

    def test_keys_are_isolated(self):
        rl = TriggerRateLimiter(limit_per_minute=1)
        assert rl.acquire("wh_a") is True
        assert rl.acquire("wh_a") is False
        assert rl.acquire("wh_b") is True  # 独立桶

    def test_unlimited_when_none(self):
        rl = TriggerRateLimiter(limit_per_minute=None)
        for _ in range(100):
            assert rl.acquire("wh_1") is True

    def test_invalid_limit_treated_as_unlimited(self):
        rl = TriggerRateLimiter(limit_per_minute=0)
        assert rl.acquire("wh_1") is True
        rl2 = TriggerRateLimiter(limit_per_minute=-5)
        assert rl2.acquire("wh_1") is True


class TestTokenRefill:
    """时间驱动的回填：用 injectable clock 测试，不真实 sleep"""

    def test_refill_after_time_passes(self):
        now = [1000.0]

        def clock():
            return now[0]

        rl = TriggerRateLimiter(limit_per_minute=1, clock=clock)  # 1 token/min
        assert rl.acquire("wh_1") is True
        # 桶空：立刻再取被拒
        assert rl.acquire("wh_1") is False
        # 前进 60 秒：回填满 1 个 token
        now[0] += 60.0
        assert rl.acquire("wh_1") is True
        assert rl.acquire("wh_1") is False

    def test_full_refill_after_window(self):
        now = [2000.0]

        def clock():
            return now[0]

        rl = TriggerRateLimiter(limit_per_minute=2, clock=clock)
        rl.acquire("wh_1")
        rl.acquire("wh_1")
        assert rl.acquire("wh_1") is False
        now[0] += 60.0  # 一个完整窗口
        assert rl.acquire("wh_1") is True
        assert rl.acquire("wh_1") is True
        assert rl.acquire("wh_1") is False

    def test_burst_capped_at_capacity(self):
        now = [3000.0]

        def clock():
            return now[0]

        rl = TriggerRateLimiter(limit_per_minute=10, clock=clock)
        # 即使等很久，一次最多取到容量个 token
        now[0] += 600.0
        taken = sum(1 for _ in range(20) if rl.acquire("wh_1"))
        assert taken == 10


class TestRateLimiterDefaults:
    def test_default_clock_is_time_monotonic(self):
        import time

        rl = TriggerRateLimiter(limit_per_minute=5)
        # 默认 clock 存在且可调用
        assert callable(rl._clock)
        v1 = rl._clock()
        assert isinstance(v1, float)
        # monotonic 语义：两次调用单调不减
        v2 = rl._clock()
        assert v2 >= v1

    def test_remaining_returns_token_count(self):
        rl = TriggerRateLimiter(limit_per_minute=4)
        assert rl.remaining("fresh_key") == 4
        rl.acquire("fresh_key")
        assert rl.remaining("fresh_key") == 3
        assert rl.remaining("untouched_key") == 4
