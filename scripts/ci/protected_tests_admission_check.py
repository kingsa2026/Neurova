#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受保护子集**收录门**：往 protected_tests*.txt 新增收录时，逐文件单跑必须全绿（教义第 3 条）。

清单原则（索引顶部注释）："只进当前确定全绿的测试；预存失败模块不进 CI，修复后逐个搬入。"
此前"确定全绿"靠人自觉；本门把它变成机器判据：本次 diff 新增的收录条目逐文件单跑 pytest，
非零退出（失败 / 收集错 / 零收集）即拒绝，点名文件与退出码。

只校验**增量**（diff 新增行）；全量健康由 CI 分片与 nightly（protected_subset_nightly.py）
负责，不在此重复——那是分片存在的理由，别把 4187 行再塞回一个进程。

用法：
    python scripts/ci/protected_tests_admission_check.py --from-index    # pre-commit 壳调起
    python scripts/ci/protected_tests_admission_check.py --files a.py b.py  # 人工收录前自查
退出码：0 放行；1 拒绝（stderr 点名）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

#: 首笔提交（无 HEAD）时 diff 的基线：git 空树对象号。
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def parseAdmissions(diffText: str) -> list:
    """unified diff（-U0）文本 → 新增收录条目（剥注释与空行）。"""
    admissions = []
    for line in diffText.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        entry = line[1:].strip()
        if entry and not entry.startswith("#"):
            admissions.append(entry)
    return admissions


def listFiles(repo: Path) -> list:
    """protected_tests*.txt 清单文件（分片号的事实源是目录里有哪几片，不手抄片号）。"""
    return sorted((repo / "scripts" / "ci").glob("protected_tests*.txt"))


def admissionsFromIndex(repo: Path) -> list:
    """暂存区里对清单文件的**新增收录**条目。取数失败报错，不静默当空。"""
    lists = listFiles(repo)
    if not lists:
        return []
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=30)
    base = head.stdout.strip() if head.returncode == 0 else EMPTY_TREE
    spec = [str(path.relative_to(repo)) for path in lists]
    proc = subprocess.run(
        ["git", "diff", "--cached", base, "-U0", "--", *spec],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            f"读暂存区清单差异失败（exit {proc.returncode}）：{proc.stderr.strip()}")
    return parseAdmissions(proc.stdout)


def checkFiles(files, python: str, timeout: int, cwd: Path) -> tuple:
    """逐文件单跑 pytest。返回 (ok, reportLines)。"""
    if not files:
        return True, ["[收录门] 无新增收录，放行。"]
    report, ok = [], True
    for path in files:
        target = Path(path)
        if not target.is_file():
            alt = Path(cwd) / path
            if alt.is_file():
                target = alt
            else:
                ok = False
                report.append(f"[收录门] {path}：文件不存在——清单点名的路径必须真实存在")
                continue
        try:
            proc = subprocess.run(
                [python, "-m", "pytest", str(target), "-q", "--no-header",
                 "-p", "no:cacheprovider", "--rootdir", str(cwd)],
                cwd=str(cwd), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout)
            code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            ok = False
            report.append(f"[收录门] {path}：单跑超过 {timeout}s 墙钟——先查明为何这么慢再谈收录")
            continue
        if code == 0:
            report.append(f"[收录门] {path}：单跑全绿，放行收录")
            continue
        ok = False
        if "No module named" in err and "pytest" in err:
            report.append(f"[收录门] {path}：解释器 {python} 没有 pytest——用项目 .venv 的解释器跑本门")
        elif code == 5:
            report.append(f"[收录门] {path}：零收集（exit 5）——收了个跑不出用例的文件等于没测")
        else:
            report.append(
                f"[收录门] {path}：单跑非绿（exit {code}）——红灯文件在转绿前不得收录（教义第 3 条）")
        report.extend(f"    {tail}" for tail in out.strip().splitlines()[-5:])
    return ok, report


def pickPython(repo: Path) -> str:
    """优先项目 .venv（跑测口径与 CI 同源）；没有再退当前解释器（缺 pytest 会在报告里点名）。"""
    for parts in ((".venv", "Scripts", "python.exe"), (".venv", "bin", "python")):
        candidate = repo.joinpath(*parts)
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def main(argv=None) -> int:
    defaultRepo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="受保护子集收录门（AGENTS.md §1 教义第 3 条）")
    parser.add_argument("--from-index", action="store_true", help="从 git 暂存区读本次新增收录")
    parser.add_argument("--files", nargs="*", default=None, help="显式待收录文件（人工自查用）")
    parser.add_argument("--repo", default=str(defaultRepo))
    parser.add_argument("--python", default=None, help="跑单测的解释器；缺省优先项目 .venv")
    parser.add_argument("--timeout", type=int, default=300, help="单文件墙钟（秒）")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    if args.files is not None:
        files = args.files
    elif args.from_index:
        files = admissionsFromIndex(repo)
    else:
        files = []
    python = args.python or pickPython(repo)
    ok, report = checkFiles(files, python=python, timeout=args.timeout, cwd=repo)
    for line in report:
        print(line, file=sys.stderr if not ok else sys.stdout)
    if not ok:
        print("[收录门] 拒绝：红灯文件在转绿前不得进 protected_tests（AGENTS.md §1 教义第 3 条）。",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
