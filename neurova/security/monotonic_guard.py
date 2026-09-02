"""单调守卫（Monotonic Guard）—— 可插拔的拒绝型安全检查链。

设计契约（对齐 DeepSeek Harness guards 语义，见 docs 内部评审备注）：
- 守卫只允许返回 DENY 或 ABSTAIN；契约上不存在 ALLOW。
  "放行"必须由"没有任何守卫拒绝"推导——任何守卫都不能批准调用，
  杜绝"放行式检查"成为安全链条的最弱环节。
- 守卫自身异常 → fail-closed 视为 DENY（与治理 fail-closed 纪律一致），
  绝不放行。
- 注册可逆：register() 返回 disposer，调用后守卫不再参与判定，幂等。
- 注册表为空时 check_all() 恒返回 None —— 与接入前行为完全等价。

使用方式（在治理中心 evaluate_tool_call 入口调用一次即可）：

    registry = get_monotonic_guards()
    registry.register(MyGuard(), scope=("mcp.",))
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class GuardVerdict(str, Enum):
    """守卫裁决：只有拒绝与弃权两种值，没有放行。"""

    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass
class GuardOutcome:
    """一次 DENY 裁决的详细信息（进入治理结果、审计与 UI 提示）。"""

    rule_id: str
    message: str
    severity: str = "medium"  # 取值域与 tool_guard.GuardSeverity 一致
    evidence: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity,
        }
        if self.evidence:
            result["evidence"] = self.evidence
        return result


class Guard(Protocol):
    """守卫协议：实现 check()，按注册序遍历执行。"""

    rule_id: str

    def check(
        self,
        tool_name: str,
        params: Any,
        user_id: Optional[str] = None,
    ) -> GuardVerdict:
        """返回 DENY 或 ABSTAIN；抛异常视为 DENY（fail-closed）。"""
        ...


@dataclass
class _Registration:
    guard: Guard
    scope: Optional[Sequence[str]] = None
    disposed: bool = field(default=False)

    def matches(self, tool_name: str) -> bool:
        if not self.scope:
            return True
        return any(tool_name.startswith(prefix) for prefix in self.scope)


class MonotonicGuardRegistry:
    """守卫注册表：按注册序评估，任一 DENY 短路并返回首个裁决。

    check_all 在锁外持有守卫副本后逐个调用，因此检查期间注册/卸载
    不会破坏遍历（卸载的守卫至多在本次检查中仍生效一次）。
    """

    def __init__(self) -> None:
        self._registrations: List[_Registration] = []
        self._lock = threading.RLock()

    def register(
        self,
        guard: Guard,
        *,
        scope: Optional[Sequence[str]] = None,
    ) -> Callable[[], None]:
        """注册守卫（可逆副作用）。scope 为工具名前缀白名单，None=全部。

        Returns:
            disposer：调用后守卫不再参与判定；重复调用幂等。
        """
        registration = _Registration(guard=guard, scope=scope)
        with self._lock:
            self._registrations.append(registration)

        def disposer() -> None:
            with self._lock:
                if registration.disposed:
                    return
                registration.disposed = True
                try:
                    self._registrations.remove(registration)
                except ValueError:
                    pass  # 幂等：守卫已被清除

        return disposer

    def unregister(self, rule_id: str) -> bool:
        """按 rule_id 卸载；不存在时返回 False。"""
        with self._lock:
            for registration in self._registrations:
                if registration.guard.rule_id == rule_id:
                    registration.disposed = True
                    self._registrations.remove(registration)
                    return True
        return False

    def check_all(
        self,
        tool_name: str,
        params: Any,
        user_id: Optional[str] = None,
    ) -> Optional[GuardOutcome]:
        """按注册序评估命中作用域的守卫。

        Returns:
            首个 DENY 的 GuardOutcome；全部 ABSTAIN 或空注册表时返回 None。
        """
        with self._lock:
            registrations = list(self._registrations)

        for registration in registrations:
            if registration.disposed or not registration.matches(tool_name):
                continue
            guard = registration.guard
            try:
                verdict = guard.check(tool_name, params, user_id)
            except Exception as e:  # noqa: BLE001 - fail-closed：守卫故障即拒绝
                logger.exception("单调守卫 %s 检查异常（fail-closed DENY）", guard.rule_id)
                return GuardOutcome(
                    rule_id=guard.rule_id,
                    message=f"守卫 {guard.rule_id} 异常，已拒绝执行: {e}",
                    severity="high",
                )
            if verdict == GuardVerdict.DENY:
                logger.warning("单调守卫 %s 拒绝工具 %s", guard.rule_id, tool_name)
                return GuardOutcome(rule_id=guard.rule_id, message=f"守卫 {guard.rule_id} 拦截")
        return None

    def clear(self) -> None:
        """清空全部守卫（恢复到等价于未接入状态）。"""
        with self._lock:
            self._registrations.clear()

    def list_guards(self) -> List[Guard]:
        with self._lock:
            return [r.guard for r in self._registrations]

    def __len__(self) -> int:
        with self._lock:
            return len(self._registrations)


_global_registry: Optional[MonotonicGuardRegistry] = None
_registry_lock = threading.RLock()


def get_monotonic_guards() -> MonotonicGuardRegistry:
    """全局守卫注册表单例（工厂模式）。"""
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = MonotonicGuardRegistry()
    return _global_registry


def reset_monotonic_guards() -> None:
    """重置全局单例（测试与热更新用）。"""
    global _global_registry
    with _registry_lock:
        _global_registry = None


__all__ = [
    "Guard",
    "GuardOutcome",
    "GuardVerdict",
    "MonotonicGuardRegistry",
    "get_monotonic_guards",
    "reset_monotonic_guards",
]
