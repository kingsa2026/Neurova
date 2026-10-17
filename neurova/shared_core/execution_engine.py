from __future__ import annotations

"""
Execution Engine —— 执行监控器的宿主单例

本模块今天只提供一件事：
- 执行监控（装配 `ExecutionMonitor` 并经 `get_execution_monitor()` 交给 `/api/v1/monitor/*`）

曾与这把引擎同处的工具执行、工作流执行、计划节点执行与那份进程内执行台账已整体退役：
全仓无一条来路（运行时探针实测 `get_execution_monitor: 2`，其余 14 个方法计数全 0），
替代分别是 `tool_executor._execute_tool_core` 这条真咽喉（治理、票据、hooks 都在它身上）与
`collaboration/neurflow/` 那台真 DAG 引擎（拓扑分层＋层内并发＋`safe_eval_condition` 真分支）。
逐条证据与来历见 `audit-reports/execution-engine-subtree-archive-2026-10-17.md`。

别把这里的单例当"通用执行入口"用——它不是，也不该是：工具与工作流各有自己的真咽喉。
"""

import threading
import typing

from neurova.core.logger import get_logger

logger = get_logger(__name__)

if typing.TYPE_CHECKING:  # 仅类型检查期：monitor 为可选组件，运行期函数内 try/except 懒加载
    from neurova.execution_engine.execution_monitor import ExecutionMonitor


class ExecutionEngine:
    """执行引擎单例。

    今天只装配并对外提供执行监控器；`monitor.py` 那三个端点是它唯一的生产来路。
    """

    _instance: typing.Optional["ExecutionEngine"] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._execution_monitor: typing.Optional["ExecutionMonitor"] = None
        self._init_components()

        self._initialized = True
        logger.info("ExecutionEngine 初始化完成")

    def _init_components(self) -> None:
        """装配执行监控器（延迟导入避免循环依赖）"""
        try:
            from neurova.execution_engine.execution_monitor import ExecutionMonitor

            self._execution_monitor = ExecutionMonitor()
            logger.debug("ExecutionEngine 组件初始化完成")

        except ImportError as e:
            logger.warning("ExecutionEngine 组件导入失败: %s", e)
            self._execution_monitor = None

    def get_execution_monitor(self) -> typing.Optional["ExecutionMonitor"]:
        """获取执行监控器（可能为 None: 组件导入失败时的占位）"""
        return self._execution_monitor


# 工厂函数
_execution_engine: typing.Optional[ExecutionEngine] = None
_execution_engine_lock = threading.Lock()


def get_execution_engine() -> ExecutionEngine:
    """获取执行引擎单例"""
    global _execution_engine
    if _execution_engine is None:
        # P3-e：DCL——单例装配监控器，不可双创建
        with _execution_engine_lock:
            if _execution_engine is None:
                _execution_engine = ExecutionEngine()
    return _execution_engine


def reset_execution_engine() -> None:
    """重置执行引擎（用于测试隔离）。

    Issue #65 那一次修的是"只清模块级缓存、没清类级 `_instance`"：reset 后再取回的是同一个对象，
    `_initialized` 仍为 True，任何依赖它做隔离的测试都拿到脏状态。当时清了三层，其中第三层
    （旧实例的 `_executions` 执行记录）随执行台账面一并退役——今天这把引擎不再有实例级可变状态，
    所以剩两层：

    1. 模块级缓存 ``_execution_engine``；
    2. 类级单例 ``ExecutionEngine._instance``（置 None，下次 ``__new__`` 重建 →
       ``_initialized=False`` → ``__init__`` 重新装配监控器）。

    调用方：``tests/conftest.py`` 的 autouse 隔离 fixture。
    """
    global _execution_engine
    with _execution_engine_lock:
        _execution_engine = None
        ExecutionEngine._instance = None
    logger.debug("ExecutionEngine 单例已重置（模块缓存 + 类级 _instance）")
