# -*- coding: utf-8 -*-
"""受限令牌沙箱的句柄全路径回收（fullrepo 审计 2026-11-18 D 组）。

红灯依据：原实现只在成功路径关闭 pi.hProcess/hThread——超时路径
TerminateProcess 后直接 return（两个进程句柄每次超时都泄漏）；
_make_inheritable 中途失败时已建句柄也会泄漏。本测试用假 windll
驱动**真实 execute()**，按 CloseHandle 的实际调用断言「每条路径都
把句柄关干净」。
"""
import ctypes
from types import SimpleNamespace

from neurova.sandbox.restricted_token import RestrictedTokenSandbox

_TIMEOUT_STILL_ACTIVE = 0x102


class _FakeKernel32:
    def __init__(self):
        self.closed = []
        self.terminated = []
        self.wait_result = 0

    def CreateFileW(self, *args):
        # 建真文件：成功路径 execute 会读回管道内容
        from pathlib import Path
        Path(args[0]).write_bytes(b"")
        return 100

    def SetHandleInformation(self, *args):
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def CreateProcessAsUserW(self, *args):
        pi = args[10]._obj
        pi.hProcess = 1001
        pi.hThread = 1002
        return 1

    def WaitForSingleObject(self, handle, ms):
        return self.wait_result

    def TerminateProcess(self, handle, code):
        self.terminated.append(handle)
        return True

    def GetExitCodeProcess(self, handle, byref_code):
        byref_code._obj.value = 0
        return True


class _FakeAdvapi32:
    def __init__(self, create_ok: bool):
        self.create_ok = create_ok

    def SaferCreateLevel(self, *args):
        args[3]._obj.value = 7
        return True

    def SaferComputeTokenFromLevel(self, *args):
        args[2]._obj.value = 42
        return True

    def SaferCloseLevel(self, *args):
        return True

    def CreateProcessAsUserW(self, *args):
        if not self.create_ok:
            return 0
        pi = args[10]._obj
        pi.hProcess = 1001
        pi.hThread = 1002
        return 1


def _install(monkeypatch, create_ok: bool = True):
    k32 = _FakeKernel32()
    adv = _FakeAdvapi32(create_ok)
    monkeypatch.setattr(ctypes, "windll",
                        SimpleNamespace(kernel32=k32, advapi32=adv), raising=False)
    return k32


def _sandbox():
    return RestrictedTokenSandbox()


class TestRestrictedTokenHandleRecovery:
    def test_timeout_path_closes_process_and_thread_handles(self, monkeypatch):
        k32 = _install(monkeypatch)
        k32.wait_result = _TIMEOUT_STILL_ACTIVE
        out = _sandbox().execute("calc.exe", timeout=0.01)
        assert out["success"] is False
        assert 1001 in k32.closed, "超时路径泄漏 pi.hProcess"
        assert 1002 in k32.closed, "超时路径泄漏 pi.hThread"
        assert 42 in k32.closed, "超时路径泄漏受限令牌句柄"

    def test_create_failure_closes_token_and_pipe_handles(self, monkeypatch):
        k32 = _install(monkeypatch, create_ok=False)
        out = _sandbox().execute("calc.exe")
        assert out["success"] is False
        assert 42 in k32.closed, "创建失败路径泄漏受限令牌句柄"
        assert 100 in k32.closed, "创建失败路径泄漏输出管道句柄"

    def test_success_path_closes_everything(self, monkeypatch):
        k32 = _install(monkeypatch)
        out = _sandbox().execute("calc.exe")
        assert out["success"] is True
        for handle in (42, 100, 1001, 1002):
            assert handle in k32.closed, f"成功路径泄漏句柄 {handle}"
