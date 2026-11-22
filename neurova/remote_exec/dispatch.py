# -*- coding: utf-8 -*-
"""统一远程执行分派漏斗（W1b，计划见 docs/04-plans/2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md §4）。

所有远程形态（ssh/guest/tunnel/neuacp/mcp）的调用统一走本漏斗：
准入（形态白名单 + 能力声明复验）→ 执行体（调用方注入，避免本包反向依赖
tool_executor/computer_use/guest_agent/tunnel/neuacp）→ 统一结果信封
（executed/phase/retryable，U3 语义）→ 离线 hold（connect/timeout 且可重试时
在窗口内指数退避重试，端点标 offline；窗口耗尽返回「未执行、可安全重试」）
→ 生命周期事件（start/retry/result，供审计，不携带明文凭据）。

本函数为同步阻塞实现；async 语境由调用方自行 to_thread 包装。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple, Union

from neurova.core.logger import get_logger
from neurova.remote_exec.registry import (
    REMOTE_KINDS,
    RemoteEndpoint,
    getRemoteEndpointRegistry,
)

logger = get_logger(__name__)

#: 离线 hold 窗口的环境注入点（毫秒）；缺省 45s
HOLD_TIMEOUT_ENV = "NEUROVA_REMOTE_HOLD_MS"
DEFAULT_HOLD_TIMEOUT_MS = 45_000

_FIRST_RETRY_DELAY_S = 0.5
_RETRY_BACKOFF_FACTOR = 2.0
_RETRY_DELAY_CAP_S = 5.0

#: 触发离线 hold 的失败相位（U3：连接失败/超时且零输出，确认未执行）
_HOLD_PHASES = frozenset({"connect", "timeout"})

_PHASE_DISPATCH = "dispatch"
_PHASE_EXEC = "exec"


@dataclass
class RemoteDispatchResult:
    """统一结果信封（U3 语义）。

    executed: True（已执行）/ False（确认未执行）/ "unknown"（已获部分输出后
    中断，不可盲目重试）；holdAttempts/holdElapsedMs 为离线 hold 的实测重试
    次数与累计等待毫秒（未进入 hold 时为 0）。
    """

    ok: bool
    executed: Union[bool, str]
    phase: str
    retryable: bool
    endpointId: str
    kind: str
    output: Any = None
    error: Optional[str] = None
    holdAttempts: int = 0
    holdElapsedMs: int = 0


class RemoteDispatchError(Exception):
    """结构化准入拒绝（形态未知/能力缺失等；分派前拦截，不产生执行副作用）。"""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        retryable: bool = False,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.details = details or {}


def _isRemoteNotExecutedError(exc: BaseException) -> bool:
    """判定 U3 相位化异常；优先直接 import，导入失败退回类名+属性 duck 判定。"""
    if _looksLikeRemoteNotExecutedError(exc):
        return True
    try:
        from neurova.computer_use.ssh_runner import RemoteNotExecutedError
    except Exception:  # noqa: BLE001 - ssh_runner 不可导入时按 duck 判定兜住
        return False
    return isinstance(exc, RemoteNotExecutedError)


def _looksLikeRemoteNotExecutedError(exc: BaseException) -> bool:
    return (
        type(exc).__name__ == "RemoteNotExecutedError"
        and hasattr(exc, "phase")
        and hasattr(exc, "executed")
        and hasattr(exc, "retryable")
    )


def _isHoldEligible(exc: BaseException) -> bool:
    """connect/timeout 且可安全重试 → 进离线 hold；其余失败一律不 hold。"""
    if not _isRemoteNotExecutedError(exc):
        return False
    phase = getattr(exc, "phase", "")
    retryable = bool(getattr(exc, "retryable", False))
    return phase in _HOLD_PHASES and retryable


def _resolveHoldTimeoutMs(holdTimeoutMs: Optional[int]) -> int:
    if holdTimeoutMs is not None:
        return max(0, int(holdTimeoutMs))
    raw = (os.environ.get(HOLD_TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_HOLD_TIMEOUT_MS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "环境变量 %s 非整数（%r），按默认 %dms 处理",
            HOLD_TIMEOUT_ENV,
            raw,
            DEFAULT_HOLD_TIMEOUT_MS,
        )
        return DEFAULT_HOLD_TIMEOUT_MS


def _markEndpointSeenSafe(endpointId: str, health: str) -> None:
    """健康度回写容错：注册表故障只告警，不阻断分派结果（契约显式豁免点）。"""
    try:
        getRemoteEndpointRegistry().markEndpointSeen(endpointId, health)
    except Exception:  # noqa: BLE001 - 契约要求 registry 故障不阻断返回
        logger.warning(
            "remote endpoint 健康度回写失败（不阻断分派）: endpoint=%s health=%s",
            endpointId,
            health,
            exc_info=True,
        )


def _emit(
    onEvent: Optional[Callable[[str, dict], None]], eventName: str, payload: Dict[str, Any]
) -> None:
    if onEvent is not None:
        onEvent(eventName, payload)


def dispatchRemoteCall(
    *,
    toolName: str,
    params: dict,
    endpoint: RemoteEndpoint,
    executor: Callable[[dict], Any],
    requiredCapability: Optional[str] = None,
    holdTimeoutMs: Optional[int] = None,
    sleepFn: Callable[[float], None] = time.sleep,
    onEvent: Optional[Callable[[str, dict], None]] = None,
    transparentExceptions: Tuple[type, ...] = (),
) -> RemoteDispatchResult:
    """远程执行统一入口：准入 → 执行体 → 统一信封 → 离线 hold → 事件。

    executor(params) 由调用方注入形态执行体（ssh_runner/guest/tunnel/neuacp）；
    成功返回值原样透传进 result.output，本漏斗不改写。

    transparentExceptions：executor 抛出的异常若命中其中之一，则在发出
    remote_dispatch_result 事件后**原样重抛**（同一异常对象），交回调用方
    保留自有处理（如 SSH 支路的 U1 主机确认卡/指纹冲突 fail-closed）；
    命中者优先于离线 hold 判定。缺省空元组 = 既有行为逐字节不变。
    """
    startedAt = time.monotonic()
    baseEvent: Dict[str, Any] = {
        "toolName": toolName,
        "endpointId": endpoint.endpointId,
        "kind": endpoint.kind,
    }

    def _resultEvent(phase: str, ok: bool) -> Dict[str, Any]:
        return {
            **baseEvent,
            "phase": phase,
            "ok": ok,
            "elapsedMs": int((time.monotonic() - startedAt) * 1000),
        }

    def _finish(result: RemoteDispatchResult) -> RemoteDispatchResult:
        _emit(onEvent, "remote_dispatch_result", _resultEvent(result.phase, result.ok))
        return result

    _emit(onEvent, "remote_dispatch_start", dict(baseEvent))

    # ── 1) 准入：形态白名单 + 能力声明复验（拒绝发生在任何执行副作用之前） ──
    if endpoint.kind not in REMOTE_KINDS:
        _emit(onEvent, "remote_dispatch_result", _resultEvent(_PHASE_DISPATCH, False))
        raise RemoteDispatchError(
            f"未知远程执行形态: {endpoint.kind!r}（合法形态: {sorted(REMOTE_KINDS)}）",
            reason="unknown_kind",
        )
    if requiredCapability is not None and not endpoint.capabilities.get(requiredCapability):
        _emit(onEvent, "remote_dispatch_result", _resultEvent(_PHASE_DISPATCH, False))
        raise RemoteDispatchError(
            f"端点 {endpoint.endpointId} 缺少所需能力: {requiredCapability}",
            reason="capability_missing",
            details={"requiredCapability": requiredCapability},
        )

    holdTimeout = _resolveHoldTimeoutMs(holdTimeoutMs)
    holdAttempts = 0
    holdElapsedMs = 0
    delayS = _FIRST_RETRY_DELAY_S
    lastPhase = "connect"
    lastError = ""

    # ── 2)~5) 执行 + 失败分类（hold 重试 / 直接映射 / dispatch 失败） ──
    attemptIndex = 0
    while True:
        try:
            raw = executor(params)
        except Exception as exc:  # noqa: BLE001 - 分类后按语义映射，不吞
            if transparentExceptions and isinstance(exc, transparentExceptions):
                # 调用方保留自有处理的异常（如 U1 主机确认卡/指纹冲突）：
                # 发出结果事件后原样重抛（同一对象、原 traceback），不映射不吞。
                _emit(onEvent, "remote_dispatch_result", _resultEvent(
                    getattr(exc, "phase", _PHASE_EXEC), False))
                raise
            if _isHoldEligible(exc):
                lastPhase = getattr(exc, "phase", "connect")
                lastError = str(exc)
                if attemptIndex == 0:
                    # 首次进入离线 hold：端点标 offline（仅标一次）
                    _markEndpointSeenSafe(endpoint.endpointId, "offline")
                if holdElapsedMs >= holdTimeout:
                    # 窗口耗尽：诚实返回「未执行、可安全重试」
                    return _finish(
                        RemoteDispatchResult(
                            ok=False,
                            executed=False,
                            phase=lastPhase,
                            retryable=True,
                            endpointId=endpoint.endpointId,
                            kind=endpoint.kind,
                            error=(
                                f"远程端点在 {holdTimeout}ms 离线等待窗口内未恢复"
                                f"（重试 {holdAttempts} 次）：未执行、可安全重试。"
                                f"最后错误：{lastError}"
                            ),
                            holdAttempts=holdAttempts,
                            holdElapsedMs=holdElapsedMs,
                        )
                    )
                sleepS = min(delayS, (holdTimeout - holdElapsedMs) / 1000.0)
                sleepFn(sleepS)
                holdElapsedMs += int(round(sleepS * 1000))
                holdAttempts += 1
                _emit(
                    onEvent,
                    "remote_dispatch_retry",
                    {
                        **baseEvent,
                        "attempt": holdAttempts,
                        "delayMs": int(round(sleepS * 1000)),
                        "phase": lastPhase,
                        "error": lastError,
                    },
                )
                delayS = min(delayS * _RETRY_BACKOFF_FACTOR, _RETRY_DELAY_CAP_S)
                attemptIndex += 1
                continue
            if _isRemoteNotExecutedError(exc):
                # 其他相位（auth / executed="unknown" 等）：直接映射，不 hold 不重试
                return _finish(
                    RemoteDispatchResult(
                        ok=False,
                        executed=getattr(exc, "executed", False),
                        phase=getattr(exc, "phase", _PHASE_EXEC),
                        retryable=bool(getattr(exc, "retryable", False)),
                        endpointId=endpoint.endpointId,
                        kind=endpoint.kind,
                        error=str(exc),
                        holdAttempts=holdAttempts,
                        holdElapsedMs=holdElapsedMs,
                    )
                )
            # 未知异常：dispatch 相位失败，不标健康度、不重试
            return _finish(
                RemoteDispatchResult(
                    ok=False,
                    executed=False,
                    phase=_PHASE_DISPATCH,
                    retryable=False,
                    endpointId=endpoint.endpointId,
                    kind=endpoint.kind,
                    error=f"{type(exc).__name__}: {exc}",
                    holdAttempts=holdAttempts,
                    holdElapsedMs=holdElapsedMs,
                )
            )
        else:
            # ── 成功：endpoint 转 online（容错），原始返回透传 ──
            _markEndpointSeenSafe(endpoint.endpointId, "online")
            return _finish(
                RemoteDispatchResult(
                    ok=True,
                    executed=True,
                    phase=_PHASE_EXEC,
                    retryable=False,
                    endpointId=endpoint.endpointId,
                    kind=endpoint.kind,
                    output=raw,
                    holdAttempts=holdAttempts,
                    holdElapsedMs=holdElapsedMs,
                )
            )
