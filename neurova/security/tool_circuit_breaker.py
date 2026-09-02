"""工具执行熔断器（与 LLM 层同源实现，复用 rate_limiter.CircuitBreaker）。

解决缺口：聊天主链（chat_pipeline → ToolExecutor._execute_single_tool 咽喉点）
在工具后端持续故障时缺少熔断——每轮仍走完整治理评估 + 尝试执行 + 等待超时，
故障风暴期间主链延迟放大。装配后：

- 观察者段：result 观察者把每次工具执行的成功/失败喂给熔断器（失败达阈值→打开）
- 守卫段：熔断打开 → 单调守卫 DENY → 治理前置预检快速拒绝（不进执行体、不等待）
- 半开探测：恢复窗口过后放行一个请求，成功→关闭，失败→重新打开

语义边界（防呆）：
- **策略性拒绝不计数**：治理 ASK/DENY/SANDBOX 拦截（result 含 governance /
  pending_approval 键）是"决策"而非"后端故障"——把用户拒绝计入故障会把
  不应熔断的服务熔断。
- **熔断器自身故障=自降级 ABSTAIN**：熔断是弹性防护（可降级），与治理的
  硬 fail-closed（安全策略）不同——熔断器损坏只丢防护，不把工具执行全屏蔽。
- **默认不安装**：install_tool_circuit_breaker() 显式装配（幂等）；未安装时
  行为与未接入完全等价（零回归面）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.llm.providers.rate_limiter import CircuitBreaker
from neurova.security.monotonic_guard import GuardVerdict, get_monotonic_guards
from neurova.agent.tool_pipeline import get_pipeline_observers

logger = get_logger(__name__)

RULE_ID = "tool_circuit_breaker"


class ToolCircuitBreakerGuard:
    """单调守卫：熔断打开 → DENY（快速失败），否则 ABSTAIN。

    契约满足 deny-or-abstain（只拒绝/弃权，无批准）；
    熔断器自身异常时自降级 ABSTAIN（弹性防护可降级，见模块头语义边界）。
    """

    rule_id = RULE_ID

    def __init__(self, breaker: CircuitBreaker) -> None:
        self.breaker = breaker

    def check(self, tool_name: str, params: Any,
              user_id: Optional[str] = None) -> GuardVerdict:
        try:
            if self.breaker.can_execute():
                return GuardVerdict.ABSTAIN
            logger.warning(
                "工具熔断器打开（%s），快速拒绝 %s", self.breaker.name, tool_name)
            return GuardVerdict.DENY
        except Exception:  # noqa: BLE001 - 熔断器故障只丢防护，不阻断工具执行
            logger.exception("工具熔断器异常（自降级放行）: %s", tool_name)
            return GuardVerdict.ABSTAIN


class ToolCircuitBreakerObserver:
    """result 观察者：把工具执行结果喂给熔断器（策略拒绝不计数）。"""

    def __init__(self, breaker: CircuitBreaker) -> None:
        self.breaker = breaker

    def __call__(self, report) -> None:
        try:
            # 策略性拒绝（治理拦截/待审批）是决策不是故障——与 on_tool_executed
            # 三处统计共用同一判定（governance.is_policy_denial），单源口径。
            from neurova.security.governance import is_policy_denial

            if is_policy_denial(report.result):
                return
            if report.success:
                self.breaker.record_success()
            else:
                self.breaker.record_failure()
        except Exception:  # noqa: BLE001 - 观察者故障已被门面隔离，这里只留痕
            logger.warning("熔断器观察者失败: %s", report, exc_info=True)


@dataclass
class ToolCircuitBreakerHandle:
    """装配句柄：breaker + guard + observer + 可逆 disposers。"""

    breaker: CircuitBreaker
    guard: ToolCircuitBreakerGuard
    observer: ToolCircuitBreakerObserver
    _disposers: List[Callable[[], None]] = field(default_factory=list)

    def dispose(self) -> None:
        for disposer in self._disposers:
            try:
                disposer()
            except Exception:  # noqa: BLE001 - 卸载失败不阻止继续
                logger.warning("熔断器卸载组件失败", exc_info=True)
        self._disposers.clear()


_global_handle: Optional[ToolCircuitBreakerHandle] = None
_install_lock = threading.RLock()


def install_tool_circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    success_threshold: int = 1,
    name: str = "tools",
) -> ToolCircuitBreakerHandle:
    """装配工具熔断器（幂等：已安装返回同一句柄）。

    默认参数与 LLM 层 per-provider 熔断一致（failure_threshold=5,
    recovery_timeout=30s, success_threshold=1）。
    """
    global _global_handle
    with _install_lock:
        if _global_handle is not None:
            return _global_handle

        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            name=name,
        )
        guard = ToolCircuitBreakerGuard(breaker)
        observer = ToolCircuitBreakerObserver(breaker)
        handle = ToolCircuitBreakerHandle(
            breaker=breaker,
            guard=guard,
            observer=observer,
            _disposers=[
                get_monotonic_guards().register(guard),
                get_pipeline_observers().add_result_observer(observer),
            ],
        )
        logger.info("工具熔断器已装配（%s, 阈值 %s/%s）",
                    name, failure_threshold, recovery_timeout)
        _global_handle = handle
        return handle


def uninstall_tool_circuit_breaker(force: bool = False) -> None:
    """卸载工具熔断器（可逆；幂等）。force=True 时强制清空全局句柄。"""
    global _global_handle
    with _install_lock:
        handle, _global_handle = _global_handle, None
        if force:
            handle = None
        if handle is not None:
            handle.dispose()


def get_tool_circuit_breaker() -> Optional[CircuitBreaker]:
    handle = get_installed_handle()
    return handle.breaker if handle else None


def get_installed_handle() -> Optional[ToolCircuitBreakerHandle]:
    with _install_lock:
        return _global_handle


def get_tool_circuit_breaker_stats() -> Dict[str, Any]:
    """熔断器健康快照（未安装时返回空 dict）。"""
    breaker = get_tool_circuit_breaker()
    return breaker.get_stats() if breaker else {}


__all__ = [
    "RULE_ID",
    "ToolCircuitBreakerGuard",
    "ToolCircuitBreakerHandle",
    "ToolCircuitBreakerObserver",
    "get_installed_handle",
    "get_tool_circuit_breaker",
    "get_tool_circuit_breaker_stats",
    "install_tool_circuit_breaker",
    "uninstall_tool_circuit_breaker",
]
