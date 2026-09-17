"""工具执行后处理管线 — 五段流水线版本。

五段语义：pre → guard → execute(main) → post → result

- pre / guard（拒绝型策略前置）：生产主链由 GovernancePolicy（security/governance）
  承载（含 security/monotonic_guard 的 deny-or-abstain 契约）；本组件的 pre/guard
  段供扩展场景（沙箱语境改写、自定义策略）插桩，与治理中心共享同一 Guard 协议。
- execute：主执行体由调用方传入（ToolExecutor 负责真实执行与超时），
  经 execute_wrapper（middleware）环绕——超时/重试/指标可在此插桩。
- post：调用方注册的后置步骤（`add_step` / `add_post_step`），含并行段。
- result：观察者收到**独立深拷贝快照**（不可变语义：观察者改动不污染报告），
  经 `get_pipeline_observers` / `notify_tool_result` 门面接入
  `ToolExecutor.on_tool_executed`（默认空注册表 = 零行为变化）。

历史：C2/ADR 0010 曾将本模块标记为死代码（生产路径不调用，仅测试引用）。
本次升级后：本组件为组件化流水线 + result 观察者扩展点——**这条是活的**
（生产消费方：`neurova/security/tool_circuit_breaker.py` 经
`get_pipeline_observers().add_result_observer(...)` 挂熔断观察者）。

P2（Issue #46）：上述"记忆/生命周期/技能/进化四类旧步骤"
（`SkillObservationStep` 等四个 Step 类）与装配它们的 `create_default_pipeline`
在 `neurova/` 内**零生产调用**（只有测试引用），已真删——它们的职责在生产上
由 `ToolExecutor.on_tool_executed` 尾部承担；技能观察的唯一正确通道是
`creation_governance` 的 ContextVar 采集器（那条才有证据闸）。保留旧 Step
类只会让后来者把无证据通道当接线模板。
"""

from __future__ import annotations

import copy
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.security.monotonic_guard import GuardVerdict
from neurova.tool_layers.types import ToolExecutionContext as _CanonicalContext

logger = get_logger(__name__)


class ToolExecutionContext(_CanonicalContext):
    """兼容旧构造的规范上下文（14 字段超集）。

    旧代码以 success=True / execution_time= 关键字构造（7 字段版本）；
    两者映射到 status / metadata 字段，新代码直接使用规范字段。
    """

    def __init__(self, *args, success: Optional[bool] = None,
                 execution_time: Optional[float] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._legacy_success = success
        self._legacy_execution_time = execution_time

    @property
    def success(self) -> bool:
        """旧语义兼容：规范 status 推导 success。"""
        legacy = getattr(self, "_legacy_success", None)
        if legacy is not None:
            return legacy
        return str(getattr(self, "status", "")).lower() in ("completed", "success", "done")

    @property
    def execution_time(self) -> float:
        return getattr(self, "_legacy_execution_time", None) or 0.0


class PipelineReject(Exception):
    """pre 段拒绝对该次执行：跳过 main，post/result 仍执行（供观测记录）。"""


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


class ToolExecutionStep:
    """后置步骤基类（旧语义）。"""

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def error_level(self) -> str:
        raise NotImplementedError

    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):  # noqa: B027
        """执行步骤（子类实现）。"""


class PipelineConfig:
    """管线配置。

    P2（Issue #46）：原配置里另有 6 个**从未被读取**的开关
    （enable_memory_recording / enable_lifecycle_update /
    enable_skill_observation / enable_evolution_feedback / continue_on_error /
    log_level）——它们对应的四个 Step 类零生产调用，已一并删除。留着这些
    开关等于给读者一份"可以关掉某一步"的假能力（实际没有任何代码读它），
    是一条静默的谎——故真删，而不是标注保留。
    只剩两个**有真实消费方**的字段（`_run_post_steps` 读它们）。
    """

    parallel_independent_steps: bool = True
    max_workers: int = 2


class PipelineGuardAdapter:
    """适配单调守卫协议（monotonic_guard.Guard）为管线 guard。

 check 必须返回 GuardVerdict.DENY/ABSTAIN——契约上不存在放行。
    该适配器同样可直接注册到 GovernancePolicy 的守卫注册表（rule_id+check）。
    """

    rule_id: str

    def __init__(self, rule_id: str,
                 check_fn: Callable[[str, Any, Optional[str]], GuardVerdict]):
        self.rule_id = rule_id
        self._check_fn = check_fn

    def check(self, tool_name: str, params: Any,
              user_id: Optional[str] = None) -> GuardVerdict:
        return self._check_fn(tool_name, params, user_id)


class ToolExecutionPipeline:
    """
    工具执行五段流水线（pre → guard → execute → post → result）。

    兼容旧用法：add_step() + execute(context) 仅执行 post 段（旧语义）；
    新用法：add_pre_step / add_guard / add_execute_wrapper / add_result_observer
    + resolve(context, main=main_fn)。主执行体为同步回调；异步组合由调用方外包。
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self._config = config or PipelineConfig()
        self._steps: List[ToolExecutionStep] = []
        self._pre_steps: List[ToolExecutionStep] = []
        self._guards: List[PipelineGuardAdapter] = []
        self._wrappers: List[Callable] = []
        self._observers: List[Callable] = []
        self._lock = threading.RLock()

    # ── 注册 ────────────────────────────────────────────────────

    @property
    def steps(self) -> List[ToolExecutionStep]:
        return self._steps

    def add_step(self, step: ToolExecutionStep):
        """添加后置步骤（旧语义入口；等价 add_post_step）。"""
        self.add_post_step(step)

    def add_post_step(self, step: ToolExecutionStep):
        with self._lock:
            self._steps.append(step)

    def add_pre_step(self, step: ToolExecutionStep):
        """pre 段步骤：execute(context, report)，可抛 PipelineReject 拒绝。"""
        with self._lock:
            self._pre_steps.append(step)

    def add_guard(self, guard: PipelineGuardAdapter):
        """guard 段：deny-or-abstain 契约（见 PipelineGuardAdapter）。"""
        with self._lock:
            self._guards.append(guard)

    def add_execute_wrapper(self, wrapper: Callable[[Any, Callable], Any]):
        """execute 段 middleware：wrapper(context, next_fn) -> result。"""
        with self._lock:
            self._wrappers.append(wrapper)

    def add_result_observer(self, observer: Callable[[ToolExecutionReport], None]):
        """result 段观察者：收到独立深拷贝快照（异常彼此隔离）。"""
        with self._lock:
            self._observers.append(observer)

    # ── 五段执行 ────────────────────────────────────────────────

    def execute(self, context: ToolExecutionContext) -> ToolExecutionReport:
        """兼容入口：= resolve(context)（旧用法等价——无 main 时跳过 execute 段）。"""
        return self.resolve(context, main=None)

    def resolve(
        self,
        context: ToolExecutionContext,
        main: Optional[Callable[[ToolExecutionContext], Optional[Dict[str, Any]]]] = None,
    ) -> ToolExecutionReport:
        """执行五段。"""

        start_time = time.time()
        report = ToolExecutionReport(
            tool_name=context.tool_name,
            success=bool(getattr(context, "success", False)),
            execution_time=float(getattr(context, "execution_time", 0.0) or 0.0),
            metadata=copy.deepcopy(getattr(context, "metadata", None) or {}),
        )
        skipped_main = False

        # 1) pre 段
        for step in list(self._pre_steps):
            try:
                step.execute(context, report)
            except PipelineReject as e:
                skipped_main = True
                report.rejected = True
                report.errors.append(str(e))
                logger.warning("管线 pre 拒绝 %s: %s", context.tool_name, e)
                break
            except Exception as e:  # noqa: BLE001 - pre 故障：记录并短路 main
                skipped_main = True
                report.rejected = True
                report.errors.append(f"pre {getattr(step, 'name', '?')}: {e}")
                logger.exception("管线 pre 步骤失败: %s", getattr(step, "name", "?"))
                break

        # 2) guard 段（单调守卫：deny/abstain；异常=fail-closed deny）
        if not skipped_main:
            for guard in list(self._guards):
                try:
                    verdict = guard.check(context.tool_name, context.params)
                except Exception as e:  # noqa: BLE001 - fail-closed
                    skipped_main = True
                    report.rejected = True
                    report.errors.append(f"守卫 {guard.rule_id} 异常: {e}")
                    logger.exception("管线守卫 %s 异常（fail-closed）", guard.rule_id)
                    break
                if verdict == GuardVerdict.DENY:
                    skipped_main = True
                    report.rejected = True
                    report.errors.append(f"守卫 {guard.rule_id} 拦截")
                    logger.warning("管线守卫 %s 拒绝 %s", guard.rule_id, context.tool_name)
                    break

        # 3) execute 段（主执行体 + middleware 环绕）
        if not skipped_main and main is not None:
            payload = _compose_wrappers(self._wrappers, main)
            try:
                report.result = payload(context)
                report.success = report.result is not None
            except Exception as e:  # noqa: BLE001 - 主执行异常入报告，不炸传
                report.success = False
                report.errors.append(f"execute: {e}")
                logger.exception("管线主执行失败: %s", context.tool_name)

        # 4) post 段（旧语义：memory/skill 并行，其余串行；错误进 warnings/errors）
        self._run_post_steps(context, report)

        # 5) result 段（冻结快照 + 观察者隔离）
        frozen = report.frozen()
        for observer in list(self._observers):
            try:
                observer(frozen)
            except Exception as e:  # noqa: BLE001 - 观察者故障隔离
                report.warnings.append(f"result observer: {e}")
                logger.warning("管线结果观察者失败: %s", e, exc_info=True)

        report.total_processing_time = time.time() - start_time
        return report

    def _run_post_steps(self, context, report):
        """旧语义步骤执行。"""
        if not self._steps:
            return
        independent_steps = []
        dependent_steps = []
        for step in self._steps:
            name = getattr(step, "name", "")
            if name in ("memory_recording", "skill_observation"):
                independent_steps.append(step)
            else:
                dependent_steps.append(step)

        if self._config.parallel_independent_steps and len(independent_steps) > 1:
            with ThreadPoolExecutor(max_workers=self._config.max_workers) as executor:
                futures = {}
                for step in independent_steps:
                    step_start = time.time()
                    futures[executor.submit(step.execute, context, report)] = (step, step_start)
                for future in as_completed(futures):
                    step, step_start = futures[future]
                    self._record_step_outcome(future, step, report, time.time() - step_start)
        else:
            for step in independent_steps + dependent_steps:
                step_start = time.time()
                try:
                    step.execute(context, report)
                    report.step_times[getattr(step, "name", "?")] = time.time() - step_start
                except Exception as e:  # noqa: BLE001 - 记录后继续
                    self._record_step_error(step, report, time.time() - step_start, e)

    def _record_step_outcome(self, future, step, report, elapsed):
        try:
            future.result()
            report.step_times[getattr(step, "name", "?")] = elapsed
        except Exception as e:  # noqa: BLE001
            self._record_step_error(step, report, elapsed, e)

    @staticmethod
    def _record_step_error(step, report, elapsed, e):
        report.step_times[getattr(step, "name", "?")] = elapsed
        error_level = getattr(step, "error_level", "warning")
        if error_level == "critical":
            report.errors.append(f"Critical: {getattr(step, 'name', '?')}: {e}")
            logger.error("关键步骤失败: %s", e)
        else:
            report.warnings.append(f"{getattr(step, 'name', '?')}: {e}")
            logger.warning("步骤失败: %s", e)


def _compose_wrappers(wrappers: List[Callable], main: Callable) -> Callable:
    """middleware 组合：最后注册的 wrapper 最贴近 main（洋葱模型）。"""
    composed = main
    for wrapper in reversed(wrappers):
        inner = composed

        def _wrap(context, _inner=inner, _wrapper=wrapper):
            return _wrapper(context, _inner)

        composed = _wrap
    return composed


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


def reset_pipeline_observers() -> None:
    """重置全局单例（测试与热更新用）。"""
    global _global_observers
    with _observers_lock:
        _global_observers = None


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
    "PipelineConfig",
    "PipelineGuardAdapter",
    "PipelineObserversRegistry",
    "PipelineReject",
    "ToolExecutionContext",
    "ToolExecutionPipeline",
    "ToolExecutionReport",
    "ToolExecutionStep",
    "get_pipeline_observers",
    "notify_tool_result",
    "reset_pipeline_observers",
]
