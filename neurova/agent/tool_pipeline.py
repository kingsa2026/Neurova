"""工具执行结果观察门面（`ToolExecutor.on_tool_executed` 尾部挂载点）。

本模块在 **T-09 死码处置批（Issue #174 / #310）** 之后只剩一件事：把工具执行结果
以**冻结快照**形态分发给注册的观察者。

- 写入侧唯一接入点：`ToolExecutor.on_tool_executed` 尾部的 `notify_tool_result(...)`；
- 读取侧唯一生产消费方：`security/tool_circuit_breaker.py` 经
  `get_pipeline_observers().add_result_observer(...)` 挂熔断观察者；
- 默认空注册表 = 零行为变化（`notify_tool_result` 空表 no-op）。

## 已退场的部分（别再把它接回来）

此前的「五段流水线」（pre → guard → execute → post → result）框架整体退场：
`ToolExecutionPipeline` / `PipelineConfig` / `PipelineGuardAdapter` /
`ToolExecutionStep` / `PipelineReject` / `reset_pipeline_observers` 与兼容子类
`ToolExecutionContext` 已删净。依据是机器事实——四段的注册入口
（`add_pre_step` / `add_guard` / `add_execute_wrapper` / `add_post_step`）
在生产侧**全仓零调用**，`ToolExecutionPipeline` 本身也零引用（连 import 都没有）。

它们的职责在生产上由 `ToolExecutor` 的信封承担（票据 / 治理预检 / hooks /
per-tool 超时全链生效）；再挂一套五段框架就是**第二份执行编排**（教义第 6 条）。
「五段流水线是否要以 `PipelineConfig` 形态接线」这个问题因此**不是待办，是已被否证的方案**。

`ToolExecutionReport` 保留：它是 result 面发给观察者的对外契约形状
（`frozen()` 深拷贝快照）。它上面那四个 `memory_recorded` / `lifecycle_updated` /
`skill_observed` / `evolution_notified` 字段的来源（旧四步门面 + `create_default_pipeline`）
已在 P2（Issue #46）真删，字段恒 False，只作形状兼容——`is_fully_successful`
的 docstring 已注明不得据此判成功。
"""

from __future__ import annotations

import copy
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolExecutionReport:
    """工具执行后处理报告（字段向后兼容旧版 + 五段状态）。"""

    # 基本信息
    tool_name: str
    success: bool
    execution_time: float
    timestamp: float = field(default_factory=time.time)

    # 各步骤执行状态——**旧四步门面的产物，生产者已随 P2 删除**（见下方
    # `is_fully_successful` 的注记）。字段保留是因为观察者拿到的是本报告的
    # 冻结快照（`frozen()` / `to_dict()`），形状属对外契约；但默认值恒 False，
    # 不要再把它们当成"这一步跑过了吗"的判据。
    memory_recorded: bool = False
    lifecycle_updated: bool = False
    skill_observed: bool = False
    evolution_notified: bool = False

    # 错误信息
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # 性能指标
    total_processing_time: float = 0.0
    step_times: Dict[str, float] = field(default_factory=dict)

    # 附加信息
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 五段流水线状态（v2 新增；旧字段语义不变）
    rejected: bool = False
    result: Optional[Dict[str, Any]] = None

    @property
    def is_fully_successful(self) -> bool:
        """是否所有后置步骤都成功。

        ⚠️ P2（Issue #46）：本判据的四个来源都是**旧四步门面**的产物，而
        那个门面（`create_default_pipeline` + 四个 Step 类）零生产调用，已
        真删——故本属性在生产上恒 False。保留只为兼容既有测试/观察者签名，
        **不要**据此判断执行是否成功（看 `errors` / `success` / `rejected`）。
        """
        return (self.memory_recorded
                and self.lifecycle_updated
                and self.skill_observed
                and self.evolution_notified)

    @property
    def stage(self) -> str:
        """终止阶段（未 rejected → executed，被拒 → rejected）。"""
        return "rejected" if self.rejected else "executed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp,
            "memory_recorded": self.memory_recorded,
            "lifecycle_updated": self.lifecycle_updated,
            "skill_observed": self.skill_observed,
            "evolution_notified": self.evolution_notified,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "total_processing_time": self.total_processing_time,
            "step_times": dict(self.step_times),
            "metadata": copy.deepcopy(self.metadata),
            "rejected": self.rejected,
            "result": copy.deepcopy(self.result),
        }

    def frozen(self) -> "ToolExecutionReport":
        """返回独立不可变语义快照（深拷贝；观察者改动不污染源报告）。"""
        return ToolExecutionReport(**self.to_dict())


# ── 结果观察者门面（ToolExecutor.on_tool_executed 尾部挂载点） ────

class PipelineObserversRegistry:
    """全局结果观察者注册表（轻量门面；默认空 = 零行为变化）。"""

    def __init__(self) -> None:
        self._observers: List[Callable[[ToolExecutionReport], None]] = []
        self._lock = threading.RLock()

    def add_result_observer(
        self, observer: Callable[[ToolExecutionReport], None]
    ) -> Callable[[], None]:
        with self._lock:
            self._observers.append(observer)

        def disposer() -> None:
            with self._lock:
                try:
                    self._observers.remove(observer)
                except ValueError:
                    pass

        return disposer

    def list_result_observers(self) -> List[Callable]:
        with self._lock:
            return list(self._observers)

    def clear(self) -> None:
        with self._lock:
            self._observers.clear()


_global_observers: Optional[PipelineObserversRegistry] = None
_observers_lock = threading.RLock()


def get_pipeline_observers() -> PipelineObserversRegistry:
    """全局结果观察者注册表单例。"""
    global _global_observers
    if _global_observers is None:
        with _observers_lock:
            if _global_observers is None:
                _global_observers = PipelineObserversRegistry()
    return _global_observers


def notify_tool_result(
    tool_name: str,
    success: bool,
    result: Optional[Dict[str, Any]] = None,
    **context: Any,
) -> None:
    """工具结果通知（冻结快照；观察者异常隔离；空注册表 no-op）。

    由 ToolExecutor.on_tool_executed 尾部调用——这是唯一接入点，
    默认没有任何观察者时行为与未接入完全一致。
    """
    report = ToolExecutionReport(
        tool_name=tool_name,
        success=success,
        execution_time=float(context.get("execution_time", 0.0) or 0.0),
        result=copy.deepcopy(result) if result is not None else None,
        metadata=copy.deepcopy({
            "tool_source": context.get("tool_source", ""),
            "user_input": context.get("user_input", ""),
        }),
    )
    frozen = report.frozen()
    for observer in get_pipeline_observers().list_result_observers():
        try:
            observer(frozen)
        except Exception as e:  # noqa: BLE001 - 观察者故障隔离
            logger.warning("结果观察者失败: %s", e, exc_info=True)


__all__ = [
    "PipelineObserversRegistry",
    "ToolExecutionReport",
    "get_pipeline_observers",
    "notify_tool_result",
]
