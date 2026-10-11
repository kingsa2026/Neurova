#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受保护子集的夜间复核：把 `protected_tests.txt` 逐条**单独**跑一遍，报出哪几条不绿。

## 为什么需要它（白天的门禁缺这一块）

`scripts/ci/protected_tests.txt` 的准入纪律写在 AGENTS.md §4/§3：
「该清单只收逐文件单跑确定全绿的」。但这条纪律**从来没被复核过**——
白天那一步是把整张清单塞进一次 pytest 跑完（`pytest ... $TESTS`），它能证明
"这一堆放在一起时全绿"，证不了"每一条单独跑也全绿"，而且一旦红就只知道红了、
不知道是哪一条。本脚本补的就是"准入条件本身有没有还在成立"这道复核：

- **逐条单跑**：与清单的准入口径同形（一条一个进程）；
- 每条自带超时：一条挂死不吃掉整晚；
- 报告点名每条的读数（绿/红/超时/收集失败），退出码只在全绿时为 0。

## 为什么放夜间而不是 push 门禁

498 条逐条单跑约 1 小时量级（进程启动 ×498 为主），放 push 上会把门禁时长推到
没人等的程度；而"条目悄悄变红"是时间维度的漂移（别人改了公共 fixture、依赖上游变了），
正属夜间该抓的那类。口径与周级的部署配置巡检一致：**非门禁、允许失败、不上报提交状态**，
红了由夜间报告说话，不拦任何人的合并。

用法：
    python scripts/ci/protected_subset_nightly.py               # 全量逐条
    python scripts/ci/protected_subset_nightly.py --limit 5     # 冒烟（CI 自检用）
    python scripts/ci/protected_subset_nightly.py --list        # 只列条目不跑
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
LIST_FILE = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"
#: 单条默认上限。受保护条目都是"单跑确定全绿"的，正常远低于此；
#: 真撞上限的形态是挂死（锁、外部服务、等待输入），那正是要单独点名出来的一类。
DEFAULT_PER_FILE_TIMEOUT = 600.0


def readEntries(path: Path = LIST_FILE) -> List[str]:
    """清单读数：注释与空行剔除，其余原样保留（**不做去重、不做排序**）。

    去重与排序会掩盖"同一文件被登记两次"这种形态——那是漂移，不是要整理的事。
    """
    entries: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(stripped)
    return entries


def runOne(entry: str, perFileTimeout: float) -> Tuple[str, float, str]:
    """单跑一条。返回 `(状态, 耗时, 摘要)`，状态 ∈ {green, red, timeout, missing}。"""
    target = REPO_ROOT / entry
    if not target.exists():
        # 清单里指着一个不存在的文件：子进程根本不该被起（起了也是 collection error）
        return "missing", 0.0, "文件不在仓里"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
             entry],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=perFileTimeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout", time.monotonic() - started, f">{perFileTimeout:.0f}s 未完成"
    elapsed = time.monotonic() - started
    tail = [ln for ln in (proc.stdout or "").splitlines()
            if " passed" in ln or " failed" in ln or " error" in ln]
    summary = tail[-1].strip() if tail else (proc.stdout or proc.stderr or "")[-120:].strip()
    return ("green" if proc.returncode == 0 else "red"), elapsed, summary


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（冒烟用）")
    parser.add_argument("--list", action="store_true", help="只列条目，不起子进程")
    parser.add_argument("--per-file-timeout", type=float, default=DEFAULT_PER_FILE_TIMEOUT)
    parser.add_argument("--quiet", action="store_true", help="只报非绿条目")
    args = parser.parse_args(argv)

    entries = readEntries()
    print(f"受保护子集条目：{len(entries)} 条（清单：{LIST_FILE.relative_to(REPO_ROOT)}）")
    if args.list:
        for entry in entries:
            print(entry)
        return 0
    if args.limit:
        entries = entries[:args.limit]
        print(f"本次只跑前 {len(entries)} 条（--limit）")

    bad: Dict[str, str] = {}
    started = time.monotonic()
    for index, entry in enumerate(entries, 1):
        status, elapsed, summary = runOne(entry, args.per_file_timeout)
        if status == "green":
            if not args.quiet:
                print(f"[{index}/{len(entries)}] 绿 {elapsed:6.1f}s  {entry}")
            continue
        bad[entry] = f"{status}: {summary}"
        print(f"[{index}/{len(entries)}] {status.upper()} {elapsed:6.1f}s  {entry} — {summary}")

    print(f"\n耗时 {time.monotonic() - started:.0f}s，条目 {len(entries)}，非绿 {len(bad)}")
    for entry, reason in bad.items():
        print(f"  {entry} — {reason}")
    if bad:
        print("\n夜间复核 FAILED / 受保护子集有条目不再满足「逐文件单跑确定全绿」")
        return 1
    print("夜间复核 PASSED / 受保护子集逐条单跑全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
