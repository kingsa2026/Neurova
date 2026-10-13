# -*- coding: utf-8 -*-
r"""构建前磁盘余量闸——阈值的唯一事实源。

为什么要闸（2026-10-08 取证）：2026-09-05 E: 打到 100%（当日读数最低 28 MB）时，
Ubuntu 的根文件系统正是 `E:\wsl\Ubuntu\ext4.vhdx`。宿主盘没有余量，vhdx 就无法分配新块，
而这件事在 VM 里**不是以 ENOSPC 露面，而是以 EIO 露面**——rustc 用 mmap 读写工具链与
target 文件，映射页无法后备时内核投递 SIGBUS(7)，那一轮留下 7 个崩溃转储（2.18 GB）
落在 C 盘 Temp，反过来又吃 C 盘。整个过程没有任何一处提前说过"盘不够"，人只看到
"rustc 崩了"。本闸的作用就是把这条不可读的损失换成构建开始前的一行可读拒绝。

阈值依据（2026-10-08 实测，不是拍脑袋）：`NeurUI/src-tauri/target` 当时 5.4 GB
（release 1.9 + debug 3.6），另有 NSIS bundle、`dist/installer` 产物与同盘 vhdx 增长要抢空间；
`MIN_FREE_GB` 取该足迹的约两倍并向上取整。它是一道**兜底地板**，不是容量规划。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]

MIN_FREE_GB = 12.0

# 会被多 GB 级写入顶到的落点；缺省全查，任一不足即拒。
DEFAULT_PROBE_PATHS: Tuple[Path, ...] = (
    REPO / "NeurUI" / "src-tauri" / "target",
    REPO / "dist" / "installer",
)


def freeBytesAt(path) -> int:
    """取 `path` 所在盘的剩余字节。

    干净机器上 target 还不存在，逐级退到最近的存在祖先再取——不能因为路径没建就直接报错，
    那正是最需要闸的那次构建。
    """
    probe = Path(path)
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            raise ValueError("取不到所在盘：{} 及其所有祖先都不存在".format(path))
        probe = parent
    # shutil.disk_usage 的字段序是 (total, used, free)；按位置解包会把 used 当成 free 报出去
    return shutil.disk_usage(str(probe)).free


def assertHeadroom(paths: Iterable, minFreeGb: float = MIN_FREE_GB) -> List[Tuple[Path, int]]:
    """余量够则返回读数，不够则抛 RuntimeError 并点名路径、实测值与闸值。"""
    readings = [(Path(p), freeBytesAt(p)) for p in paths]
    required = int(minFreeGb * 1024 ** 3)
    short = [(p, free) for p, free in readings if free < required]
    if short:
        detail = "\n".join(
            "  {} 所在盘实测剩余 {:.2f} GB，闸值 {:.0f} GB".format(p, free / 1024 ** 3, minFreeGb)
            for p, free in short
        )
        raise RuntimeError(
            "磁盘余量不足，拒绝开始构建——多 GB 级 target 写入会把盘写穿；"
            "盘满在 WSL 里以 EIO/SIGBUS 露面，不会以 ENOSPC 提醒你：\n{}".format(detail)
        )
    return readings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="构建前磁盘余量闸（阈值唯一事实源：disk_headroom.MIN_FREE_GB）")
    parser.add_argument("paths", nargs="*",
                        help="被检查的路径；不传则检查 tauri target 与安装器产物目录")
    parser.add_argument("--min-gb", type=float, default=MIN_FREE_GB, dest="minGb",
                        help="覆盖阈值（仅判据用；建置里不要抄字面量）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = [Path(p) for p in args.paths] or list(DEFAULT_PROBE_PATHS)
    try:
        readings = assertHeadroom(paths, args.minGb)
    except (RuntimeError, ValueError) as exc:
        print("[disk-headroom] {}".format(exc), file=sys.stderr)
        return 1

    for path, free in readings:
        print("[disk-headroom] OK {} 剩余 {:.2f} GB（闸值 {:.0f} GB）".format(
            path, free / 1024 ** 3, args.minGb))
    return 0


if __name__ == "__main__":
    sys.exit(main())
