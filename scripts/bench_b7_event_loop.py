"""B-7 Phase 0 度量脚本（docs/B7调度器事件循环统一立项 v2 §8.1）。

M1: 每 job 事件循环开销微基准——per-job new_event_loop+close vs 常驻循环
    run_coroutine_threadsafe 提交，n=1000 报 P50/P95。
M2: 重试并发占池回放——10 条并发重试链（深度 3、退避 1+2+4s）在 legacy
    （重试任务绑 job 循环、drain 等整链）vs shared（重试挂常驻循环）两种
    模式下的工作线程占用与任务提交排队延迟。

只读测量，不改任何生产代码。运行：python scripts/bench_b7_event_loop.py
"""

from __future__ import annotations

import asyncio
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

N = 1000


def _noop() -> float:
    return 0.0


async def _aio_noop() -> float:
    return 0.0


async def _aio_sleep(ms: float) -> float:
    await asyncio.sleep(ms / 1000.0)
    return ms


def bench_m1() -> dict:
    """M1：每 job 固定开销（无负载协程 + 1ms 模拟 IO 负载两组）。"""
    out = {}

    def pct(vals):
        s = sorted(vals)
        return {
            "p50_ms": round(statistics.median(s) * 1000, 3),
            "p95_ms": round(s[int(len(s) * 0.95)] * 1000, 3),
            "mean_ms": round(statistics.fmean(s) * 1000, 3),
        }

    # legacy：per-job new_event_loop + run_until_complete + close
    for name, coro_fn in (("noop", _aio_noop), ("sleep1ms", lambda: _aio_sleep(1))):
        lat = []
        for _ in range(N):
            t0 = time.perf_counter()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(coro_fn())
            finally:
                loop.close()
            lat.append(time.perf_counter() - t0)
        out[f"legacy_per_job_loop/{name}"] = pct(lat)

    # shared：常驻循环 + run_coroutine_threadsafe
    shared = asyncio.new_event_loop()
    t = threading.Thread(target=shared.run_forever, daemon=True, name="bench-shared-loop")
    t.start()
    try:
        for name, coro_fn in (("noop", _aio_noop), ("sleep1ms", lambda: _aio_sleep(1))):
            lat = []
            for _ in range(N):
                t0 = time.perf_counter()
                asyncio.run_coroutine_threadsafe(coro_fn(), shared).result()
                lat.append(time.perf_counter() - t0)
            out[f"shared_loop/{name}"] = pct(lat)
    finally:
        shared.call_soon_threadsafe(shared.stop)
    return out


def bench_m2(chains: int = 10, depth: int = 3, backoff: float = 1.0) -> dict:
    """M2：并发重试链的 worker 占用与提交排队延迟（legacy vs shared）。"""

    def run_mode(mode: str) -> dict:
        pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="sched")
        shared = asyncio.new_event_loop()
        st = threading.Thread(target=shared.run_forever, daemon=True)
        st.start()
        busy_samples: list[float] = []
        submit_waits: list[float] = []
        stop = threading.Event()

        active_lock = threading.Lock()
        active = {"n": 0}

        def sampler2():
            while not stop.is_set():
                with active_lock:
                    busy_samples.append(active["n"])
                time.sleep(0.05)

        def legacy_job(idx: int):
            """legacy：job 线程上建循环，重试链绑本循环，drain 等整链。"""
            with active_lock:
                active["n"] += 1
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def chain():
                    for d in range(depth):
                        await asyncio.sleep(backoff * (2**d))  # 模拟退避等待

                try:
                    loop.run_until_complete(chain())
                finally:
                    loop.close()
            finally:
                with active_lock:
                    active["n"] -= 1

        def shared_job(idx: int):
            """shared/B：job 线程只承担执行段，重试链 spawn 到常驻循环后即返回。"""
            with active_lock:
                active["n"] += 1
            try:
                fut = asyncio.run_coroutine_threadsafe(_aio_sleep(5), shared)  # 执行段 5ms
                fut.result()
                # 重试链 spawn 到常驻循环，不等待
                for d in range(depth):
                    asyncio.run_coroutine_threadsafe(
                        _aio_sleep(backoff * (2**d) * 1000), shared
                    )
            finally:
                with active_lock:
                    active["n"] -= 1

        sampler_thread = threading.Thread(target=sampler2, daemon=True)
        sampler_thread.start()

        t0 = time.perf_counter()
        if mode == "legacy":
            futs = [pool.submit(legacy_job, i) for i in range(chains)]
        else:
            futs = [pool.submit(shared_job, i) for i in range(chains)]
        # 同时提交 3 个普通短任务，测排队延迟（饥饿信号）
        for _ in range(3):
            ts = time.perf_counter()
            pool.submit(_noop).result()
            submit_waits.append(time.perf_counter() - ts)
        for f in futs:
            f.result()
        wall = time.perf_counter() - t0
        stop.set()
        sampler_thread.join(timeout=1)
        pool.shutdown(wait=False, cancel_futures=True)
        shared.call_soon_threadsafe(shared.stop)

        return {
            "wall_s": round(wall, 2),
            "peak_busy_workers": max(busy_samples) if busy_samples else 0,
            "submit_wait_p50_ms": round(statistics.median(submit_waits) * 1000, 2),
            "submit_wait_max_ms": round(max(submit_waits) * 1000, 2),
        }

    return {"legacy": run_mode("legacy"), "shared": run_mode("shared")}


if __name__ == "__main__":
    print("=== M1: per-job loop 固定开销（n=1000）===")
    for k, v in bench_m1().items():
        print(f"  {k}: {v}")
    print("=== M2: 10 并发重试链（深度3，退避 1/2/4s）worker 占用与排队 ===")
    for k, v in bench_m2().items():
        print(f"  {k}: {v}")
