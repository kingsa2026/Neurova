"""B-7 Phase 2 不变量：worker 占用是活跃 job 数的函数，而非重试链深度的函数

P2 直接证据消除（B7基线度量报告 M2 模型，scripts/bench_b7_event_loop.py）：
- legacy：重试链绑 job 循环 + drain 等整链 → 10 并发重试链把 10 worker
  全部占住整条链时长（回放实测 10/10、7 秒），期间任何新 job 排队。
- shared（方案 B）：wrapper 提交完执行段即返回，重试链挂常驻循环——
  worker 提交返回后立即空闲，后续短任务提交不被排队阻塞。

时长控制：退避 0.05/0.1/0.2s（max_attempts=4 → 链总退避 0.35s），
执行段 20ms；legacy 峰值采样窗 ≥0.35s（20ms 采样粒度足够）。
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import pytest

import neurova.agent.scheduler as sched_mod
from neurova.agent.scheduler import (
    AutomationTask,
    RetryPolicy,
    TaskRequest,
    TaskScheduler,
    TaskType,
)

CHAINS = 10
POOL_SIZE = 10
EXEC_SEGMENT_S = 0.02  # 模拟任务执行段
RETRY_BASE_S = 0.05  # 退避 0.05/0.1/0.2（exponential，max_attempts=4）
RETRY_THREAD_NAME = "neurova-scheduler-retry-loop"

# 供 FlakyExecutor 使用的 sleep（不经 monkeypatch，真实时间）
asyncio_sleep = asyncio.sleep


class FlakyExecutor:
    """固定执行段 + 始终失败（有 retry_policy 时触发满链重试）。"""

    def __init__(self):
        self.calls = 0
        self.calls_lock = threading.Lock()

    async def validate(self, task):
        return True, None

    async def execute(self, task, execution) -> Dict[str, Any]:
        with self.calls_lock:
            self.calls += 1
        await asyncio_sleep(EXEC_SEGMENT_S)
        return {"success": False, "error": "boom"}


def _make_task(task_id: str, with_retry: bool) -> AutomationTask:
    return AutomationTask(
        id=task_id,
        name=f"task-{task_id}",
        type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, agent_id="a1", input={"message": "hi"}),
        retry_policy=RetryPolicy(
            enabled=True, max_attempts=4, retry_delay_seconds=1, exponential_backoff=True
        ) if with_retry else None,
    )


class OccupancyProbe:
    """线程池活跃 worker 采样器（bench M2 的 sampler 同型）。"""

    def __init__(self, interval: float = 0.02):
        self._interval = interval
        self._active = 0
        self._lock = threading.Lock()
        self._samples: List[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self._stop.is_set():
            with self._lock:
                self._samples.append(self._active)
            time.sleep(self._interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=1)

    def busy(self, delta: int):
        with self._lock:
            self._active += delta

    def snapshot(self) -> int:
        with self._lock:
            return self._active

    @property
    def peak(self) -> int:
        return max(self._samples) if self._samples else 0


@pytest.mark.parametrize("mode", ["legacy", "shared"])
def test_worker_occupancy_retry_chain_replay(mode, monkeypatch):
    """10 并发重试链回放：legacy 峰值占用 ≥ 链数；shared 提交返回即空闲。"""
    monkeypatch.setenv("NEUROVA_SCHEDULER_EXEC_MODE", mode)
    TaskScheduler._instance = None
    scheduler = TaskScheduler()
    executor = FlakyExecutor()
    scheduler._executors[TaskType.AGENT] = executor
    for i in range(CHAINS):
        task = _make_task(f"t-occ-{i}", with_retry=True)
        # 退避 0.05s 起（0.05/0.1/0.2）：retry_delay_seconds 注解 int 但
        # 实际参与 float 运算，测试域直接赋 float 值控制时长
        task.retry_policy.retry_delay_seconds = RETRY_BASE_S
        scheduler.add_task(task)
    scheduler.add_task(_make_task("t-short", with_retry=False))  # 探针短任务

    probe = OccupancyProbe(interval=0.02)
    short_task_waits: List[float] = []
    pool = ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="b7-occ")
    try:
        with probe:
            counted_wrapper = scheduler._execute_task_wrapper

            def _job(task_id: str):
                probe.busy(+1)
                try:
                    counted_wrapper(task_id)
                finally:
                    probe.busy(-1)

            t0 = time.perf_counter()
            job_futures = [pool.submit(_job, f"t-occ-{i}") for i in range(CHAINS)]

            if mode == "shared":
                for f in job_futures:
                    f.result(timeout=5)
                wrapper_wall = time.perf_counter() - t0
                # shared：wrapper 只含执行段（链总退避 ≥0.35s），必须早返回
                assert wrapper_wall < 0.3, (
                    f"shared 模式 wrapper 必须不等重试链返回，实际 {wrapper_wall:.3f}s"
                )
                # worker 立即空闲：短稳态窗后无 wrapper 仍占 worker，而链未收口
                time.sleep(0.05)
                assert probe.snapshot() == 0, "shared 模式 job 提交返回后 worker 必须立即空闲"
                with executor.calls_lock:
                    calls_now = executor.calls
                assert calls_now < CHAINS * 4, "重试链必须仍在常驻循环上未完（未被等链占用）"

                # 后续短任务提交不被重试链排队阻塞（P2 消除的直接后果）
                for _ in range(3):
                    ts = time.perf_counter()
                    pool.submit(_job, "t-short").result(timeout=5)
                    short_task_waits.append(time.perf_counter() - ts)
                assert max(short_task_waits) < 0.5, (
                    f"短任务提交不得被重试链阻塞，实际 {short_task_waits}"
                )
            else:
                # legacy：wrapper 只有整链跑完才返回（drain 等全链）
                for f in job_futures:
                    f.result(timeout=10)
                legacy_wall = time.perf_counter() - t0
                assert legacy_wall >= RETRY_BASE_S * (2 ** 0 + 2 ** 1 + 2 ** 2) * 0.8, (
                    f"legacy wrapper 必须等整条重试链，实际 {legacy_wall:.3f}s"
                )

            peak = probe.peak
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        # 收口：shared 模式取消常驻循环上的链；legacy 此时链已随 drain 收口
        for t in list(scheduler._pending_retry_tasks):
            t.cancel()
        for f in list(getattr(scheduler, "_pending_retry_futures", ())):
            f.cancel()
        sched_mod._shutdown_retry_loop()
        TaskScheduler._instance = None

    if mode == "legacy":
        assert peak >= CHAINS, (
            f"legacy：{CHAINS} 并发重试链必须占满 {POOL_SIZE} worker 线程（P2 直接证据），"
            f"实测峰值 {peak}"
        )
    else:
        # shared 峰值 = 活跃执行段重叠数；关键差异断言在上方
        # （提交返回即空闲 + 短任务不阻塞）。此处锁存峰值不高于池容量。
        assert peak <= POOL_SIZE


def test_retry_loop_thread_count_at_most_one(monkeypatch):
    """调度域常驻重试循环线程数 ≤ 1（懒启动 + 存活判据复用，不泄漏线程）。"""
    monkeypatch.delenv("NEUROVA_SCHEDULER_EXEC_MODE", raising=False)
    TaskScheduler._instance = None
    s = TaskScheduler()
    try:
        for _ in range(5):
            loop = sched_mod._get_retry_loop()
            loop2 = sched_mod._get_retry_loop()
            assert loop is loop2, "并发懒启动必须复用同一循环"
        alive = [t for t in threading.enumerate() if t.name == RETRY_THREAD_NAME]
        assert len(alive) == 1 and alive[0].is_alive(), (
            f"常驻重试循环线程必须恰为 1，实际 {len(alive)}"
        )
    finally:
        sched_mod._shutdown_retry_loop()
        TaskScheduler._instance = None
