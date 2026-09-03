"""
P0-3 修复测试：MultiModelLLMClient __init__ TOCTOU（C6）

测试目标（来自 fix-all-bugs-plan-v1.md）：
- RED：10 线程并发 MultiModelLLMClient()，断言 _clients 字典只被初始化一次
  （无重复 _initialize_default_clients 调用）

设计依据：
- neurova/llm/multi_model_client.py:79-81 __init__ 的 _initialized 检查在锁外
- __new__ 用 cls._lock（threading.Lock）保护实例创建，但 __init__ 的初始化检查无锁
- 两线程同时进入 __init__：都看到 _initialized 缺失 → 都设为 True → 都执行初始化
- 修复方案：在 __init__ 内用 cls._lock（改为 RLock）保护 _initialized 检查
"""

import threading
import time
from typing import List
from unittest.mock import patch, MagicMock

import pytest

from neurova.llm.multi_model_client import MultiModelLLMClient


def _reset_singleton():
    """重置 MultiModelLLMClient 单例"""
    MultiModelLLMClient._instance = None


def _make_mock_provider_manager():
    """构造 mock provider_manager 避免真实 LLM 初始化"""
    mock_pm = MagicMock()
    mock_pm.get_default_provider.return_value = None
    mock_pm.list_providers.return_value = []
    return mock_pm


class TestMultiModelClientInitLock:
    """P0-3: MultiModelLLMClient __init__ TOCTOU 修复测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        _reset_singleton()

    def teardown_method(self):
        """每个测试后重置单例"""
        _reset_singleton()

    def test_concurrent_init_calls_initialize_once(self):
        """RED: 10 线程并发构造 MultiModelLLMClient，_initialize_default_clients 只应被调用 1 次

        修复前（_initialized 无锁）：TOCTOU 可能多次调用 _initialize_default_clients
        修复后（RLock 保护）：仅调用 1 次
        """
        call_count = 0
        call_lock = threading.Lock()
        calls: List[int] = []

        def fake_init(self):
            nonlocal call_count
            with call_lock:
                call_count += 1
                calls.append(call_count)
            self._clients = {}

        mock_pm = _make_mock_provider_manager()
        with patch.object(MultiModelLLMClient, "_initialize_default_clients", fake_init), \
             patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):

            num_threads = 10
            barrier = threading.Barrier(num_threads)

            def worker():
                barrier.wait()
                MultiModelLLMClient()

            threads = [threading.Thread(target=worker) for _ in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert len(calls) == 1, (
                f"_initialize_default_clients 被调用 "
                f"{len(calls)} 次（期望 1 次，TOCTOU 复现）"
            )

    def test_singleton_returns_same_instance(self):
        """RED: 并发构造返回同一实例"""
        def fake_init(self):
            self._clients = {}

        mock_pm = _make_mock_provider_manager()
        with patch.object(MultiModelLLMClient, "_initialize_default_clients", fake_init), \
             patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):

            num_threads = 8
            results: List[int] = [0] * num_threads
            barrier = threading.Barrier(num_threads)

            def worker(idx: int):
                barrier.wait()
                results[idx] = id(MultiModelLLMClient())

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            first_id = results[0]
            assert all(r == first_id for r in results), (
                f"并发构造返回不同实例：{results}（应全部相同）"
            )

    def test_lock_is_rlock(self):
        """RED: 修复后 _lock 应为 RLock（可重入），因 __init__ 在 __new__ 后重入

        使用 timeout 避免在 Lock（不可重入）情况下永久阻塞
        """
        def fake_init(self):
            self._clients = {}

        mock_pm = _make_mock_provider_manager()
        with patch.object(MultiModelLLMClient, "_initialize_default_clients", fake_init), \
             patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):
            c = MultiModelLLMClient()
            assert hasattr(MultiModelLLMClient, "_lock"), "MultiModelLLMClient 缺少 _lock 类属性"

            # 第一次 acquire（任何 Lock/RLock 都能成功）
            acquired1 = MultiModelLLMClient._lock.acquire(timeout=1)
            assert acquired1, "_lock 第一次 acquire 失败"
            try:
                # 第二次 acquire：RLock 成功（重入），Lock 阻塞超时失败
                acquired2 = MultiModelLLMClient._lock.acquire(timeout=2)
                if acquired2:
                    MultiModelLLMClient._lock.release()
                    # 是 RLock
                    assert acquired2, "_lock 不可重入（应为 RLock 支持 __init__ 内重入）"
                else:
                    # 是 Lock，RED 阶段应失败
                    pytest.fail(
                        "_lock 是 threading.Lock（不可重入），应为 threading.RLock "
                        "以支持 __init__ 在 __new__ 持锁后重入"
                    )
            finally:
                MultiModelLLMClient._lock.release()
