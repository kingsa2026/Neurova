# -*- coding: utf-8 -*-
"""CORE-04：健康检查的 timeout 预算必须真的生效，且不得阻塞事件循环。

根因两处：
1. `run_check()` 用 `with ThreadPoolExecutor(...)`：`future.result(timeout)` 超时后
   退出上下文仍 `shutdown(wait=True)`，把「按预算返回」重新拖回无限等待——实测配置
   0.01s、实际耗时 0.25s 并返回 unhealthy。
2. 端点 `async def` 里同步调用 `run_all_checks()`：同步 I/O 占住事件循环。
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from neurova.core.health_checker import HealthChecker, HealthStatus


def testTimeoutBudgetIsNotNegatedByExecutorShutdown():
    """卡住的检查按 timeout 返回，不被 executor 退出等待抵消。"""
    checker = HealthChecker()
    release = threading.Event()

    def hang() -> tuple[bool, str]:
        release.wait(10.0)
        return True, "late"

    try:
        checker.register("hang", hang, timeout=0.05)
        start = time.monotonic()
        result = checker.run_check("hang")
        elapsed = time.monotonic() - start
    finally:
        release.set()

    assert result is not None
    assert result.status == HealthStatus.UNHEALTHY
    assert elapsed < 1.0, f"超时预算被抵消：实际 {elapsed:.2f}s"


@pytest.mark.asyncio
async def testHealthEndpointDoesNotBlockEventLoop(monkeypatch):
    """async 端点执行慢检查期间，事件循环仍能调度其他任务。"""
    from neurova.api.endpoints import health as health_mod

    checker = HealthChecker()
    checker.register("slow", lambda: (time.sleep(0.3), (True, "OK"))[1], timeout=5.0)
    monkeypatch.setattr(health_mod, "_get_health_checker", lambda: checker)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    task = asyncio.create_task(heartbeat())
    try:
        await health_mod.get_health_status()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert ticks >= 10, f"事件循环被健康检查占住：0.3s 内只调度了 {ticks} 次"