# -*- coding: utf-8 -*-
"""Issue #65：ExecutionEngine 单例 reset 契约（跨测试隔离）。

基线问题（实测）：``reset_execution_engine()`` 只把模块级 ``_execution_engine``
置 None，**没有清类级 ``ExecutionEngine._instance``**。于是：

    reset 后 module global: None
    reset 后 class _instance: <ExecutionEngine object ...>   # 未清
    e2 is e1: True
    marker survived reset: leak        # _executions 里的状态还在
    _initialized: True

`_executions` 只增不减、组件不重装配，任何依赖它做隔离的测试都拿到脏状态。
且该函数全仓**零调用方**——"重置"契约
从未被真实调用点验证。

本套件钉：两层全清（模块缓存 / 类级 _instance）、重建后组件可用、
并发 reset 与 get 不产生"半初始化"实例。

**见证物改判（执行记录面退役那一笔）**：原套件用 `_executions` 当"状态不外泄"与
"初始化完成"两条的见证物。那一面（含写它的三条死路）已整体退役，再断 `_executions == {}`
等于断一件拿不到也永远不会变的事——恒真空守卫。所以两条各换到**存活的组件位**
`_execution_monitor` 上；"旧实例不得被就地失效"那一格保留，只剥掉 `_executions` 那半句。
"""
import threading

import pytest


@pytest.fixture()
def engine_module():
    from neurova.shared_core import execution_engine as ee

    ee.reset_execution_engine()
    yield ee
    ee.reset_execution_engine()


class TestResetClearsClassSingleton:
    def test_class_instance_cleared(self, engine_module):
        ee = engine_module
        ee.get_execution_engine()
        assert ee.ExecutionEngine._instance is not None
        ee.reset_execution_engine()
        assert ee._execution_engine is None, "模块级缓存未清"
        assert ee.ExecutionEngine._instance is None, "类级 _instance 未清（本次回归的根因）"

    def test_identity_changes_after_reset(self, engine_module):
        ee = engine_module
        first = ee.get_execution_engine()
        ee.reset_execution_engine()
        second = ee.get_execution_engine()
        assert second is not first, "reset 后取回同一对象 = 隔离无效"

    def test_rebuilt_instance_is_fully_initialized(self, engine_module):
        ee = engine_module
        ee.get_execution_engine()
        ee.reset_execution_engine()
        rebuilt = ee.get_execution_engine()
        assert rebuilt._initialized is True
        # 组件重新装配——监控器是这把引擎今天唯一的组件，也是唯一还有人来路的那条
        assert rebuilt._execution_monitor is not None

    def test_reset_is_idempotent_and_safe_when_never_created(self, engine_module):
        ee = engine_module
        ee.reset_execution_engine()  # 从未创建
        ee.reset_execution_engine()
        assert ee.ExecutionEngine._instance is None

    def test_old_instance_keeps_its_own_init_mark(self, engine_module):
        """旧实例不得被就地失效。

        刻意不翻旧实例的 ``_initialized``：并发下已持有旧引用的调用方会观察到
        "返回对象自称未初始化"的自相矛盾状态（实测过）。
        """
        ee = engine_module
        first = ee.get_execution_engine()
        ee.reset_execution_engine()
        assert first._initialized is True, "旧实例状态被就地失效（并发引用会观察到矛盾状态）"

    def test_concurrent_reset_and_get_yields_complete_instance(self, engine_module):
        """并发 reset + get 不得产出"半初始化"对象（__new__ 与 __init__ 竞态）。

        判定用结构完整性（``_execution_monitor`` 已在 = ``__init__`` 跑完）而非
        ``_initialized`` 标记——后者会被并发的 reset 就地改写，属观测噪声。
        """
        ee = engine_module
        errors = []
        seen = []

        def worker():
            try:
                for _ in range(20):
                    engine = ee.get_execution_engine()
                    seen.append(hasattr(engine, "_execution_monitor"))
                    ee.reset_execution_engine()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发 reset/get 抛异常: {errors}"
        assert seen and all(seen), "存在未完成初始化的实例被返回（__new__/__init__ 竞态）"

    def test_conftest_wires_reset_for_test_isolation(self):
        """契约须挂在真实调用点：conftest 的 autouse 隔离 fixture 调用它。"""
        import io
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        src = io.open(root / "tests" / "conftest.py", encoding="utf-8").read()
        assert "reset_execution_engine" in src, (
            "conftest 未接线 reset_execution_engine——重置契约又回到'零调用方'状态"
        )
