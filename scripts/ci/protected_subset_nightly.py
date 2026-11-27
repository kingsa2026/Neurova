#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受保护子集的夜间复核：把 `protected_tests.txt` 逐条**单独**跑一遍，报出哪几条不绿。

## 为什么需要它（白天的门禁缺这一块）

`scripts/ci/protected_tests.txt` 的准入纪律写在 AGENTS.md §4/§3：
「该清单只收逐文件单跑确定全绿的」。但这条纪律**从来没被复核过**——
白天那一步是把整张清单塞进一次 pytest 跑完（`pytest ... $TESTS`），它能证明
"这一堆放在一起时全绿"，证不了"每一条单独跑也全绿"，而且一旦红就只知道红了、
不知道是哪一条。本脚本补的就是"准入条件本身有没有还在成立"这道复核：

- **逐文件隔离、有界并发**：每条仍是独立 pytest 进程，默认 2 并发；
- 每条自带超时，整轮另有总墙钟预算；预算耗尽明确标记未完成条目；
- 状态逐条原子落盘，清单/仓库指纹一致时只复用绿色条目；
- 报告点名每条的读数（绿/红/超时/预算耗尽/未启动/缺失），退出码只在全绿时为 0。

## 为什么放夜间而不是 push 门禁

整份清单逐条单跑是小时量级（主要开销是每条一个进程），放 push 上会把门禁时长推到
没人等的程度；而"条目悄悄变红"是时间维度的漂移（别人改了公共 fixture、依赖上游变了），
正属夜间该抓的那类。口径与周级的部署配置巡检一致：**非门禁、允许失败、不上报提交状态**，
红了由夜间报告说话，不拦任何人的合并。

用法：
    python scripts/ci/protected_subset_nightly.py               # 全量逐条（默认 2 并发/85m 总预算）
    python scripts/ci/protected_subset_nightly.py --limit 5     # 冒烟（CI 自检用）
    python scripts/ci/protected_subset_nightly.py --list        # 只列条目不跑
    python scripts/ci/protected_subset_nightly.py --state-file /tmp/nightly.json --resume
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
LIST_FILE = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"
#: 单条默认上限。受保护条目都是"单跑确定全绿"的，正常远低于此；
#: 真撞上限的形态是挂死（锁、外部服务、等待输入），那正是要单独点名出来的一类。
DEFAULT_PER_FILE_TIMEOUT = 600.0
#: CNB 单格墙钟 90m；脚本预留 5m 收束、杀子进程、落状态与打印失败汇总。
DEFAULT_TOTAL_TIMEOUT = 85 * 60.0
DEFAULT_WORKERS = 2
STATE_VERSION = 1


# 本脚本不是包、也没有 pytest 的 rootdir 注入，故自己把仓根放进 sys.path——单源 helper
# 住在生产侧（§6-490），import 方向只能是 scripts → neurova，反向就是方向错。
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neurova.core.text_encoding import utf8ChildEnv


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


def runOne(entry: str, perFileTimeout: float, deadline: float | None = None) -> Tuple[str, float, str]:
    """单跑一条；总预算先于单条预算命中时杀子进程并报 budget。"""
    if deadline is not None and time.monotonic() >= deadline:
        return "not_run", 0.0, "总预算耗尽，未启动"
    target = REPO_ROOT / entry
    if not target.is_file():
        return "missing", 0.0, "文件不在仓里"
    started = time.monotonic()
    effectiveTimeout = perFileTimeout
    totalBudgetBound = False
    if deadline is not None:
        remaining = deadline - started
        if remaining <= 0:
            return "not_run", 0.0, "总预算耗尽，未启动"
        effectiveTimeout = min(effectiveTimeout, remaining)
        totalBudgetBound = remaining <= perFileTimeout
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", entry],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=utf8ChildEnv(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=effectiveTimeout)
    except subprocess.TimeoutExpired:
        if proc.poll() is None:
            proc.kill()
        stdout, stderr = proc.communicate()
        elapsed = time.monotonic() - started
        if totalBudgetBound:
            return "budget", elapsed, f">总预算，已终止（单条上限 {perFileTimeout:.0f}s）"
        return "timeout", elapsed, f">{perFileTimeout:.0f}s 未完成"
    elapsed = time.monotonic() - started
    tail = [ln for ln in (stdout or "").splitlines()
            if " passed" in ln or " failed" in ln or " error" in ln]
    summary = tail[-1].strip() if tail else (stdout or stderr or "")[-120:].strip()
    return ("green" if proc.returncode == 0 else "red"), elapsed, summary


def listDigest(entries: List[str]) -> str:
    """清单内容指纹；注释变化不影响续跑，条目顺序或内容变化即失效。"""
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def repositoryFingerprint() -> str:
    """续跑状态只对同一提交、同一工作树路径集合与本脚本有效。"""
    commands = (
        ["git", "rev-parse", "HEAD"],
        ["git", "status", "--porcelain"],
    )
    readings = []
    for command in commands:
        proc = subprocess.run(
            command, cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, env=utf8ChildEnv(),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"读取续跑仓库指纹失败：{' '.join(command)}：{proc.stderr.strip()}")
        readings.append(proc.stdout)
    readings.append(hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return hashlib.sha256("\n".join(readings).encode("utf-8")).hexdigest()


def loadState(statePath: Path, repoDigest: str, entriesDigest: str) -> Dict[str, Tuple[str, float, str]]:
    """只复用指纹一致且状态为 green 的条目；损坏状态必须显式失败。"""
    if not statePath.exists():
        return {}
    try:
        payload = json.loads(statePath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"状态文件损坏：{statePath}：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise RuntimeError(f"状态文件版本不支持：{statePath}")
    if payload.get("repoSha256") != repoDigest or payload.get("listSha256") != entriesDigest:
        return {}
    rawResults = payload.get("results")
    if not isinstance(rawResults, dict):
        raise RuntimeError(f"状态文件损坏：{statePath}：results 不是对象")
    resumed = {}
    for entry, result in rawResults.items():
        if isinstance(result, dict) and result.get("status") == "green":
            resumed[entry] = ("green", float(result.get("elapsed", 0)), str(result.get("summary", "")))
    return resumed


def saveState(
    statePath: Path,
    repoDigest: str,
    entriesDigest: str,
    results: Dict[str, Tuple[str, float, str]],
) -> None:
    """逐条落状态；同目录临时文件替换，进程被杀不会留下半截 JSON。"""
    payload = {
        "version": STATE_VERSION,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "repoSha256": repoDigest,
        "listSha256": entriesDigest,
        "results": {
            entry: {"status": status, "elapsed": elapsed, "summary": summary}
            for entry, (status, elapsed, summary) in results.items()
        },
    }
    statePath.parent.mkdir(parents=True, exist_ok=True)
    temporary = statePath.with_name(statePath.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(statePath)


def executeEntries(
    entries: List[str],
    perFileTimeout: float,
    totalTimeout: float,
    workers: int,
    resumed: Dict[str, Tuple[str, float, str]] | None = None,
    onResult=None,
) -> Dict[str, Tuple[str, float, str]]:
    """有界并发执行；预算耗尽时未启动条目明确标 not_run，不冒充通过。"""
    if workers < 1:
        raise ValueError("workers 必须 >= 1")
    if totalTimeout <= 0:
        raise ValueError("totalTimeout 必须 > 0")
    resumed = resumed or {}
    results: Dict[str, Tuple[str, float, str]] = {}
    pending = []
    for entry in entries:
        if entry in resumed:
            results[entry] = ("skipped", 0.0, "续跑复用绿色结果")
        else:
            pending.append(entry)
    deadline = time.monotonic() + totalTimeout
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(runOne, entry, perFileTimeout, deadline): entry
            for entry in pending
        }
        for future in as_completed(futures):
            entry = futures[future]
            result = future.result()
            results[entry] = result
            if onResult is not None:
                onResult(entry, result)
    return results


def main(argv: List[str] | None = None) -> int:
    # Windows 宿主默认 cp936：本脚本会 print 中文与箭头，出口不钉 utf-8 就会在一句 print 上
    # 抛 UnicodeEncodeError、退出码 1，让"红"指向脚本自己而不是被测行为（§6-496）。
    # 放在 main 里而不是模块级：这几档会被 pytest 以 importlib 加载，模块级钉等于改宿主进程。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（冒烟用）")
    parser.add_argument("--list", action="store_true", help="只列条目，不起子进程")
    parser.add_argument("--per-file-timeout", type=float, default=DEFAULT_PER_FILE_TIMEOUT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发子进程上限")
    parser.add_argument("--total-timeout", type=float, default=DEFAULT_TOTAL_TIMEOUT, help="整轮墙钟预算（秒）")
    parser.add_argument("--state-file", type=Path, default=None, help="逐条续跑状态文件（放在仓外）")
    parser.add_argument("--resume", action="store_true", help="跳过状态文件中指纹一致的绿色条目")
    parser.add_argument("--quiet", action="store_true", help="只报非绿条目")
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit 必须 >= 0")
    if args.per_file_timeout <= 0 or args.total_timeout <= 0:
        parser.error("--per-file-timeout 与 --total-timeout 必须 > 0")
    if args.workers < 1:
        parser.error("--workers 必须 >= 1")
    if args.resume and args.state_file is None:
        parser.error("--resume 必须同时指定 --state-file")

    entries = readEntries()
    entriesDigest = listDigest(entries)
    print(f"受保护子集条目：{len(entries)} 条（清单：{LIST_FILE.relative_to(REPO_ROOT)}）")
    if args.list:
        for entry in entries:
            print(entry)
        return 0
    if args.limit:
        entries = entries[:args.limit]
        print(f"本次只跑前 {len(entries)} 条（--limit）")

    repoDigest = repositoryFingerprint()
    resumed = loadState(args.state_file, repoDigest, entriesDigest) if args.resume else {}
    print(f"续跑复用 {len(resumed)} 条绿色结果" if args.resume else "本轮不复用旧状态")
    stateResults = dict(resumed)

    def recordResult(entry, result):
        if args.state_file is None:
            return
        stateResults[entry] = result
        saveState(args.state_file, repoDigest, entriesDigest, stateResults)

    started = time.monotonic()
    results = executeEntries(
        entries,
        perFileTimeout=args.per_file_timeout,
        totalTimeout=args.total_timeout,
        workers=args.workers,
        resumed=resumed,
        onResult=recordResult if args.state_file is not None else None,
    )

    bad: Dict[str, str] = {}
    for index, entry in enumerate(entries, 1):
        status, elapsed, summary = results[entry]
        if status == "green":
            if not args.quiet:
                print(f"[{index}/{len(entries)}] 绿 {elapsed:6.1f}s  {entry}")
            continue
        if status == "skipped":
            if not args.quiet:
                print(f"[{index}/{len(entries)}] SKIP 续跑复用  {entry}")
            continue
        bad[entry] = f"{status}: {summary}"
        print(f"[{index}/{len(entries)}] {status.upper()} {elapsed:6.1f}s  {entry} — {summary}")

    print(f"\n耗时 {time.monotonic() - started:.0f}s，条目 {len(entries)}，非绿 {len(bad)}")
    if args.state_file is not None:
        print(f"续跑状态：{args.state_file}")
    for entry, reason in bad.items():
        print(f"  {entry} — {reason}")
    if any(result[0] in {"budget", "not_run"} for result in results.values()):
        print("\n总预算耗尽：未完成条目已明确标记；确认清单与代码未变后用 --resume 续跑")
    if bad:
        print("\n夜间复核 FAILED / 受保护子集有条目不再满足「逐文件单跑确定全绿」")
        return 1
    print("夜间复核 PASSED / 受保护子集逐条单跑全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
