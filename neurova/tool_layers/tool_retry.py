# -*- coding: utf-8 -*-
"""U11 失败分级重试守卫（工具调用级）——从 neurova.tool_executor 拆出。

只移动 `ToolExecutor` 的 `_retryGate*` / `_retrySuppressedResult` 方法，
不改变任何语义。不变量：

- 同参指纹 `executionFingerprint(tool_name, params)`；
- `_retryLedger` + `_retryLedgerLock` 仍由 `ToolExecutor.__init__` 唯一创建；
- 不重试应用层失败；变异类工具未声明 idempotent 时 transport 也不重试；
- `classifyToolFailure` / `retryDecisionFor` / `_toolIsMutation` /
  `_toolIdempotentDeclared` 与常量单源于本模块；`neurova.tool_executor`
  re-export 旧导入路径。

本模块不得在顶层 import `neurova.tool_executor`：
`neurova.tool_executor` import 本 mixin，而 `neurova.agent.__init__`
会从 `neurova.tool_executor` re-export `ToolExecutor`。
"""
import time
from typing import Any, Dict, Optional

__all__ = [
    "ToolRetryMixin",
    "TOOL_RETRY_SUPPRESSED_CODE",
    "TOOL_RETRY_SUPPRESSION_WINDOW_S",
    "_RETRY_INFLIGHT_TTL_S",
    "_RETRY_LEDGER_MAX",
    "_TRANSPORT_ERROR_TYPE_NAMES",
    "_TRANSPORT_TEXT_MARKERS",
    "_toolIdempotentDeclared",
    "_toolIsMutation",
    "classifyToolFailure",
    "retryDecisionFor",
]

#: 稳定错误码：同参调用因上一轮不可重试失败而被拒绝重试。
TOOL_RETRY_SUPPRESSED_CODE = "TOOL_RETRY_SUPPRESSED"
#: 同参不可重试失败的抑制窗（秒）：窗内同参调用被拒绝，过窗视为新调用。
TOOL_RETRY_SUPPRESSION_WINDOW_S = 60.0
#: 在途登记的安全 TTL（秒）——异常路径漏清账时不至于永久抑制。
_RETRY_INFLIGHT_TTL_S = 600.0
#: 抑制登记表容量上限（有界，防无界增长；淘汰最老）。
_RETRY_LEDGER_MAX = 256

#: transport 级失败的异常类型名（保守列举；拿不准的一律按 application 处置）。
_TRANSPORT_ERROR_TYPE_NAMES = frozenset({
    "ConnectionError", "ConnectionResetError", "ConnectionRefusedError",
    "ConnectionAbortedError", "BrokenPipeError", "TimeoutError", "InterruptedError",
    "SSLError", "SSHException", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "WriteTimeout", "PoolTimeout", "NetworkError", "ClientConnectionError",
    "CancelledError",
})

#: transport 级失败的错误文本标记（小写匹配；保守列举）。
_TRANSPORT_TEXT_MARKERS = (
    "timed out", "timeout", "超时", "connection", "连接", "network", "网络",
    "unreachable", "reset by peer", "broken pipe", "econnrefused", "econnreset",
    "etimedout", "refused", "channel closed", "ssh session", "socket",
)


class ToolRetryMixin:
    """U11 retry guard methods. `_result_is_success` 由 ToolExecutor 提供。"""

    def _retryGateCheck(self, tool_name: str, params: Dict) -> Optional[Dict[str, Any]]:
        """U11 入口闸：同参指纹命中不可重试抑制（或在途变异调用）→ 结构化拒绝。"""
        from neurova.security.tool_metadata import executionFingerprint

        fingerprint = executionFingerprint(tool_name, params)
        now = time.monotonic()
        with self._retryLedgerLock:
            entry = self._retryLedger.get(fingerprint)
            if entry is None:
                return None
            if now > float(entry.get("expires") or 0.0):
                self._retryLedger.pop(fingerprint, None)
                return None
            if entry.get("state") == "running":
                # 同参调用仍在执行中：变异类工具拒绝并发重入（双执行隐患），
                # 只读工具放行（并发读安全）。
                if _toolIsMutation(tool_name) and not _toolIdempotentDeclared(tool_name):
                    return self._retrySuppressedResult(tool_name, {
                        "allowed": False, "failure_class": "in_flight",
                        "reason": "同参调用仍在执行中（变异类工具拒绝并发重入）",
                    })
                return None
            decision = entry.get("decision") or {}
            if decision.get("allowed", True) is False:
                return self._retrySuppressedResult(tool_name, decision)
            return None

    def _retryGateMarkRunning(self, tool_name: str, params: Dict) -> None:
        """登记在途（并发同参识别用）；已有抑制登记时此调用不会发生（先被闸拒绝）。"""
        from neurova.security.tool_metadata import executionFingerprint

        fingerprint = executionFingerprint(tool_name, params)
        with self._retryLedgerLock:
            entry = self._retryLedger.get(fingerprint)
            if entry is not None and entry.get("state") == "suppressed":
                return  # 抑制中的登记不被在途标记覆盖（闸已拦截，防御性兜底）
            self._retryLedger[fingerprint] = {
                "state": "running",
                "expires": time.monotonic() + _RETRY_INFLIGHT_TTL_S,
            }
            while len(self._retryLedger) > _RETRY_LEDGER_MAX:
                self._retryLedger.popitem(last=False)

    def _retryGateRecordOutcome(self, tool_name: str, params: Dict,
                                result: Optional[Dict], error: Optional[BaseException]) -> None:
        """按失败分级纪律落账：成功/可重试 → 清账；不可重试 → 抑制窗内拒绝同参重试。"""
        from neurova.security.tool_metadata import executionFingerprint

        fingerprint = executionFingerprint(tool_name, params)
        failed = error is not None or (
            isinstance(result, dict) and not self._result_is_success(result)
        )
        if not failed:
            with self._retryLedgerLock:
                self._retryLedger.pop(fingerprint, None)
            return
        decision = retryDecisionFor(
            tool_name, error=error, result=result if isinstance(result, dict) else None)
        if decision.get("allowed"):
            with self._retryLedgerLock:
                self._retryLedger.pop(fingerprint, None)
            return
        with self._retryLedgerLock:
            self._retryLedger[fingerprint] = {
                "state": "suppressed",
                "decision": decision,
                "expires": time.monotonic() + TOOL_RETRY_SUPPRESSION_WINDOW_S,
            }
            while len(self._retryLedger) > _RETRY_LEDGER_MAX:
                self._retryLedger.popitem(last=False)

    def _retryGateRecordAbort(self, tool_name: str, params: Dict) -> None:
        """执行被取消/超时中断：结果未知。变异类工具按"不可盲重试"抑制；
        只读工具清账（transport 级重试保留）。"""
        from neurova.security.tool_metadata import executionFingerprint

        fingerprint = executionFingerprint(tool_name, params)
        decision = retryDecisionFor(
            tool_name, result={"error": "执行被取消（超时/停止），结果未知", "executed": "unknown"})
        with self._retryLedgerLock:
            if decision.get("allowed"):
                self._retryLedger.pop(fingerprint, None)
                return
            self._retryLedger[fingerprint] = {
                "state": "suppressed",
                "decision": decision,
                "expires": time.monotonic() + TOOL_RETRY_SUPPRESSION_WINDOW_S,
            }
            while len(self._retryLedger) > _RETRY_LEDGER_MAX:
                self._retryLedger.popitem(last=False)

    @staticmethod
    def _retrySuppressedResult(tool_name: str, decision: Dict[str, Any]) -> Dict[str, Any]:
        """U11 稳定拒绝形状：同参重试被失败分级纪律拦下。"""
        return {
            "success": False,
            "error_code": TOOL_RETRY_SUPPRESSED_CODE,
            "retry": dict(decision),
            "error": (
                f"工具 {tool_name} 的上一次同参调用以"
                f"{decision.get('failure_class', '应用层')}失败告终，"
                "按失败分级重试纪律不自动重试；请修正参数或改用其他方法后再试"
            ),
        }


def classifyToolFailure(tool_name: str, error: Optional[BaseException] = None,
                        result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """U11 失败分级：transport（连接/会话层，可换连接重试）vs application（零重试）。

    判定顺序：
    1. 结果里的显式 `retryable` 键（U3 REMOTE_NOT_EXECUTED 契约）最优先——
       执行体自己声明过"能不能重试"，分类器不越权改口；
    2. 异常类型名命中 transport 特征 → transport；
    3. 错误文本命中 transport 标记 → transport；
    4. 其余一律 application（保守：默认不可重试）。
    """
    if isinstance(result, dict) and "retryable" in result:
        retryable = bool(result.get("retryable"))
        return {
            "failure_class": "transport" if retryable else "application",
            "retry_allowed": retryable,
            "reason": str(result.get("error") or "执行体显式声明 retryable"),
        }
    if isinstance(error, BaseException):
        if type(error).__name__ in _TRANSPORT_ERROR_TYPE_NAMES:
            return {"failure_class": "transport", "retry_allowed": True,
                    "reason": f"{type(error).__name__}: {error}"}
        text = str(error).lower()
        if any(marker in text for marker in _TRANSPORT_TEXT_MARKERS):
            return {"failure_class": "transport", "retry_allowed": True,
                    "reason": f"{type(error).__name__}: {error}"}
        return {"failure_class": "application", "retry_allowed": False,
                "reason": f"{type(error).__name__}: {error}"}
    errorText = ""
    if isinstance(result, dict):
        errorText = str(result.get("error") or "")
    lowered = errorText.lower()
    if any(marker in lowered for marker in _TRANSPORT_TEXT_MARKERS):
        return {"failure_class": "transport", "retry_allowed": True, "reason": errorText}
    return {"failure_class": "application", "retry_allowed": False,
            "reason": errorText or "应用层失败"}


def _toolIsMutation(tool_name: str) -> bool:
    """变异类判定：只读声明取不到 / readOnly=False 一律按变异（保守侧）。"""
    try:
        from neurova.agent.tool_coordinator import resolveToolCapability

        capability = resolveToolCapability(tool_name)
    except Exception:  # noqa: BLE001 - 能力面故障按保守侧（变异）处置
        return True
    if capability is None:
        return True
    return not bool(getattr(capability, "readOnly", False))


def _toolIdempotentDeclared(tool_name: str) -> bool:
    """schema runtime.idempotent 声明（U7 元数据的 U11 消费点）。"""
    try:
        from neurova.builtin_tools import get_builtin_tool_runtime

        runtime = get_builtin_tool_runtime(tool_name)
    except Exception:  # noqa: BLE001 - 取不到声明按未声明（不幂等）
        return False
    return bool(runtime and runtime.get("idempotent") is True)


def retryDecisionFor(tool_name: str, error: Optional[BaseException] = None,
                     result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """U11 重试裁决：失败分级 + 变异/幂等声明 → 是否允许重试。

    - 应用层失败：一律不重试；
    - transport 级失败：只读工具可换连接/会话重试；变异类工具未声明
      idempotent 时**默认不重试**（重复执行的副作用不可撤回）。
    """
    classification = classifyToolFailure(tool_name, error=error, result=result)
    if classification["failure_class"] != "transport":
        return {
            "allowed": False,
            "failure_class": classification["failure_class"],
            "reason": classification["reason"] or "应用层失败不重试",
        }
    if _toolIsMutation(tool_name) and not _toolIdempotentDeclared(tool_name):
        return {
            "allowed": False,
            "failure_class": "transport",
            "reason": (
                f"变异类工具 {tool_name} 未声明 idempotent，"
                f"transport 级失败也不自动重试（副作用不可撤回）：{classification['reason']}"
            ),
        }
    return {
        "allowed": True,
        "failure_class": "transport",
        "reason": classification["reason"] or "transport 级失败，可换连接/会话重试",
    }
