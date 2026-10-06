"""Proactor accept 守护（neurova.core.proactor_accept_guard）测试。

背景缺陷（2026-10-06 实测，logs/server.log:5966-5983）：CPython 的
`BaseProactorEventLoop._start_serving` 对 accept 上的一切 OSError 统一处置为
"记录异常并关闭监听套接字"（proactor_events.py:864-871）。Windows 上客户端
在 accept 完成的瞬间异常断开（RST 打进 AcceptEx 窗口）时，overlapped accept
以 WinError 64（ERROR_NETNAME_DELETED）失败——一次客户端中断即永久拆掉监听：
进程存活但拒绝一切新连接。WinError 995（ERROR_OPERATION_ABORTED）同属瞬时类。

判据：WinError 64/995 视为瞬时错误自动重挂 accept 且监听保持打开；
其余错误原样上抛（`_start_serving` 的原生关听处置保持不变）。
"""

import asyncio
import errno
import os
import socket

import pytest

win32Only = pytest.mark.skipif(os.name != "nt", reason="Proactor/IOCP 仅 Windows 存在")

_PENDING = object()


def _transientOSError(winerror):
    """构造携带 winerror 的 OSError（与 Windows 真实 accept 失败同构）。"""
    err = OSError(winerror, "注入的瞬时 accept 失败", None, winerror, None)
    if getattr(err, "winerror", None) != winerror:
        err.winerror = winerror
    return err


class _ScriptedProactor:
    """鸭子类型 IocpProactor：accept 结果按脚本出牌，判据确定性驱动。"""

    def __init__(self, loop):
        self._loop = loop
        self.acceptCalls = 0
        self.lastFuture = None
        self._script = []

    def scriptFailure(self, exc):
        self._script.append(exc)

    def scriptConnection(self, conn, addr):
        self._script.append((conn, addr))

    def scriptPending(self):
        self._script.append(_PENDING)

    def accept(self, listener):
        self.acceptCalls += 1
        fut = self._loop.create_future()
        self.lastFuture = fut
        outcome = self._script.pop(0)
        if outcome is _PENDING:
            pass
        elif isinstance(outcome, BaseException):
            fut.set_exception(outcome)
        else:
            fut.set_result(outcome)
        return fut


def _makeListener():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener


@win32Only
def testUnpatchedStartServingClosesListenerOnTransientAcceptError():
    """缺陷钉子：原生 _start_serving 对 accept OSError 一律关监听（守护的存在前提）。"""
    loop = asyncio.ProactorEventLoop()
    listener = _makeListener()
    realProactor = loop._proactor
    captured = []
    scripted = _ScriptedProactor(loop)
    scripted.scriptFailure(_transientOSError(64))
    try:
        loop.call_exception_handler = captured.append
        loop._proactor = scripted
        loop._start_serving(lambda: None, listener)
        loop.run_until_complete(asyncio.sleep(0.1))
    finally:
        loop._proactor = realProactor
        loop.close()
        listener.close()

    assert any(ctx.get("message") == "Accept failed on a socket" for ctx in captured)
    assert listener.fileno() == -1


def testTransientAcceptErrorBoundaries():
    from neurova.core.proactor_accept_guard import isTransientAcceptError

    assert isTransientAcceptError(_transientOSError(64))
    assert isTransientAcceptError(_transientOSError(995))
    assert not isTransientAcceptError(OSError(errno.EBADF, "bad listener fd"))
    assert not isTransientAcceptError(RuntimeError("IocpProactor is closed"))


@win32Only
def testTransientAcceptErrorIsRearmedNotSurfaced():
    """WinError 64/995 必须重挂 accept 且监听保持打开（本守护的核心判据）。"""
    from neurova.core.proactor_accept_guard import acceptWithRetry

    loop = asyncio.ProactorEventLoop()
    listener = _makeListener()
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    addr = ("127.0.0.1", 40000)
    scripted = _ScriptedProactor(loop)
    scripted.scriptFailure(_transientOSError(64))
    scripted.scriptFailure(_transientOSError(995))
    scripted.scriptConnection(conn, addr)
    try:

        async def drive():
            outer = acceptWithRetry(lambda p, l: p.accept(l), scripted, listener)
            return await asyncio.wait_for(outer, timeout=5.0)

        acceptedConn, acceptedAddr = loop.run_until_complete(drive())
        assert scripted.acceptCalls == 3
        assert listener.fileno() != -1
    finally:
        loop.close()
        listener.close()
        conn.close()

    assert acceptedConn is conn
    assert acceptedAddr == addr


@win32Only
def testNonTransientAcceptErrorSurfacesForOriginalCloseHandling():
    """非瞬时错误必须原样上抛——关听与否是 _start_serving 的原生职责，守护不越权。"""
    from neurova.core.proactor_accept_guard import acceptWithRetry

    loop = asyncio.ProactorEventLoop()
    listener = _makeListener()
    scripted = _ScriptedProactor(loop)
    scripted.scriptFailure(OSError(errno.EBADF, "bad listener fd"))
    try:

        async def drive():
            return await acceptWithRetry(lambda p, l: p.accept(l), scripted, listener)

        with pytest.raises(OSError):
            loop.run_until_complete(drive())
        assert scripted.acceptCalls == 1
        assert listener.fileno() != -1
    finally:
        loop.close()
        listener.close()


@win32Only
def testOuterCancellationPropagatesToPendingInnerAccept():
    """事件循环关停（_stop_accept_futures）取消外层 future 时，内层 accept 必须被取消。"""
    from neurova.core.proactor_accept_guard import acceptWithRetry

    loop = asyncio.ProactorEventLoop()
    listener = _makeListener()
    scripted = _ScriptedProactor(loop)
    scripted.scriptPending()
    try:

        async def drive():
            outer = acceptWithRetry(lambda p, l: p.accept(l), scripted, listener)
            await asyncio.sleep(0.05)
            assert not outer.done()
            outer.cancel()
            await asyncio.sleep(0.05)
            assert outer.cancelled()

        loop.run_until_complete(drive())
    finally:
        loop.close()
        listener.close()

    assert scripted.lastFuture.cancelled()


@win32Only
def testInstallKeepsRealProactorAcceptWorkingEndToEnd():
    """安装守护后，真 Proactor + 真监听 + 真客户端连接的 accept 成功路径不受影响。"""
    from neurova.core.proactor_accept_guard import installProactorAcceptGuard

    assert installProactorAcceptGuard() is True
    assert installProactorAcceptGuard() is True

    async def drive():
        async def echo(reader, writer):
            data = await reader.readexactly(4)
            writer.write(data)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"ping")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.readexactly(4), timeout=5.0)
            writer.close()
            await asyncio.sleep(0)
            return echoed
        finally:
            server.close()
            await server.wait_closed()

    loop = asyncio.ProactorEventLoop()
    try:
        assert loop.run_until_complete(drive()) == b"ping"
    finally:
        loop.close()
