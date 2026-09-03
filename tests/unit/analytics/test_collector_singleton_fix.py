"""
P0-2 修复测试：get_collector 单例并发安全（C2）

测试目标（来自 fix-all-bugs-plan-v1.md）：
- RED：10 线程并发调用 get_collector()，断言全部返回同一实例且 id() 相同
- WHITE-BOX: 验证模块持有 _collector_lock（threading.Lock 类型）

设计依据：
- neurova/analytics/collector.py:803-812 用 hasattr 检查无锁，TOCTOU
- 修复模板：neurova/cognitive/orchestrator.py:358-369（_singleton + _singleton_lock + with）
"""

import threading
import time
from typing import Any, List

import pytest

from neurova.analytics import collector as collector_module
from neurova.analytics.collector import MetricsCollector, get_collector, reset_collector


class TestCollectorSingletonConcurrencyFix:
    """P0-2: get_collector 单例并发安全修复测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        reset_collector()

    def teardown_method(self):
        """每个测试后重置单例"""
        reset_collector()

    def test_concurrent_get_collector_returns_same_instance(self):
        """RED: 10 线程并发 get_collector() 应全部返回同一实例

        修复前（hasattr 无锁）：TOCTOU 可能创建多个实例
        修复后（_collector_lock）：双重检查锁保证唯一性
        """
        num_threads = 10
        results: List[Any] = [None] * num_threads
        barrier = threading.Barrier(num_threads)

        def worker(idx: int):
            barrier.wait()  # 同步启动，最大化竞争窗口
            results[idx] = get_collector()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有线程应返回同一实例
        first_id = id(results[0])
        for i, r in enumerate(results):
            assert id(r) == first_id, (
                f"线程 {i} 返回不同实例：id={id(r)} != first={first_id}（TOCTOU 复现）"
            )
        assert all(r is results[0] for r in results), "并发 get_collector 返回不同实例"

    def test_reset_collector_creates_new_instance_after_reset(self):
        """RED: reset 后再次 get_collector 应返回新实例"""
        c1 = get_collector()
        reset_collector()
        c2 = get_collector()
        assert c1 is not c2, "reset_collector 未生效"
        assert isinstance(c1, MetricsCollector)
        assert isinstance(c2, MetricsCollector)

    def test_concurrent_get_and_reset_no_exception(self):
        """RED: 并发 get_collector + reset_collector 不应数据损坏"""
        errors = []

        def getter():
            try:
                for _ in range(50):
                    get_collector()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def resetter():
            try:
                for _ in range(20):
                    reset_collector()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=getter)
        t2 = threading.Thread(target=resetter)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"get+reset 并发抛异常: {errors}"


class TestCollectorLockExists:
    """白盒验证修复存在"""

    def test_module_has_lock_attribute(self):
        """RED: 修复后 collector 模块应持有 _collector_lock 属性"""
        assert hasattr(collector_module, "_collector_lock"), (
            "collector 模块未持有 _collector_lock 属性（单例并发保护缺失）"
        )

    def test_module_has_singleton_attribute(self):
        """RED: 修复后 collector 模块应持有 _collector_singleton 属性"""
        # 重置确保干净状态
        reset_collector()
        # 触发一次创建
        get_collector()
        # 验证单例字段存在（不是函数属性 hasattr 写法）
        assert hasattr(collector_module, "_collector_singleton"), (
            "collector 模块未持有 _collector_singleton 属性（仍用旧的函数属性写法）"
        )
        assert collector_module._collector_singleton is not None
