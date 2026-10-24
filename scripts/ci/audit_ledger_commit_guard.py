#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计台账 commit 号可达性扫描器（判据唯一出处，守卫与人共用）。

为什么要有这个扫描器：`audit-reports/*.md` 以 `` `xxxxxxxx` `` 形式引用 commit 号，
而并发会话的 rebase / merge 会**重写历史**——号对应的对象仍留在 `.git` 里，于是
`git cat-file -e` 照样成功，但那个号已经不在任何分支历史上了。只查"对象存在"
证明不了"号还在"，台账会长期指向不在历史里的提交，而读的人无从发现。

可达性判据：`git merge-base --is-ancestor <h> HEAD`。
替代号判据：同标题 **且** `git show --numstat` 逐行一致，且唯一——只凭标题相同就替换
不安全（遇到"同题重做"会张冠李戴），不满足则宁可留空由人工判定。

性能口径：HEAD 索引一次 `git log` 取回（标题随行），diffstat 只对同标题候选计算。
早先写法是逐个 HEAD 提交起一次 `git log`/`git show`，在万级仓库上直接超时。

用法：
    python scripts/ci/audit_ledger_commit_guard.py              # 人读摘要
    python scripts/ci/audit_ledger_commit_guard.py --porcelain  # 机器行，供守卫比对
退出码：有失效号时非 0。
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "audit-reports"
HASH_RE = re.compile(r"`([0-9a-f]{8,40})`")
HEX_ONLY = re.compile(r"^[0-9a-f]{8,40}$")

_numstatCache: dict = {}
_objectTypeCache: dict = {}

#: 本脚本每次 git 调用的预算唯一出处。**逐号**起 `merge-base` 是全档成本的来源
#: （台账有多少个号就起多少次），单次毫秒级；没有 `timeout=` 时一次卡住的 git
#: 会把调用方整场挂住——而调用方是跑测进程，Windows 侧 pytest-timeout 走 thread 法，
#: 超时即终止整个进程（§6-402 批 K 记的那三度死法）。30s 是单次调用的上界，
#: 整轮扫描的墙由调用方自己按实测声明（见 `tests/unit/test_audit_ledger_commit_guard.py`）。
GIT_WALL_S = 30


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=GIT_WALL_S).stdout


def isCommit(token: str) -> bool:
    if token not in _objectTypeCache:
        _objectTypeCache[token] = _git("cat-file", "-t", token).strip()
    return _objectTypeCache[token] == "commit"


def isReachable(token: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", token, "HEAD"],
                          capture_output=True, timeout=GIT_WALL_S).returncode == 0


def numstatDigest(token: str) -> str:
    if token not in _numstatCache:
        rows = []
        for line in _git("show", "--numstat", "--format=", token).splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                rows.append((parts[0], parts[1], parts[2]))
        _numstatCache[token] = repr(sorted(rows))
    return _numstatCache[token]


def headIndex() -> list:
    """一次 `git log` 取回 [(短号, 标题)]——不可逐提交再起进程（万级仓库会超时）。"""
    rows = []
    for line in _git("log", "--format=%h%x09%s", "HEAD").splitlines():
        if "\t" in line:
            short, subj = line.split("\t", 1)
            rows.append((short, subj.strip()))
    return rows


def findReplacement(token: str, index: list) -> str:
    """同标题 + diffstat 逐行一致且唯一时才给替代号，否则空串（不许猜）。"""
    staleSubject = _git("log", "-1", "--format=%s", token).strip()
    if not staleSubject:
        return ""
    candidates = [short for short, subj in index if subj == staleSubject]
    if not candidates:
        return ""
    digest = numstatDigest(token)
    matched = [c for c in candidates if numstatDigest(c) == digest]
    return matched[0] if len(matched) == 1 else ""


def scanReport(path: Path, index: list):
    """返回 (该报告引用的 commit 号列表, [(失效号, 替代号)])。"""
    text = io.open(path, encoding="utf-8", errors="replace").read()
    tokens, seen = [], set()
    for match in HASH_RE.finditer(text):
        if not HEX_ONLY.match(match.group(1)):
            continue
        short = match.group(1)[:8]
        if short in seen or not isCommit(short):
            continue
        seen.add(short)
        tokens.append(short)
    stale = [(t, findReplacement(t, index)) for t in tokens if not isReachable(t)]
    return tokens, stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="审计台账 commit 号可达性")
    parser.add_argument("--porcelain", action="store_true",
                        help="每行 `<报告>|<失效号>|<替代号>`，供守卫比对")
    args = parser.parse_args(argv)

    index = headIndex()
    totalRefs, staleRows = 0, []
    for report in sorted(REPORT_DIR.glob("*.md")):
        tokens, stale = scanReport(report, index)
        totalRefs += len(tokens)
        for bad, repl in stale:
            staleRows.append((report.name, bad, repl))
        if not args.porcelain:
            print("%-46s 引用 %3d 个号，失效 %d" % (report.name, len(tokens), len(stale)))
            for bad, repl in stale:
                print("    失效 %s%s" % (bad, "  → 可回写为 " + repl if repl
                                         else "  （无可安全回写的替代号）"))

    if args.porcelain:
        for row in staleRows:
            print("|".join(row))
    if staleRows:
        print("失效引用 %d 条 / 共 %d 条引用（目录 %s）"
              % (len(staleRows), totalRefs, REPORT_DIR.relative_to(PROJECT_ROOT)),
              file=sys.stderr)
        return 1
    print("台账 commit 号全部可达（共 %d 条引用）" % totalRefs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
