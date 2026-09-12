"""B-10 回归测试：召回协程执行收敛到模块级常驻事件循环线程。

根因：`_run_coroutine_in_thread` 每次调用派生新线程 + asyncio.run() 新事件
循环（每轮 chat 召回一次）；M-13 join 超时后线程弃置且协程不可取消 ——
挂起场景线程渐进堆积。

修复后契约：
- 模块级常驻单事件循环线程（daemon、懒启动、永久运行）；
- 正常路径返回结果；协程异常向调用方 re-raise；
- 超时返回 None（M-13 语义不变），且**线程数不增长**；
- 多次调用共用同一 loop，不再每调用新建线程；
- shutdown_recall_loop() 供测试/停机收口。
"""

import asyncio
import threading

import pytest

from neurova.cognitive_layers.memory_layer import neurova_recall as nr
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    NeurovaRecallEngine,
)


@pytest.fixture(autouse=True)
def _isolated_recall_loop():
    """每个用例收口共享 loop，防挂起协程跨用例泄漏。"""
    yield
    nr.shutdown_recall_loop()


def _recall_loop_thread_count() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "neurova-recall-loop")


class TestB10SharedRecallLoop:
    def test_normal_result_returned(self):
        async def coro():
            await asyncio.sleep(0.01)
            return {"hits": 3}

        assert NeurovaRecallEngine._run_coroutine_in_thread(coro()) == {"hits": 3}

    def test_exception_reraised_to_caller(self):
        async def boom():
            raise ValueError("召回通道炸了")

        with pytest.raises(ValueError, match="召回通道炸了"):
            NeurovaRecallEngine._run_coroutine_in_thread(boom())

    def test_timeout_returns_none_and_no_thread_growth(self):
        # 预热：先跑一次快协程，确保常驻 loop 线程已建立
        async def fast():
            return "ok"

        assert NeurovaRecallEngine._run_coroutine_in_thread(fast(), join_timeout=5.0) == "ok"
        baseline_threads = threading.active_count()

        async def hang():
            await asyncio.sleep(3600)

        result = NeurovaRecallEngine._run_coroutine_in_thread(hang(), join_timeout=0.2)
        assert result is None, "超时必须返回 None（调用方以空结果继续）"
        assert threading.active_count() == baseline_threads, (
            "超时后线程数不得增长（旧实现弃置线程 → 渐进堆积）"
        )

    def test_multiple_calls_share_one_loop_no_per_call_thread(self):
        async def fast(i):
            await asyncio.sleep(0.001)
            return i

        first_loop = nr._get_recall_loop()
        for i in range(8):
            assert NeurovaRecallEngine._run_coroutine_in_thread(
                fast(i), join_timeout=5.0
            ) == i

        assert nr._get_recall_loop() is first_loop, "多次调用必须共用同一事件循环"
        assert _recall_loop_thread_count() == 1, (
            "共享召回 loop 线程必须只有 1 条（旧实现每调用新建线程）"
        )

    def test_timeout_cancels_underlying_coroutine_finally_runs(self):
        """超时必须真取消底层 task：finally 被执行证明取消传播到位。

        旧实现（每次新线程+asyncio.run / M-13 弃置）协程不可取消；共享 loop
        若只弃等不取消，挂起协程会在常驻 loop 上永久残留（协程级泄漏）。
        """
        finally_ran = threading.Event()

        async def hang_with_finally():
            try:
                await asyncio.sleep(3600)
            finally:
                finally_ran.set()

        result = NeurovaRecallEngine._run_coroutine_in_thread(
            hang_with_finally(), join_timeout=0.2
        )
        assert result is None, "超时返回 None（M-13 语义）"
        assert finally_ran.wait(timeout=5.0), (
            "超时后底层协程必须被真取消（finally 未执行 = 只弃等未取消，协程残留）"
        )

    def test_shutdown_recall_loop_stops_thread(self):
        async def fast():
            return 1

        assert NeurovaRecallEngine._run_coroutine_in_thread(fast(), join_timeout=5.0) == 1
        assert _recall_loop_thread_count() >= 1
        nr.shutdown_recall_loop()
        assert _recall_loop_thread_count() == 0, "收口后常驻 loop 线程应退出"
