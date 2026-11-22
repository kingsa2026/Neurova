# -*- coding: utf-8 -*-
"""进程树清算器（U10）：按树收割，不留孙进程孤儿。

背景：池/执行体的既有清算走逐 pid terminate，子进程再孵化的孙进程会
成为孤儿继续占用资源。本模块是全仓"按树清算"的单一事实源：

- Windows：PowerShell CIM（Win32_Process）快照构建 pid→ppid 映射，
  自根 BFS 收集全部后代，``taskkill /F /PID …`` 按 20/批批量击杀，
  杀后复查快照逐 pid 判生死（含清算窗口期新孵化的树内后代）；
- POSIX：优先 ``os.killpg``（要求根进程自立进程组——生产侧 spawn 须
  ``start_new_session=True``，见 acp_client 前置）；不成组则退化逐 pid
  ``SIGTERM → 宽限 → SIGKILL``；
- 失败诚实上报：逐 pid 返回 :class:`PerProcessResult`，不吞异常、
  不把失败改写成成功；目标已退出视作达成（幂等，detail 注明）。

安全护栏：拒绝清算当前进程自身与非法 pid。
"""
from __future__ import annotations

import csv
import io
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "PerProcessResult",
    "TASKKILL_BATCH",
    "reap_tree",
    "kill_tree",
    "signalGroup",
    "collectTree",
    "parseProcessMap",
    "winProcessMap",
]

#: Windows 批量 taskkill 的单批 pid 上限（U10 形态：20/批）。
TASKKILL_BATCH = 20

#: CIM 快照 / taskkill 子进程超时（秒）。
_SNAPSHOT_TIMEOUT_S = 20.0
_TASKKILL_TIMEOUT_S = 20.0

#: POSIX 宽限轮询间隔（秒）。
_GRACE_POLL_INTERVAL_S = 0.05

#: 信号常量平台安全取法：SIGKILL 仅 POSIX 存在；Windows 逻辑单测/静态引用
#: 走同值回退（POSIX 运行时取到的仍是真 SIGKILL）。
_SIGTERM = getattr(signal, "SIGTERM", 15)
_SIGKILL = getattr(signal, "SIGKILL", 9)


@dataclass(frozen=True)
class PerProcessResult:
    """单个进程的清算结果（诚实上报，不吞异常）。"""

    pid: int
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        state = "ok" if self.ok else "FAILED"
        return f"pid={self.pid} {state}" + (f" ({self.detail})" if self.detail else "")


# ---------- Windows：CIM 快照 + BFS + 批量 taskkill ----------

#: Win32_Process 快照单源：PowerShell CIM（tasklist 无父 pid 列，建不了树）。
#: pid/ppid 均为 ASCII 数字，输出按 utf-8 容错解码不影响解析。
_POWERSHELL_SNAPSHOT_COMMAND = (
    "powershell", "-NoProfile", "-NonInteractive", "-Command",
    "Get-CimInstance Win32_Process "
    "| Select-Object ProcessId,ParentProcessId "
    "| ConvertTo-Csv -NoTypeInformation",
)


def _runCapture(command: Sequence[str], timeoutS: float) -> str:
    """跑一条捕获型命令；非零退出诚实抛 OSError（不吞）。"""
    completed = subprocess.run(list(command), capture_output=True, timeout=timeoutS)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace").strip()
        raise OSError(f"命令失败 ({command[0]}): {detail}")
    return completed.stdout.decode("utf-8", "replace")


def parseProcessMap(csvText: str) -> Dict[int, int]:
    """CIM CSV 文本 → ``{pid: ppid}``；非数字行跳过（解析容错不掩盖结构）。"""
    mapping: Dict[int, int] = {}
    for row in csv.DictReader(io.StringIO(csvText)):
        try:
            pid = int(str(row.get("ProcessId") or "").strip())
            ppid = int(str(row.get("ParentProcessId") or "").strip())
        except (TypeError, ValueError):
            continue
        mapping[pid] = ppid
    return mapping


def winProcessMap() -> Dict[int, int]:
    """Windows 全量 pid→ppid 快照（PowerShell CIM 单源）。"""
    return parseProcessMap(_runCapture(_POWERSHELL_SNAPSHOT_COMMAND, _SNAPSHOT_TIMEOUT_S))


def collectTree(root: int, parentMap: Dict[int, int]) -> List[int]:
    """自根 BFS 收集整棵树（根优先、逐层后代）；根不在快照时返回 ``[root]``。

    seen 去重：pid 复用的极端情形下保证有界收敛。
    """
    children: Dict[int, List[int]] = {}
    for pid, ppid in parentMap.items():
        children.setdefault(ppid, []).append(pid)
    order: List[int] = []
    queue: List[int] = [root]
    seen = {root}
    while queue:
        current = queue.pop(0)
        order.append(current)
        for child in children.get(current, ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return order


def _taskkillBatch(pids: Sequence[int]) -> Tuple[bool, str]:
    """一批 ``taskkill /F /PID …``（≤TASKKILL_BATCH 个）；返回 (是否受理, 系统输出)。

    注意：批内部分失败时 taskkill 也返回非零，但能杀的已杀——成败以
    杀后复查快照为准，这里的返回只作 detail 证据。
    """
    command = ["taskkill", "/F"]
    for pid in pids:
        command += ["/PID", str(pid)]
    completed = subprocess.run(command, capture_output=True, timeout=_TASKKILL_TIMEOUT_S)
    detail = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace").strip()
    return completed.returncode == 0, detail


def _ancestorInTree(pid: int, parentMap: Dict[int, int], treeSet) -> bool:
    """pid 的父链（沿快照 ppid 上溯，有界）是否落在树集合内。"""
    cursor = pid
    for _ in range(64):
        cursor = parentMap.get(cursor)
        if cursor is None:
            return False
        if cursor in treeSet:
            return True
    return False


def _reapWindows(root: int, batch_size: int = TASKKILL_BATCH) -> List[PerProcessResult]:
    """Windows 树清算：CIM 快照建树 → BFS → 批量 taskkill /F → 杀后复查。"""
    try:
        parentMap = winProcessMap()
    except Exception as exc:  # noqa: BLE001 - 快照失败无法建树，诚实失败交调用方降级
        return [PerProcessResult(root, False, f"进程快照查询失败: {exc}")]
    if root not in parentMap:
        return [PerProcessResult(root, True, "进程已退出（快照无此 pid）")]
    tree = collectTree(root, parentMap)
    treeSet = set(tree)
    batchErrors: Dict[int, str] = {}
    batch = max(1, int(batch_size))
    for index in range(0, len(tree), batch):
        chunk = tree[index:index + batch]
        try:
            accepted, detail = _taskkillBatch(chunk)
        except Exception as exc:  # noqa: BLE001 - taskkill 本身失败（超时等）逐 pid 记账
            for pid in chunk:
                batchErrors[pid] = f"taskkill 执行失败: {exc}"
            continue
        if not accepted:
            for pid in chunk:
                batchErrors[pid] = detail or "taskkill 返回非零"
    # 杀后复查：不在快照 = 已死（成功）；仍在 = 失败（带 taskkill 证据）
    try:
        afterMap = winProcessMap()
        verifyError: Optional[str] = None
    except Exception as exc:  # noqa: BLE001 - 复查失败按批结果诚实上报，不宣称成功
        afterMap, verifyError = None, str(exc)
    results: List[PerProcessResult] = []
    for pid in tree:
        if afterMap is None:
            ok = pid not in batchErrors
            results.append(PerProcessResult(pid, ok, "" if ok else batchErrors[pid]))
        elif pid in afterMap:
            results.append(PerProcessResult(
                pid, False, batchErrors.get(pid) or "taskkill 后仍存活"))
        else:
            results.append(PerProcessResult(pid, True, ""))
    if afterMap is not None:
        for pid in afterMap:
            if pid not in treeSet and _ancestorInTree(pid, afterMap, treeSet):
                results.append(PerProcessResult(
                    pid, False, "清算窗口期新孵化的树内后代仍存活"))
    elif verifyError:
        results.append(PerProcessResult(root, False, f"杀后复查快照失败: {verifyError}"))
    return results


# ---------- POSIX：killpg 优先 / 退化逐 pid SIGTERM→宽限→SIGKILL ----------


def _signalGroup(pgid: int, sig: int) -> None:
    """全仓唯一的 ``os.killpg`` 真调用点（U10 后进程组信号单一事实源）。

    其他模块需要进程组信号一律经 :func:`signalGroup` / :func:`kill_tree`
    委托，不得自带第二份 ``os.killpg``（守卫：
    tests/unit/tools/test_tool_cancellation.py::testProcessGroupKillHasOneSite）。
    """
    os.killpg(pgid, sig)


def signalGroup(pgid: int, sig: int) -> None:
    """对外委托口：跨模块的进程组信号统一走这里（异常诚实上抛）。"""
    _signalGroup(pgid, sig)


def _posixTreePids(root: int) -> List[int]:
    """POSIX 树收集：psutil 递归后代；不可用/无权限时退化为仅根（诚实降级）。"""
    try:
        import psutil
    except ImportError:
        return [root]
    try:
        parent = psutil.Process(root)
        return [parent.pid] + [child.pid for child in parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return [root]
    except psutil.AccessDenied:
        return [root]


def _posixAlive(pid: int) -> bool:
    """POSIX 存活探测（signal 0）；仅 POSIX 运行时被调。"""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权发信号
    except OSError:
        return True


def _reapPosix(root: int, grace_seconds: float = 5.0) -> List[PerProcessResult]:
    """POSIX 树清算：根自立进程组则 killpg，否则退化逐 pid 信号升级。"""
    pids = _posixTreePids(root)
    grace = max(0.0, float(grace_seconds))
    try:
        pgid = os.getpgid(root)
    except Exception:  # noqa: BLE001 - 取组失败按不成组退化
        pgid = None
    useGroup = pgid is not None and pgid == root
    sigtermErrors: Dict[int, str] = {}
    if useGroup:
        try:
            _signalGroup(pgid, _SIGTERM)
        except ProcessLookupError:
            pass  # 组已消亡 → 目标达成
        except Exception:  # noqa: BLE001 - 组级失败退化逐 pid
            useGroup = False
    if not useGroup:
        for pid in pids:
            try:
                os.kill(pid, _SIGTERM)
            except ProcessLookupError:
                continue
            except Exception as exc:  # noqa: BLE001 - 逐 pid 诚实记账，不中断全树
                sigtermErrors[pid] = f"SIGTERM 失败: {exc}"
    # 宽限轮询：全部退出即收口
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if all(not _posixAlive(pid) for pid in pids):
            return [PerProcessResult(pid, pid not in sigtermErrors,
                                     "" if pid not in sigtermErrors else sigtermErrors[pid])
                    for pid in pids]
        time.sleep(_GRACE_POLL_INTERVAL_S)
    # 宽限超时 → 升级 SIGKILL（组在则组杀，否则逐 pid）
    results: List[PerProcessResult] = []
    if useGroup:
        try:
            _signalGroup(pgid, _SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001 - 组杀失败退化逐 pid
            useGroup = False
    for pid in pids:
        if not useGroup and _posixAlive(pid):
            try:
                os.kill(pid, _SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:  # noqa: BLE001
                results.append(PerProcessResult(pid, False, f"SIGKILL 失败: {exc}"))
                continue
        if pid in sigtermErrors:
            results.append(PerProcessResult(pid, False, sigtermErrors[pid]))
        else:
            results.append(PerProcessResult(pid, True, "宽限超时升级 SIGKILL"))
    return results


# ---------- 统一入口 ----------


def reap_tree(pid: int, grace_seconds: float = 5.0, *,
              batch_size: int = TASKKILL_BATCH) -> List[PerProcessResult]:
    """按树清算：Windows CIM BFS + 批量 taskkill；POSIX killpg/逐 pid 降级。

    返回逐 pid 的 :class:`PerProcessResult`；目标已退出视作达成（幂等）。
    不吞异常：系统级失败以 ok=False + detail 诚实上报，由调用方决定降级。
    """
    pid = int(pid)
    if pid <= 0:
        return [PerProcessResult(pid, False, f"非法 pid: {pid}")]
    if pid == os.getpid():
        return [PerProcessResult(pid, False, "拒绝清算当前进程自身")]
    if sys.platform == "win32":
        return _reapWindows(pid, batch_size=max(1, int(batch_size)))
    return _reapPosix(pid, grace_seconds)


def kill_tree(pid: int, grace_seconds: float = 5.0) -> List[PerProcessResult]:
    """统一入口：平台自动选择（Windows taskkill 批杀 / POSIX 信号降级）。"""
    return reap_tree(pid, grace_seconds=grace_seconds)
