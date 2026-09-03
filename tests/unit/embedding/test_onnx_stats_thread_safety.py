"""
TDD RED 测试 — ONNXEmbeddingEngine 统计字段线程安全

验证 Bug:
- onnx_embedding.py:86 的 self._lock = threading.Lock() 定义后从未 with self._lock: 使用（死代码）
- _total_requests / _total_inference_ms 在 line 313-314 和 387-388 无锁更新
  （+= 是 read-modify-write，非原子操作，并发调用会丢失更新）
- stats property 多次读取统计字段，无锁保护，可能返回不一致快照

修复方案: 加锁保护统计更新 + stats 读取（不是删除 _lock）

运行方式:
    cd e:\\项目\\Neurova
    python -m unittest tests.unit.embedding.test_onnx_stats_thread_safety -v
    或直接:
    python tests/unit/embedding/test_onnx_stats_thread_safety.py

注意: 本测试不依赖真实 ONNX 模型或 numpy，通过 mock 注入模拟推理后端。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock

# ============================================================
# 环境准备: 注入 mock numpy（若未安装）
# onnx_embedding.py 顶部 import numpy as np，若无 numpy 则模块无法导入。
# 测试的是统计更新的线程安全，不需要真实 numpy 运算。
# ============================================================
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if "numpy" not in sys.modules:
    _mock_np = MagicMock()
    _mock_np.ndarray = list  # 类型占位
    _mock_np.int64 = int
    _mock_np.linalg.norm.return_value = 1.0
    sys.modules["numpy"] = _mock_np

from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine  # noqa: E402


# ============================================================
# 测试辅助
# ============================================================
# 预创建 mock 推理结果，避免每次调用都创建 MagicMock（减少噪音开销）
_MOCK_EMBEDDING = MagicMock()
_MOCK_EMBEDDING.tolist.return_value = [[0.1, 0.2, 0.3]]


def _make_engine_with_st_backend():
    """
    构造一个使用 sentence_transformers 后端的引擎（无需真实模型）。

    通过 mock _st_model.encode 让推理快速返回，
    专注于测试统计更新的线程安全，而非 ONNX 推理正确性。

    关键: mock encode 使用 CPU 密集型空转（非 time.sleep），
    因为 time.sleep 会释放 GIL 导致线程被序列化，反而阻止 += 竞态。
    CPU 空转消耗 GIL ticker，使随后的 += 更可能触发 GIL 切换。
    """
    engine = ONNXEmbeddingEngine()
    engine._initialized = True
    engine._backend_type = "sentence_transformers"
    engine._dimension = 3

    def _fake_encode(texts, **kwargs):
        # Python 层循环（非 C 层 sum()），每次迭代执行字节码，
        # 消耗 GIL ticker。使随后的 += 更可能触发 GIL 切换。
        total = 0
        for _i in range(500):
            total += _i
        return _MOCK_EMBEDDING

    engine._st_model = MagicMock()
    engine._st_model.encode = _fake_encode
    return engine


# ============================================================
# 测试用例
# ============================================================
class TestOnnxStatsThreadSafety(unittest.TestCase):
    """ONNXEmbeddingEngine 统计字段线程安全测试。"""

    def setUp(self):
        """
        缩短 GIL 切换间隔，使并发竞态更易触发。

        默认 5ms 切换间隔下，+= 的 6 个字节码太短，
        GIL 几乎不可能在 += 期间切换。缩短到 10μs 后，
        ticker 仅约 100 字节码，+= 的 6 字节码占比 6%，
        配合 mock 内的 CPU 空转消耗 ticker，竞态可稳定触发。
        """
        self._orig_switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(0.00001)  # 10μs

    def tearDown(self):
        sys.setswitchinterval(self._orig_switch_interval)

    # ----------------------------------------------------------
    # 测试 1: _lock 应为 RLock（可重入）
    # ----------------------------------------------------------
    def test_lock_is_rlock(self):
        """
        RED: _lock 应为 RLock（可重入锁）。

        理由: encode_batch 可能调用其他需要同一锁的方法，
        RLock 防御性更好，避免同线程死锁。

        验证: 同线程 acquire 后再次 acquire(blocking=False) 应成功。
        - threading.Lock: 第二次 acquire 返回 False（不可重入）
        - threading.RLock: 第二次 acquire 返回 True（可重入）
        """
        engine = ONNXEmbeddingEngine()
        self.assertTrue(
            engine._lock.acquire(blocking=False), "首次 acquire 应成功"
        )
        try:
            acquired_again = engine._lock.acquire(blocking=False)
            try:
                self.assertTrue(
                    acquired_again,
                    "_lock 应为 RLock（可重入）: 同线程再次 acquire 应成功，"
                    "当前行为表明是普通 Lock（不可重入）",
                )
            finally:
                if acquired_again:
                    engine._lock.release()
        finally:
            engine._lock.release()

    # ----------------------------------------------------------
    # 测试 2: stats 应返回一致快照
    # ----------------------------------------------------------
    def test_stats_property_returns_consistent_snapshot(self):
        """
        RED: 在并发写入时，stats 应返回一致的快照。

        当前 stats property 多次读取 _total_requests 和 _total_inference_ms
        （先读用于算 avg，再读用于返回 dict），无锁保护下可能读到
        "一个字段已更新、另一个未更新" 的中间状态，导致:
          avg_inference_ms != total_inference_ms / total_requests

        修复后: stats 在 with self._lock: 下读取所有字段。

        测试方法:
        - 1 个 writer 线程持续 encode_batch
        - 4 个 reader 线程持续读取 stats
        - 每个 reader 检查 avg ≈ total_inference_ms / total_requests
        """
        engine = _make_engine_with_st_backend()

        stop = threading.Event()
        inconsistencies = []
        _lock_inconsistencies = threading.Lock()

        def writer():
            while not stop.is_set():
                try:
                    engine.encode_batch(["a", "b"])
                except Exception:
                    pass

        def reader():
            for _ in range(500):
                stats = engine.stats
                tr = stats["total_requests"]
                tim = stats["total_inference_ms"]
                avg = stats["avg_inference_ms"]
                if tr > 0:
                    expected_avg = round(tim / tr, 2)
                    if abs(avg - expected_avg) > 0.5:
                        with _lock_inconsistencies:
                            inconsistencies.append(
                                {
                                    "total_requests": tr,
                                    "total_inference_ms": tim,
                                    "avg": avg,
                                    "expected_avg": expected_avg,
                                }
                            )

        w = threading.Thread(target=writer, daemon=True)
        w.start()

        readers = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
        for r in readers:
            r.start()
        for r in readers:
            r.join()

        stop.set()
        w.join(timeout=2.0)

        self.assertEqual(
            len(inconsistencies),
            0,
            f"stats 返回不一致快照 {len(inconsistencies)} 次: "
            f"{inconsistencies[:3]} — "
            f"total_requests/total_inference_ms/avg 三者不一致，"
            f"说明 stats 未在锁保护下读取（读到了中间状态）",
        )

    # ----------------------------------------------------------
    # 测试 3: 并发 encode_batch 统计更新不应丢失
    # ----------------------------------------------------------
    def test_concurrent_encode_batch_updates_stats_atomically(self):
        """
        RED: 并发 encode_batch 时统计更新不应丢失。

        10 线程并发调用 encode_batch，每个线程 100 次迭代，每次 2 条文本。
        预期: total_requests = 10 * 100 * 2 = 2000

        无锁时: += 是 read-modify-write（LOAD→ADD→STORE），非原子。
        GIL 可在 LOAD 和 STORE 之间切换线程，导致丢失更新。
        mock encode 内的 time.sleep(0.0005) 释放 GIL，
        使线程在 += 处重叠，放大竞态。

        修复后: with self._lock: 保护统计更新。
        """
        engine = _make_engine_with_st_backend()
        n_threads = 10
        n_iters = 100
        texts_per_call = 2
        barrier = threading.Barrier(n_threads)
        texts = ["a", "b"][:texts_per_call]

        errors = []

        def worker():
            try:
                barrier.wait()  # 同步启动，最大化并发
                for _ in range(n_iters):
                    engine.encode_batch(texts)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=n_threads) as executor:
            futures = [executor.submit(worker) for _ in range(n_threads)]
            for f in as_completed(futures):
                f.result()

        self.assertEqual(errors, [], "工作线程不应抛出异常")

        expected = n_threads * n_iters * texts_per_call
        actual = engine.stats["total_requests"]
        self.assertEqual(
            actual,
            expected,
            f"并发统计丢失: 期望 {expected}, 实际 {actual} "
            f"(丢失 {expected - actual} 次更新) — "
            f"统计字段 += 非原子，需要 with self._lock: 保护",
        )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        TestOnnxStatsThreadSafety
    )
    unittest.TextTestRunner(verbosity=2).run(suite)
