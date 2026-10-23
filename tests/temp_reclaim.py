"""pytest 临时目录「锁主判活即回收」。

pytest 自己的回收把 `.lock` 的有效期定为 `LOCK_TIMEOUT = 60*60*24*3`：只要目录里
还留着锁，三天内每轮 GC 都跳过它。而被强杀的会话永远不会执行 `atexit`，锁必然残留
——所以"三天窗口内所有被杀会话的临时目录"会稳定叠在 TEMP 上。本模块把判据从
"锁还没过期"换成"锁主进程到底还在不在"，确证已死即回收。
"""

from __future__ import annotations

import functools
import getpass
import os
import re
import shutil
import stat
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any, Callable

_SESSION_DIR_PATTERN = re.compile(r"^pytest-(\d+)$")
_START_SKEW_SECONDS = 5.0


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    # 1970-01-01 对应的 FILETIME 值（自 1601-01-01 起的 100 纳秒间隔数）
    _UNIX_EPOCH_IN_FILETIME = 116444736000000000
    _FILETIME_UNIT = 1e7
    _FILETIME = ctypes.c_ulonglong
    _kernel32 = ctypes.windll.kernel32
    # 必须显式声明签名：默认 restype 是 c_int，且未声明 argtypes 时 int 参数按 32 位传，
    # 在 x64 上会把 64 位进程句柄截断成假句柄
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(_FILETIME)] * 4
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def processStartedAt(pid: int):
        """返回进程启动时间（epoch 秒）；进程不存在返回 None，取不到返回 0.0。"""
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            creation = ctypes.c_ulonglong()
            ignored = ctypes.c_ulonglong()
            queried = _kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(ignored),
                ctypes.byref(ignored), ctypes.byref(ignored),
            )
            if not queried:
                # 进程确实存在但查不到时间（例如权限受限）：按最保守的"活着"处理
                return 0.0
            return (creation.value - _UNIX_EPOCH_IN_FILETIME) / _FILETIME_UNIT
        finally:
            _kernel32.CloseHandle(handle)

elif sys.platform.startswith("linux"):

    def processStartedAt(pid: int):
        statPath = Path("/proc/{}".format(pid)) / "stat"
        try:
            statText = statPath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        # comm 字段可以含空格和括号，必须从最后一个 ')' 之后再切
        fields = statText[statText.rfind(")") + 1:].split()
        try:
            # fields[0] 是 state（第 3 个字段），starttime 是第 22 个
            startTimeTicks = int(fields[19])
            bootTime = _linuxBootTime()
        except (IndexError, ValueError):
            return 0.0
        return bootTime + startTimeTicks / os.sysconf("SC_CLK_TCK")

    def _linuxBootTime() -> float:
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
        raise ValueError("/proc/stat 缺少 btime")

else:
    # 其余 POSIX 平台没有免依赖的启动时间来源。取不到就按"活着"处理，
    # 代价只是这些平台上 pid 复用防误杀退化成"存在即保留"，仍由 pytest 原生回收兜底。
    def processStartedAt(pid: int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except OSError:
            return 0.0
        return 0.0


def holderIsDead(pid: int, lockMtime: float, *, probe) -> bool:
    """判断 `.lock` 的持有进程是否**确证**已死。

    probe(pid) 返回该进程的启动时间（epoch 秒），进程不存在时返回 None。
    光看"pid 还在"不够：pid 会被回收复用，必须再比一次启动时间——进程比锁还新，
    就说明它不是当初写锁的那个进程，锁是残留的。
    """
    startedAt = probe(pid)
    if startedAt is None:
        return True
    return startedAt > lockMtime + _START_SKEW_SECONDS


def sessionTempRoot() -> Path:
    """pytest 自建临时目录的根，与 pytest 侧 `pytest-of-<user>` 同口径。"""
    return Path(tempfile.gettempdir()) / "pytest-of-{}".format(getpass.getuser())


def _clearReadOnlyTree(root: Path) -> None:
    """清掉子树里的只读位——Windows 上 git 给 `objects/**` 加 0444，`rmtree` 即撞
    `[WinError 5] 拒绝访问`。

    为什么这不算放宽判据：授权来源始终是调用方已经确证过的 `holderIsDead`，
    这里解开的只是**文件属性**造成的"删不动"，而不是"不该删"。误删并发会话目录的风险
    由 `holderIsDead` 那道门负责，本函数不改变任何判定，也不碰判活结论为"还活着"的目录
    （那条分支根本不会走到这里）。单个条目清不动就跳过——剩下的由下一轮再试。
    """
    for dirpath, dirnames, filenames in os.walk(root):
        for name in list(dirnames) + list(filenames):
            target = Path(dirpath) / name
            try:
                if not os.access(target, os.W_OK):
                    os.chmod(target, stat.S_IWRITE)
            except OSError:
                continue


def reclaimDeadLockedDirs(tempRoot: Path, *, holderIsDead: Callable[[int, float], bool],
                          remove: Callable[[Path], Any] = shutil.rmtree) -> list:
    """回收 tempRoot 下锁主确证已死的 pytest 会话目录，返回被删目录列表。

    只处理 `pytest-<数字>` 形态且 `.lock` 能读出 pid 的目录；任何判据读不出来
    的情况都跳过——宁可留一个目录等 pytest 自己收，也不能误删并发会话正在写的目录。
    单个目录删不动（被占用）只跳过它并报警，不中断整轮清扫。
    """
    if not tempRoot.is_dir():
        return []
    removed = []
    for entry in sorted(tempRoot.iterdir()):
        if not _SESSION_DIR_PATTERN.match(entry.name) or not entry.is_dir():
            continue
        lock = entry / ".lock"
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
            lockMtime = lock.stat().st_mtime
        except (OSError, ValueError):
            continue
        if not holderIsDead(pid, lockMtime):
            continue
        try:
            remove(entry)
        except PermissionError:
            # 「删不动」有两种：一种是锁主还活着（上面已挡掉），一种只是 Windows 的只读位。
            # 后者不清掉就永久留存——实测本机 TEMP 下 10 个会话目录里 8 个因此躲过每一轮回收，
            # 每轮跑测都从本函数打出一条同样的警告。清完重试一次，仍失败才认输。
            _clearReadOnlyTree(entry)
            try:
                remove(entry)
            except OSError as retryExc:
                warnings.warn("回收 pytest 残留会话目录 {} 失败（已清只读位仍删不动），本轮跳过：{}"
                              .format(entry.name, retryExc), stacklevel=2)
                continue
            removed.append(entry)
            continue
        except OSError as exc:
            warnings.warn("回收 pytest 残留会话目录 {} 失败，本轮跳过：{}".format(entry.name, exc),
                          stacklevel=2)
            continue
        removed.append(entry)
    return removed


def pytest_sessionstart(session) -> None:
    """会话启动时清掉锁主已死的残留目录，替代 pytest 自己的三天锁免疫。"""
    if getattr(session.config.option, "basetemp", None):
        # 显式给了 --basetemp，pytest 会在启动时清空该目录，不在这套命名约定内
        return
    reclaimDeadLockedDirs(sessionTempRoot(),
                          holderIsDead=functools.partial(holderIsDead, probe=processStartedAt))
