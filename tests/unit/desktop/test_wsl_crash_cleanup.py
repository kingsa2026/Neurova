# -*- coding: utf-8 -*-
r"""WSL 崩溃转储回收判据：切断"崩溃转储反过来吃满系统盘"的正反馈。

为什么要有这条（2026-10-08 取证）：WSL 的 `core_pattern=|/wsl-capture-crash` 把每次
Linux 侧致命信号写成 `%LOCALAPPDATA%\Temp\wsl-crashes\*.dmp`，单个可达 1.4 GB。
2026-09-05 那一轮留下 7 个、共 2.18 GB，在 C 盘已经只剩 4.6 GB 的当天下午继续吃 C 盘——
**崩溃的产物本身成了下一次崩溃的成因**。

但要留一个反直觉的约束：**不能清空**。新鲜的 dump 是唯一的栈回溯载体。同一天我自己
清理时把这些 dump 删进了不可回收的删除，导致 33 天后定性根因时只能从会话日志反推，
栈信息永久丢失。所以判据按"龄期"而非"存在"下手：保留期内一个都不动，超期才回收。
"""

import datetime
import importlib.util
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_MODULE = _REPO / "scripts" / "desktop" / "wsl_crash_cleanup.py"


def _load():
    spec = importlib.util.spec_from_file_location("wsl_crash_cleanup", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plant(directory: Path, name: str, ageDays: float, content: bytes = b"x") -> Path:
    f = directory / name
    f.write_bytes(content)
    stamp = (datetime.datetime.now() - datetime.timedelta(days=ageDays)).timestamp()
    os.utime(f, (stamp, stamp))
    return f


def test_purgeKeepsDumpsInsideTheRetentionWindow(tmp_path):
    """保留期内的 dump 一个都不许动——那正是还能用来定根因的窗口。"""
    mod = _load()
    recent = _plant(tmp_path, "wsl-crash-1788605216-1637-_bin_rustc-7.dmp", ageDays=1)
    edge = _plant(tmp_path, "wsl-crash-edge.dmp", ageDays=mod.KEEP_DAYS - 1)

    removed = mod.purgeStaleDumps(tmp_path)

    assert removed == []
    assert recent.exists() and edge.exists()


def test_purgeRemovesOnlyExpiredDumps(tmp_path):
    """超期即回收；同目录里非 dump 的东西不归它管。"""
    mod = _load()
    expired = _plant(tmp_path, "wsl-crash-old.dmp", ageDays=mod.KEEP_DAYS + 5)
    stillGood = _plant(tmp_path, "notes.txt", ageDays=mod.KEEP_DAYS + 5)

    removed = mod.purgeStaleDumps(tmp_path)

    assert removed == [expired]
    assert not expired.exists()
    assert stillGood.exists(), "只该收 *.dmp，别的文件不由本闸处置"


def test_purgeIsQuietWhenTheDirectoryDoesNotExist(tmp_path):
    """本机从没崩过是正常状态，不是错误——不许为此报错或建目录。"""
    mod = _load()
    absent = tmp_path / "wsl-crashes"

    assert mod.purgeStaleDumps(absent) == []
    assert not absent.exists()


def test_dumpRootIsDerivedFromTheRealLocalAppData(tmp_path, monkeypatch):
    """落点必须是 WSL 真正写 dump 的那处，写错目录等于装了个空转的闸。"""
    mod = _load()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    root = mod.dumpRoot()

    assert root == tmp_path / "Temp" / "wsl-crashes"


def test_taskRegistrationCommandIsThePurgeItself():
    """计划任务必须调本模块的清理入口，且带一个明确的保留期口径。"""
    mod = _load()
    argv = mod.taskCommandLine()

    joined = " ".join(argv)
    assert "wsl_crash_cleanup.py" in joined
    assert "--purge" in joined, "任务参数没指向清理动作，注册了也不会清"
