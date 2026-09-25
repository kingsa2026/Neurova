#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 分支归档清理的取数与判定（AGENTS.md §0 的机器判据落点）。

## 为什么需要这一支

AGENTS.md §0 把「NPC 分支合并/废弃后**立即删除该远端分支**」写成硬动作，理由在
同节原文里：构建配置**随分支走**——某个分支改过 `.cnb.yml`，该分支每次产生构建
都会重新加载它自己那一份；于是分支一旦被归档而不清理，过期的配置会永久留着
复现同一场失败，**与任务内容、与主线代码都无关**。

本仓当前没有一条机器判据会发现「已合并的分支仍留在远端」：悬空扫描只认文档里的
路径与链接，CI 门禁只跑代码与配置，远端分支列表不在任何一处的覆盖面内。
这就是「写了纪律、没有可复核的读数」这一断点形态，与 §0 里说的
「配置在推送分支的那一刻非法，与任务无关」是同一类故障：**看着都配了，其实无人复核**。

## 判定口径（唯一事实源）

- **归档候选**：分支名以 `auto/` 开头（NPC 自动分支的唯一命名空间）；
- **待删**：该分支的提交已经是 `main` 的祖先（即已被合并进主线）；
- **保留**：未合并的分支（可能还有在途工作），以及非 `auto/` 的长期分支。

判定只由「是否为 main 的祖先」给出，不由"squash 合并后是否还能对上 sha"给出——
平台合并（merge commit）会保留原提交，`--is-ancestor` 即可回答；本仓的合并请求
全部走 merge commit（见 `git log --merges`），不存在 squash 形态。

## 取数（网络边界的唯一处）

`ls-remote` 是本模块唯一触碰网络的动作，**只在被显式调用时发生**；
常驻守卫不调它，只比对台账与仓内事实（见 `tests/unit/ci/test_npc_branch_cleanup.py`），
故 CI 不会因远端不可达而红——那是「判据随环境漂红」，不是契约。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: NPC 自动分支的命名空间。只有这个前缀下的分支参与归档判定——
#: 长期分支（`main` / `docs/*` 等）由人管理，不由本判据裁决。
NPC_BRANCH_PREFIX = "auto/"

#: 主line 引用。判定「已合并」即「这个提交是不是它的祖先」。
MAIN_REF = "origin/main"


def parseRemoteHeads(raw: str) -> Dict[str, str]:
    """`git ls-remote --heads` 的输出 → {分支名: sha}。

    只认 `refs/heads/` 之下的行；其余（tag、pull 引用）一律不进判据。
    """
    heads: Dict[str, str] = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, ref = parts[0].strip(), parts[1].strip()
        if not ref.startswith("refs/heads/"):
            continue
        heads[ref[len("refs/heads/"):]] = sha
    return heads


def listRemoteHeads(repo: str = "origin", timeout: int = 60) -> Dict[str, str]:
    """唯一触碰网络的口：取远端分支列表。失败时抛 `RuntimeError`（不静默空集）。"""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as exc:  # pragma: no cover - 环境缺 git
        raise RuntimeError(f"git 不可用：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git ls-remote 超时（{timeout}s）：{exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote 失败：{result.stderr.strip()[-500:]}")
    return parseRemoteHeads(result.stdout)


def remoteRefFor(main_ref: str, branch: str) -> str:
    """分支名 → 本仓可用的远端跟踪引用（`origin/<branch>`）。

    `main_ref` 形如 `origin/main`，其远端名部分即分支引用的前缀；
    单一事实源在此，避免各处自己拼 `origin/` 字符串。
    """
    remote = main_ref.split("/", 1)[0] if "/" in main_ref else "origin"
    return f"{remote}/{branch}"


def isMergedIntoMain(ref: str, main_ref: str = MAIN_REF) -> bool:
    """该引用是否已是主线的祖先（＝已被合并进主线）。"""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ref, main_ref],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
    )
    # merge-base --is-ancestor：0 = 是祖先，1 = 不是，其余 = 出错
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(
        f"merge-base 判定失败（{ref} vs {main_ref}）：{result.stderr.strip()[-500:]}"
    )


def classifyBranches(
    heads: Dict[str, str],
    main_ref: str = MAIN_REF,
    ancestorOfMain: Optional[Dict[str, bool]] = None,
) -> List[Dict[str, object]]:
    """逐条分支判定：`keep`（未合并）/ `stale`（已合并，应当删除）。

    `ancestorOfMain` 允许调用方注入判定结果，使**纯逻辑可离线单测**——
    否则测试就要依赖真远端，那是「判据随环境漂红」。不传时逐条现算。

    **非 NPC 命名空间的分支不参与判定**：连 `isMergedIntoMain` 都不调用。
    早先的实现对 `main` 自己也去跑一次祖先判定，而在只拿到远端头的检出里
    `origin/main` 可能还没建（浅克隆 / 首次 fetch 前），于是判据在
    "不存在的东西"上报错——那是把环境前置条件混进判据，不是契约。
    本仓 `main` 是长期分支，本就不由本判据裁决，故直接放行。
    """
    verdicts: List[Dict[str, object]] = []
    for name in sorted(heads):
        if not name.startswith(NPC_BRANCH_PREFIX):
            verdicts.append({"branch": name, "verdict": "keep",
                             "reason": "非 NPC 自动分支命名空间，不由本判据裁决"})
            continue
        if ancestorOfMain is not None:
            merged = bool(ancestorOfMain.get(name))
        else:
            merged = isMergedIntoMain(f"{remoteRefFor(main_ref, name)}")
        verdicts.append({
            "branch": name,
            "sha": heads[name],
            "verdict": "stale" if merged else "keep",
            "reason": ("已合并进主线，按 AGENTS.md §0 应当立即删除"
                       if merged else "尚未合并进主线，保留"),
        })
    return verdicts


def staleBranches(verdicts: List[Dict[str, object]]) -> List[str]:
    """从判定表里取「应当删除」的分支名（唯一取数口，避免各处自己筛）。"""
    return [str(v["branch"]) for v in verdicts if v.get("verdict") == "stale"]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NPC 分支归档清理取数（只读）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 读数")
    parser.add_argument("--repo", default="origin", help="远端名或 URL（默认 origin）")
    args = parser.parse_args(argv)

    try:
        heads = listRemoteHeads(args.repo)
    except RuntimeError as exc:
        print(f"取数失败：{exc}", file=sys.stderr)
        return 2

    verdicts = classifyBranches(heads)
    stale = staleBranches(verdicts)

    if args.json:
        print(json.dumps({
            "total_heads": len(heads),
            "npc_heads": [v["branch"] for v in verdicts
                          if str(v["branch"]).startswith(NPC_BRANCH_PREFIX)],
            "stale": stale,
            "verdicts": verdicts,
        }, ensure_ascii=False, indent=2))
    else:
        for v in verdicts:
            print(f"{v['verdict']:6s} {v['branch']}  — {v['reason']}")
        print(f"\n应当删除 {len(stale)} 条：{stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
