# -*- coding: utf-8 -*-
r"""WSL 崩溃转储回收：只清超过保留期的 `*.dmp`，并在计划任务里挂上这个入口。

为什么要它：WSL 的 `core_pattern=|/wsl-capture-crash` 会把每次 Linux 侧致命信号写成
`%LOCALAPPDATA%\Temp\wsl-crashes\wsl-crash-<时刻>-<pid>-<可执行体>-<信号>.dmp`，单个实测可达
1.4 GB。2026-09-05 那一轮留下 7 个共 2.18 GB，落在 C 盘只剩 4.6 GB 的当天下午——
崩溃产物本身在制造下一次崩溃。

为什么**不**清空：dump 是栈回溯的唯一载体。2026-10-08 清理 C 盘时把这批 dump 走了
不可回收删除，导致 33 天后定性根因时只能从会话日志反推。所以 `KEEP_DAYS` 之内一个都不动，
给"崩了 yet 还没人看"留出窗口；超期才收。

用法（仓库根）：
    .venv/Scripts/python.exe scripts/desktop/wsl_crash_cleanup.py --purge
    .venv/Scripts/python.exe scripts/desktop/wsl_crash_cleanup.py --install-task
    .venv/Scripts/python.exe scripts/desktop/wsl_crash_cleanup.py --uninstall-task
"""
from __future__ import annotations

import argparse
import datetime
import locale
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

THIS_FILE = Path(__file__).resolve()

# 保留期内不动。依据（2026-10-08）：9-05 那批 dump 在 Temp 里躺了 33 天无人取用，
# 却把 C 盘吃掉 2.18 GB；一周足够一个人发现并取走一次崩溃现场。
KEEP_DAYS = 7

DUMP_GLOB = "*.dmp"
TASK_NAME = "Neurova Wsl Crash Cleanup"


def dumpRoot() -> Path:
    """WSL 真正写 dump 的落点，从 `LOCALAPPDATA` 现推，不写死用户名。"""
    localAppData = os.environ.get("LOCALAPPDATA", "").strip()
    if not localAppData:
        raise RuntimeError("环境里没有 LOCALAPPDATA，取不到 WSL 崩溃转储落点")
    return Path(localAppData) / "Temp" / "wsl-crashes"


def purgeStaleDumps(root: Path, keepDays: float = KEEP_DAYS,
                   now: Optional[datetime.datetime] = None) -> List[Path]:
    """删掉 `root` 下 mtime 超过 `keepDays` 的 `*.dmp`，返回被删路径。

    目录不存在直接返回空——本机从没崩过是正常状态，不该为此报错，更不该顺手建目录。
    单个文件删不掉（被占用）只跳过并警告，不中断整轮。
    """
    root = Path(root)
    if not root.is_dir():
        return []
    reference = now or datetime.datetime.now()
    cutoff = reference - datetime.timedelta(days=keepDays)
    removed = []
    for f in sorted(root.glob(DUMP_GLOB)):
        try:
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime >= cutoff:
                continue
            f.unlink()
        except OSError as exc:
            import warnings
            warnings.warn("崩溃转储 {} 本轮删不掉：{}".format(f.name, exc), stacklevel=2)
            continue
        removed.append(f)
    return removed


def taskCommandLine() -> List[str]:
    """计划任务真正执行的命令——注册进去的就是这一串，判据盯它。"""
    return [sys.executable, str(THIS_FILE), "--purge"]


# `schtasks.exe` 是原生控制台件：它按**控制台码页**输出（本机 cp936），成功行还会回显任务名与
# 命令行——那条命令行里带着仓库路径中的「项目」二字。所以这两处显式按 locale 解码，
# **不要"顺手"改成 utf-8**：那会把中文换成 U+FFFD，看着像没报错、实际把回显读坏了。
# 显式写出来才是重点：默认值随父进程的 locale 变，换一台机器/换一套 ANSI 代码页就换一种读法。
def installTask() -> int:
    """按天调度当前用户任务；不需要管理员权限。"""
    tr = " ".join(taskCommandLine())
    result = subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "DAILY", "/ST", "09:30", "/TR", tr],
        capture_output=True, text=True, encoding=locale.getpreferredencoding(False))
    print((result.stdout + result.stderr).strip())
    return result.returncode


def uninstallTask() -> int:
    result = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                            capture_output=True, text=True,
                            encoding=locale.getpreferredencoding(False))
    print((result.stdout + result.stderr).strip())
    return result.returncode


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="回收超期的 WSL 崩溃转储（保留期内不动）")
    parser.add_argument("--purge", action="store_true", help="执行一轮回收（缺省动作）")
    parser.add_argument("--keep-days", type=float, default=KEEP_DAYS, dest="keepDays")
    parser.add_argument("--install-task", action="store_true", dest="installTask")
    parser.add_argument("--uninstall-task", action="store_true", dest="uninstallTask")
    args = parser.parse_args(argv)

    if args.installTask:
        return installTask()
    if args.uninstallTask:
        return uninstallTask()

    try:
        root = dumpRoot()
    except RuntimeError as exc:
        print("[wsl-crash-cleanup] {}".format(exc), file=sys.stderr)
        return 1

    removed = purgeStaleDumps(root, args.keepDays)
    detail = "（{}）".format(", ".join(r.name for r in removed[:3])) if removed else ""
    print("[wsl-crash-cleanup] {} 保留 {} 天，本轮回收 {} 个转储{}".format(
        root, args.keepDays, len(removed), detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
