#!/usr/bin/env python3
"""宽域 A/B 驱动：在**仓外只读 worktree** 里建基线，比 `FAILED`/`ERROR` **集合**而不是条数。

为什么要它：台账里"A/B 零差集"这类结论已经烧过三轮假通过——形态分别是
①命令尾接 `tail` 把退出码读成 `tail` 的（一整轮红被读成 0）；
②两侧都没跑成却报"仅本树红 0 条 = AB_PASS"（没产出汇总行 ≠ 全绿）；
③`-c` 漏给新判据，基线树里根本没有那格，"两侧失败集合一致"于是是一句假话。
这三形都指向同一件事：**差集判读的前提是取数口自己没坏**，所以这道闸把对账做在标记之前。

为什么是 Python 而不是登记名里那个 `.sh`：仓内另有一个生产符号 `ab_compare`
（`neurova/evolution/service.py` 的双臂试评），同一个词指两样东西是教义第 6 条的命名面；
而常驻判据要能在 Windows 与 CI 两种宿主上用本仓唯一跑测解释器跑起来，不该赌 PATH 里有 bash
（台账 §6-332 还记过 MSYS 的 `TMPDIR`/`MSYS_NO_PATHCONV` 坑：bash 侧与原生 git 侧把同一个
`/tmp/...` 解析成两个目录，基线树于是只剩铺进去的那格）。

用法（与本仓跑测口径一致，一律带 `-p no:cacheprovider`）：

    .venv/Scripts/python.exe scripts/ci/ab_baseline.py -k HEAD -n 3 -c <本批新判据> -- <pytest 选择集>

四种标记：`AB_PASS`（仅本树红 0 条，或那些条目在基线复跑 n 次皆红＝预存）、
`AB_REGRESSION`（有条目在本树红而在基线复跑里出现过绿）、`AB_FAIL`（对账不过／没产出汇总行／
仅本树红那条在基线树里找不到节点）、`AB_SKIP`（输入不是本仓形态）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: 汇总行**不许锚 `^`**：`addopts` 含 `-v` 时它被 `=` 包裹，裸锚在那种仓里 0 命中。
_SUMMARY = re.compile(
    r"(\d+) failed.*?(\d+) passed.*?(\d+) error|"
    r"(\d+) failed.*?(\d+) passed(?!\S* error)|"
    r"(?<!\d)(\d+) error[s]?(?!.*\d passed)")
#: 只认 pytest 短汇总的节点形状（`path.py` 或 `path.py::node` + ` - `／行尾）。
#: 不能退回 `\S+`：应用日志会打 `ERROR logger:module.py:line - ...`，那会被当成一条测试节点
#: （§6-371 实测：汇总 16 条红被抽成 18 条，对账闸当场判 AB_FAIL）。
_FAILURE_LINE = re.compile(
    r"^(FAILED|ERROR)\s+([^\s:]+\.py(?:::\S+)?)(?:\s+-|$)", re.M)


def parseSummary(text: str):
    """从 pytest 输出里取「失败/通过/错误」三条计数；取不到返回 None（**不是 0**）。"""
    for line in reversed(text.splitlines()):
        if " passed" not in line and " failed" not in line and " error" not in line:
            continue
        failed = re.search(r"(\d+) failed", line)
        passed = re.search(r"(\d+) passed", line)
        errors = re.search(r"(\d+) error", line)
        if not (failed or passed or errors):
            continue
        return {"failed": int(failed.group(1)) if failed else 0,
                "passed": int(passed.group(1)) if passed else 0,
                "errors": int(errors.group(1)) if errors else 0}
    return None


def extractFailures(text: str) -> set:
    """`FAILED`/`ERROR` 短汇总行的节点 id 集合——按文本读，NUL 字节不许让它闭嘴。"""
    return {m.group(2) for m in _FAILURE_LINE.finditer(text)}


def reconcile(text: str) -> dict:
    """同一次输出内部的对账：汇总报的红条数与实际抽到的条数必须咬合。"""
    summary = parseSummary(text)
    if summary is None:
        return {"ok": False, "reason": "没产出汇总行（没跑成不等于全绿）",
                "reported": None, "extracted": len(extractFailures(text))}
    extracted = extractFailures(text)
    reported = summary["failed"] + summary["errors"]
    if reported and not extracted:
        return {"ok": False, "summary": summary, "reported": reported, "extracted": 0,
                "reason": f"汇总报 {reported} 条红而抽取到 0 条＝捕获口径失效，零差集是假的"}
    if reported != len(extracted):
        return {"ok": False, "summary": summary, "reported": reported,
                "extracted": len(extracted),
                "reason": f"汇总报 {reported} 条红，实际抽到 {len(extracted)} 条（对账不过）"}
    return {"ok": True, "summary": summary, "reported": reported,
            "extracted": len(extracted), "reason": ""}


def classify(baselineFailures: set, treeFailures: set, baselineCollectable, reruns) -> dict:
    """判标记。`reruns`＝[(node, [是否红, ...])]；`baselineCollectable`＝None 表示交由复跑探节点。"""
    onlyTreeRed = sorted(set(treeFailures) - set(baselineFailures))
    preexisting, regressions, missing = [], [], []
    rerunMap = dict(reruns)
    for node in onlyTreeRed:
        if baselineCollectable is not None and node not in baselineCollectable:
            missing.append(node)
            continue
        outcomes = rerunMap.get(node)
        if outcomes is None:
            continue
        if all(outcomes):
            preexisting.append(node)
        else:
            regressions.append(node)
    detail = []
    if missing:
        detail.append("仅本树红但基线树找不到节点（多半是 -c 漏给）: " + ", ".join(missing))
    if regressions:
        detail.append("按回归处置: " + ", ".join(regressions))
    marker = "AB_FAIL" if missing else ("AB_REGRESSION" if regressions else "AB_PASS")
    return {"marker": marker, "onlyTreeRed": onlyTreeRed, "preexisting": preexisting,
            "regressions": regressions, "missingInBaseline": missing,
            "onlyBaselineRed": sorted(set(baselineFailures) - set(treeFailures)),
            "detail": "；".join(detail)}


def _run(cmd, cwd, env=None):
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    return (proc.stdout or "") + (proc.stderr or "")


def _runPytest(cwd: Path, selection, extraEnv=None):
    # 两侧都要能 import 到被测树**与**每个依赖：把 `PYTHONPATH` 覆写成只有 `cwd` 时，
    # 当解释器把依赖装在 `PYTHONPATH` 上（`pip install --target`、或环境里没装 pytest
    # 而靠 PYTHONPATH 提供）时，两侧一起来一句 `No module named pytest` ⇒ 读数退成
    # 「没产出汇总行 ⇒ AB_FAIL」，与"基线真的跑不过"同形。故按冒号追加，不覆写。
    inherited = [p for p in (os.environ.get("PYTHONPATH") or "").split(os.pathsep) if p]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(cwd)] + inherited),
           "PYTHONIOENCODING": "utf-8"}
    env.update(extraEnv or {})
    return _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 *selection], cwd, env)


def _isRepoShape(root: Path) -> bool:
    return (root / "scripts" / "ci" / "protected_tests.txt").is_file() and \
        (root / "pyproject.toml").is_file()


def _git(cwd: Path, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _reconfigureStdout():
    """本脚本的读数里带中文与箭头，Windows 默认 stdout 是 cp936——不打这一行就会
    在一句 `print` 上抛 UnicodeEncodeError、退出码 1，于是"红"指向脚本自己而不是被测行为
    （本仓 manual 档早就为同一件事钉过这一行，这里同口径，不另造写法）。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    _reconfigureStdout()
    parser = argparse.ArgumentParser(description="宽域 A/B（仓外只读 worktree 基线）")
    parser.add_argument("-k", "--ref", default="HEAD")
    parser.add_argument("-n", "--reruns", type=int, default=3)
    parser.add_argument("-c", "--criteria", action="append", default=[],
                       help="本批新增判据文件（相对仓根，可多次）——铺进基线树，"
                            "使基线＝HEAD 生产码＋本批判据、无修复")
    parser.add_argument("--root", default=None, help="被比较的仓根（默认为本脚本所在仓）")
    parser.add_argument("--tmp", default=None, help="基线 worktree 的父目录（默认系统临时目录）")
    parser.add_argument("--json", action="store_true", help="额外吐一行机器可读读数")
    parser.add_argument("selection", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    root = Path(args.root or Path(__file__).resolve().parents[2]).resolve()
    selection = [s for s in args.selection if s != "--"]
    if not selection:
        print("AB_FAIL：没给 pytest 选择集（空选择集下的零差集什么都不能说明）")
        return 1
    if not _isRepoShape(root):
        print(f"AB_SKIP：{root} 不是本仓形态（缺 scripts/ci/protected_tests.txt 或 pyproject.toml）")
        return 0

    tmpBase = Path(args.tmp or tempfile.mkdtemp(prefix="abBaseline-")).resolve()
    tmpBase.mkdir(parents=True, exist_ok=True)
    worktree = tmpBase / "baseline"
    try:
        added = _git(root, "worktree", "add", "--detach", str(worktree), args.ref)
        if added.returncode != 0:
            print("AB_FAIL：基线 worktree 建不起来\n" + (added.stderr or added.stdout))
            return 1
        for rel in args.criteria:
            src = root / rel
            if not src.is_file():
                print(f"AB_FAIL：-c 给的文件不在场：{rel}")
                return 1
            dst = worktree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)

        baseLog = _runPytest(worktree, selection)
        treeLog = _runPytest(root, selection)
        baseCheck, treeCheck = reconcile(baseLog), reconcile(treeLog)
        if not baseCheck["ok"] or not treeCheck["ok"]:
            print("AB_FAIL：对账不过——"
                  f"基线 {baseCheck['reason']}｜本树 {treeCheck['reason']}")
            return 1

        baselineFailures, treeFailures = extractFailures(baseLog), extractFailures(treeLog)
        outcomes = []
        for node in sorted(treeFailures - baselineFailures):
            reds = []
            for _ in range(max(1, args.reruns)):
                single = _runPytest(worktree, [node])
                if parseSummary(single) is None:
                    outcomes.append((node, None))
                    reds = None
                    break
                reds.append(bool(extractFailures(single)))
            if reds is not None:
                outcomes.append((node, reds))
        missing = [node for (node, reds) in outcomes if reds is None]
        verdict = classify(baselineFailures, treeFailures, None,
                           [(n, r) for (n, r) in outcomes if r is not None])
        if missing:
            verdict = {"marker": "AB_FAIL",
                       "detail": "仅本树红但基线树跑不出这一格（多半是 -c 漏给）: "
                                 + ", ".join(missing),
                       "onlyTreeRed": sorted(treeFailures - baselineFailures),
                       "preexisting": [], "regressions": [], "missingInBaseline": missing,
                       "onlyBaselineRed": sorted(baselineFailures - treeFailures)}
        verdict.update({"baseline": parseSummary(baseLog), "tree": parseSummary(treeLog),
                        "reruns": args.reruns, "criteria": args.criteria})
        print(f"{verdict['marker']}｜基线 {verdict['baseline']} ↔ 本树 {verdict['tree']}｜"
              f"仅本树红 {len(verdict['onlyTreeRed'])} 条｜"
              f"其中预存 {len(verdict['preexisting'])} 条（各复跑 {args.reruns} 次）｜"
              f"仅基线红 {len(verdict['onlyBaselineRed'])} 条")
        if verdict.get("detail"):
            print(f"  {verdict['detail']}")
        if verdict["onlyBaselineRed"]:
            print("  仅基线红（本批修复使其转绿的交付证据，逐条引到正文）：")
            for node in verdict["onlyBaselineRed"][:20]:
                print(f"    {node}")
        if args.json:
            print(json.dumps(verdict, ensure_ascii=False, default=list))
        return 0 if verdict["marker"] in ("AB_PASS", "AB_SKIP") else 1
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree))
        if args.tmp is None:
            shutil.rmtree(tmpBase, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
