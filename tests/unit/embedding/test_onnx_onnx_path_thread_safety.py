"""
TDD 测试 — ONNXEmbeddingEngine ONNX 后端路径的统计字段线程安全

背景:
- 现有 test_onnx_stats_thread_safety.py 只覆盖 sentence_transformers 后端路径（line 314-316 加锁点）
- onnx_embedding.py:389-391 的 ONNX Runtime 后端路径加锁点未被并发测试覆盖
- 审计报告标记为 WARN（非阻塞）——两处加锁模式完全相同，但缺少 ONNX 路径的回归保护

修复方案: 补一个 ONNX 路径的并发测试 + 一个直接断言锁使用的契约测试

测试策略:
1. test_onnx_path_acquires_lock_for_stats_update (契约测试,可靠 RED 信号)
   - mock ONNX 后端（_ort_session.run + _tokenizer.encode）
   - 用 MagicMock 替换 _lock
   - 调用 encode_batch，断言 _lock.__enter__ 被调用
   - 不依赖 GIL 线程切换时序，CPython 3.15 也可靠
   - 如果未来误删 ONNX 路径的 with self._lock:，此测试会失败

2. test_concurrent_encode_batch_updates_stats_atomically_onnx_backend (并发回归保护)
   - 10 线程并发调用 encode_batch（ONNX 路径）
   - 验证 stats["total_requests"] == expected
   - 注意: CPython 3.15 GIL 行为变化可能让简单竞态不触发
     (参见 project_memory.md "CPython 3.15 GIL 行为变化让简单竞态测试不可靠")
   - 因此本测试主要作为"覆盖性回归保护"，并非可靠的 RED 信号
   - 真正的 RED 信号是上面的契约测试

运行方式:
    cd e:\\项目\\Neurova
    python -m unittest tests.unit.embedding.test_onnx_onnx_path_thread_safety -v
"""
from __future__ import annotations

import os
import sys
import threading
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
    _mock_np.ndarray = list
    _mock_np.int64 = int
    _mock_np.linalg.norm.return_value = 1.0
    # np.array(...) 返回 MagicMock，支持 .tolist() / .ndim / 切片
    _mock_np.array.return_value = MagicMock()
    _mock_np.zeros_like.return_value = MagicMock()
    sys.modules["numpy"] = _mock_np

from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine  # noqa: E402


# ============================================================
# 测试辅助
# ============================================================
def _make_engine_with_onnx_backend():
    """
    构造一个使用 ONNX Runtime 后端的引擎（无需真实模型）。

    通过 mock _ort_session.run + _tokenizer.encode 让推理快速返回，
    专注于测试统计更新的线程安全，而非 ONNX 推理正确性。

    关键 mock 点:
    - _tokenizer.encode(text) → 返回 list[int]（走 line 335-336 分支）
    - _ort_session.get_inputs() → 返回 []（避免 token_type_ids 分支）
    - _ort_session.run(None, ort_inputs) → 返回 [mock_embeddings]
    - mock_embeddings.ndim = 2（避免 line 378-380 的 [:, 0, :] 切片分支）
    - mock_embeddings.tolist() → [[0.1, 0.2, 0.3]]

    mock encode 用 CPU 空转而非 time.sleep:
    - time.sleep 释放 GIL，让线程被序列化，反而阻止 += 竞态
    - CPU 空转消耗 GIL ticker，使随后的 += 更可能触发 GIL 切换
    """
    engine = ONNXEmbeddingEngine()
    engine._initialized = True
    engine._backend_type = "onnx"
    engine._dimension = 3

    # mock tokenizer: encode 返回 list[int]
    # hasattr([1,2,3], "ids") 为 False → 走 line 335 isinstance(encoded, list) 分支
    # 注意: 不要把 encode 替换为普通函数（会失去 MagicMock 的 return_value 机制）
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = [1, 2, 3]
    engine._tokenizer = mock_tokenizer

    # mock ONNX session
    mock_embeddings = MagicMock()
    mock_embeddings.ndim = 2  # 避免 line 378-380 的 [:, 0, :] 切片
    mock_embeddings.tolist.return_value = [[0.1, 0.2, 0.3]]

    mock_session = MagicMock()
    mock_session.get_inputs.return_value = []  # 避免 token_type_ids 分支
    mock_session.run.return_value = [mock_embeddings]

    def _fake_run(*args, **kwargs):
        # CPU 空转消耗 GIL ticker（同 st 路径的 _fake_encode）
        total = 0
        for _i in range(500):
            total += _i
        return [mock_embeddings]

    mock_session.run = _fake_run
    engine._ort_session = mock_session

    return engine


# ============================================================
# 测试用例
# ============================================================
class TestOnnxPathThreadSafety(unittest.TestCase):
    """ONNXEmbeddingEngine ONNX 后端路径的统计字段线程安全测试。"""

    def setUp(self):
        """缩短 GIL 切换间隔，使并发竞态更易触发。"""
        self._orig_switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(0.00001)  # 10μs

    def tearDown(self):
        sys.setswitchinterval(self._orig_switch_interval)

    # ----------------------------------------------------------
    # 测试 1: ONNX 路径的统计更新应在 _lock 保护下进行（契约测试,可靠 RED 信号）
    # ----------------------------------------------------------
    def test_onnx_path_acquires_lock_for_stats_update(self):
        """
        RED→GREEN: ONNX 路径的统计更新应在 _lock 保护下进行。

        方法:
        - 用 MagicMock 替换 _lock
        - 调用 encode_batch（走 ONNX 路径）
        - 断言 _lock.__enter__ 被调用（即 with self._lock: 上下文被进入）

        可靠性:
        - 不依赖 GIL 线程切换时序，CPython 3.15 也可靠
        - 如果未来误删 ONNX 路径的 with self._lock:，此测试会失败
        - 这是真正的 RED 信号，区别于并发竞态测试
        """
        engine = _make_engine_with_onnx_backend()

        # 用 MagicMock 替换 _lock（保留上下文管理器接口）
        mock_lock = MagicMock()
        engine._lock = mock_lock

        # 调用 encode_batch（走 ONNX 路径）
        result = engine.encode_batch(["test"])

        # 断言 lock 被 acquire（with 语句进入 __enter__）
        mock_lock.__enter__.assert_called(), (
            "ONNX 路径未使用 _lock 保护统计更新 — "
            "with self._lock: 应在 line 389-391 的统计更新处出现"
        )

        # 验证返回 EmbeddingResult（不验证 vectors 内容，因为 mock numpy
        # 的 .tolist() 返回 MagicMock，验证 vectors 正确性不是本测试目的）
        self.assertIsNotNone(result)

    # ----------------------------------------------------------
    # 测试 2: 并发 encode_batch 统计更新不应丢失（ONNX 路径回归保护）
    # ----------------------------------------------------------
    def test_concurrent_encode_batch_updates_stats_atomically_onnx_backend(self):
        """
        并发回归保护: ONNX 路径的统计更新不应丢失。

        10 线程并发调用 encode_batch（ONNX 路径），每个线程 100 次迭代。
        预期: total_requests = 10 * 100 * 1 = 1000

        注意:
        - CPython 3.15 GIL 行为变化可能让简单 += 竞态不触发（参见 project_memory.md）
        - 此测试主要作为"覆盖性回归保护"，并非可靠的 RED 信号
        - 真正的 RED 信号是 test_onnx_path_acquires_lock_for_stats_update
        - 若 _lock 加锁点被误删，此测试可能仍通过（因 GIL 行为）
        - 但若此测试失败，必然表示 _lock 加锁点已失效
        """
        engine = _make_engine_with_onnx_backend()
        n_threads = 10
        n_iters = 100
        texts_per_call = 1
        barrier = threading.Barrier(n_threads)
        texts = ["a"] * texts_per_call

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
            f"ONNX 路径并发统计丢失: 期望 {expected}, 实际 {actual} "
            f"(丢失 {expected - actual} 次更新) — "
            f"ONNX 路径统计字段 += 非原子，需要 with self._lock: 保护",
        )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        TestOnnxPathThreadSafety
    )
    unittest.TextTestRunner(verbosity=2).run(suite)
