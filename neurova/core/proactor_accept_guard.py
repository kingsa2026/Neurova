"""Proactor accept 守护：瞬时 accept 失败（WinError 64/995）自动重挂监听。

缺陷（2026-10-06 实测，logs/server.log:5966-5983）：CPython 的
`BaseProactorEventLoop._start_serving` 对 accept 上的一切 OSError 统一处置为
"记录异常并关闭监听套接字"（proactor_events.py:864-871）。Windows 上客户端
在 accept 完成的瞬间异常断开（RST 打进 AcceptEx 窗口）时，overlapped accept
以 WinError 64（ERROR_NETNAME_DELETED）失败——一次客户端中断即永久拆掉监听：
进程存活、日志静默，但拒绝一切新连接。WinError 995（ERROR_OPERATION_ABORTED）
同属瞬时类。

守护在 `IocpProactor.accept` 返回的 future 外链一层：瞬时失败不外泄、按退避
重挂；其余错误与取消语义原样透传，`_start_serving` 的原生处置保持不变。
"""

import logging
import sys

logger = logging.getLogger(__name__)

# ERROR_NETNAME_DELETED：客户端在 accept 完成瞬间 RST（2026-10-06 实测命中）。
# ERROR_OPERATION_ABORTED：overlapped 操作被系统中止，重挂即可。
_TRANSIENT_ACCEPT_WINERRORS = frozenset({64, 995})

_REARM_BASE_DELAY_SECONDS = 0.05
_REARM_MAX_DELAY_SECONDS = 1.0

_INSTALLED = False


def isTransientAcceptError(exc):
    """判据：该 accept 异常是否属于"重挂即可"的瞬时类。"""
    return getattr(exc, "winerror", None) in _TRANSIENT_ACCEPT_WINERRORS


def acceptWithRetry(acceptFn, proactor, listener):
    """包一层 accept：瞬时失败按退避重挂，其余语义（成功/取消/其他错误）原样透传。

    acceptFn(proactor, listener) -> Future[(conn, addr)]，即 IocpProactor.accept
    的原形态。返回的外层 future 只在"最终结果"上落定：瞬时失败在其内部消化。
    """
    loop = proactor._loop
    outer = loop.create_future()
    state = {"inner": None, "consecutiveFailures": 0}

    def arm():
        if outer.done() or loop.is_closed():
            return
        try:
            inner = acceptFn(proactor, listener)
        except (OSError, RuntimeError) as exc:
            # 挂 accept 本身失败（Proactor 已关/监听口失效）→ 上抛，
            # 由 _start_serving 走原生处置；此处不吞、不重试。
            if not outer.done():
                outer.set_exception(exc)
            return
        state["inner"] = inner
        inner.add_done_callback(onInnerDone)

    def onInnerDone(inner):
        if outer.done():
            return
        if inner.cancelled():
            outer.cancel()
            return
        exc = inner.exception()
        if exc is None:
            state["consecutiveFailures"] = 0
            outer.set_result(inner.result())
            return
        if isTransientAcceptError(exc) and not loop.is_closed():
            state["consecutiveFailures"] += 1
            failures = state["consecutiveFailures"]
            delay = min(
                _REARM_BASE_DELAY_SECONDS * 2 ** (failures - 1),
                _REARM_MAX_DELAY_SECONDS,
            )
            logger.warning(
                "accept 瞬时失败（WinError %s，连续第 %d 次），%.2fs 后重挂监听: %s",
                exc.winerror,
                failures,
                delay,
                exc,
            )
            loop.call_later(delay, arm)
            return
        outer.set_exception(exc)

    def onOuterDone(_):
        # 循环关停（_stop_accept_futures）取消外层时，同步取消内层未决 accept，
        # 让 IocpProactor 的 accept_coro 走 CancelledError 分支收掉 conn。
        inner = state["inner"]
        if outer.cancelled() and inner is not None and not inner.done():
            inner.cancel()

    outer.add_done_callback(onOuterDone)
    arm()
    return outer


def installProactorAcceptGuard():
    """把 accept 守护装到 IocpProactor.accept 上（幂等；非 Windows 无操作）。"""
    global _INSTALLED
    if sys.platform != "win32":
        return False
    if _INSTALLED:
        return True
    try:
        from asyncio import windows_events

        originalAccept = windows_events.IocpProactor.accept

        def guardedAccept(self, listener):
            return acceptWithRetry(originalAccept, self, listener)

        windows_events.IocpProactor.accept = guardedAccept
        _INSTALLED = True
        logger.info(
            "Proactor accept 守护已安装：WinError %s 视为瞬时错误，自动重挂监听",
            sorted(_TRANSIENT_ACCEPT_WINERRORS),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - 守护装配失败不阻断启动，保留原生行为
        logger.warning("Proactor accept 守护安装失败（保留原生行为）: %s", exc)
        return False
