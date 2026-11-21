# -*- coding: utf-8 -*-
"""C3 红灯：terminateProcessGroup 进程组级回收。

活体判据：子进程孵化孙进程后，terminateProcessGroup 必须把子与孙一并
回收（治理孤儿进程）；另用 kill_impl 注入覆盖各平台分支与兜底路径
（平台不适用的分支 skipif）。
"""
import os
import subprocess
import sys
import time
from typing import Optional

import pytest

from neurova.agent.neuacp.process_governance import terminateProcessGroup

_SLEEP_CODE = "import time; time.sleep(300)"
# 子进程先孵化孙进程、把孙 pid 打到 stdout，再各自长睡——构成待回收的进程树
_CHILD_CODE = (
    "import subprocess, sys, time\n"
    f"child = subprocess.Popen([sys.executable, '-c', {_SLEEP_CODE!r}])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(300)\n"
)


def _pidAlive(pid: int) -> bool:
    """跨平台探测 pid 是否仍存活。"""
    if sys.platform == "win32":
        # tasklist 输出为系统本地编码（中文系统 GBK），数字为 ASCII；
        # 用 errors="replace" 容错解码，不因编码差异误判存活
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
        ).stdout.decode("utf-8", "replace")
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _waitPidDead(pid: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pidAlive(pid):
            return True
        time.sleep(0.1)
    return not _pidAlive(pid)


def _hardKillTree(pid: int) -> None:
    """测试兜底清理：防止断言失败残留长睡进程。"""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


class TestLiveProcessTree:
    def test_terminateProcessGroupKillsChildAndGrandchild(self):
        child = subprocess.Popen(
            [sys.executable, "-c", _CHILD_CODE],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        grand_pid = None
        try:
            grand_pid = int(child.stdout.readline().strip())
            assert child.poll() is None
            assert _pidAlive(grand_pid), "前置：孙进程应已孵化存活"

            outcome = terminateProcessGroup(child, 2.0)

            expected_mode = "taskkill" if sys.platform == "win32" else "killpg"
            assert outcome["mode"] == expected_mode
            assert child.poll() is not None, "子进程必须死（fail-closed）"
            # 孤儿治理核心判据：孙进程一并回收
            assert _waitPidDead(grand_pid), "孙进程必须被进程组级回收"
        finally:
            for pid in [child.pid] + ([grand_pid] if grand_pid else []):
                if _pidAlive(pid):
                    _hardKillTree(pid)
            if child.stdout:
                child.stdout.close()


class _FakeProcess:
    """轻量协作桩：记录 kill/wait 调用序列，验证 terminateProcessGroup 分支。"""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.kill_calls = 0
        self.wait_calls: list = []
        self.kill_raises: Optional[Exception] = None
        self.wait_times_out = False
        self._exited = False

    def poll(self):
        return 0 if self._exited else None

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.wait_times_out:
            raise subprocess.TimeoutExpired("fake", timeout)
        self._exited = True
        return 0

    def kill(self):
        self.kill_calls += 1
        if self.kill_raises is not None:
            raise self.kill_raises
        self._exited = True


class TestInjectedBranches:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows taskkill 分支")
    def test_windowsBranchUsesTaskkillTreeForce(self):
        proc = _FakeProcess()
        calls = []
        outcome = terminateProcessGroup(proc, 2.0, kill_impl=lambda pid, force: calls.append((pid, force)))
        assert calls == [(4242, True)]
        assert outcome == {"mode": "taskkill", "graceful": False}

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows 兜底分支")
    def test_windowsFallbackWhenTaskkillFails(self):
        proc = _FakeProcess()

        def denied(pid, force):
            raise OSError("taskkill denied")

        outcome = terminateProcessGroup(proc, 2.0, kill_impl=denied)
        assert proc.kill_calls == 1
        assert proc._exited
        assert outcome == {"mode": "fallback", "graceful": False}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX killpg 宽限分支")
    def test_posixGracefulWhenExitedWithinGrace(self):
        proc = _FakeProcess()
        calls = []
        outcome = terminateProcessGroup(proc, 2.0, kill_impl=lambda pid, force: calls.append((pid, force)))
        # 宽限内退出：只投温和信号，不升级
        assert calls == [(4242, False)]
        assert outcome == {"mode": "killpg", "graceful": True}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX killpg 升级分支")
    def test_posixEscalatesToForceAfterGrace(self):
        proc = _FakeProcess()
        proc.wait_times_out = True
        calls = []
        outcome = terminateProcessGroup(proc, 0.1, kill_impl=lambda pid, force: calls.append((pid, force)))
        # 先 SIGTERM 后升级 SIGKILL
        assert calls == [(4242, False), (4242, True)]
        assert outcome == {"mode": "killpg", "graceful": False}

    def test_fallbackToProcKillWhenGroupKillRaises(self):
        proc = _FakeProcess()

        def boom(pid, force):
            raise OSError("no such process group")

        outcome = terminateProcessGroup(proc, 2.0, kill_impl=boom)
        assert proc.kill_calls == 1
        assert outcome["mode"] == "fallback"
        assert outcome["graceful"] is False

    def test_alreadyExitedProcessIsNoop(self):
        proc = _FakeProcess()
        proc._exited = True
        calls = []
        outcome = terminateProcessGroup(proc, 2.0, kill_impl=lambda pid, force: calls.append(pid))
        assert calls == []
        assert proc.kill_calls == 0
        assert outcome["graceful"] is True

    def test_unkillableProcessRaisesHonestly(self):
        proc = _FakeProcess()
        proc.kill_raises = PermissionError("kill denied")

        def boom(pid, force):
            raise OSError("group kill failed")

        with pytest.raises(PermissionError):
            terminateProcessGroup(proc, 2.0, kill_impl=boom)
