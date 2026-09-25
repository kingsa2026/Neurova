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

两个 **git 事实**同时成立才算归档（`stale`）：

- **归档候选**：该分支头出现在主线某个 merge commit 的**第二父位**
  （＝它正是某个已合并请求的源分支头，见 `mergedSourceTips()`）；
- **待删**：该分支头是 `main` 的祖先（＝提交已在主线里，删掉不丢成果）；
- **保留**：其余一律保留 —— 在途的分支（删掉就是丢成果）、以及头已前移的源分支。

**成员资格由事实给出，不由分支名字给出。** 早先口径把「是不是 NPC 工作分支」
等同于「名字是否以 `auto/` 开头」，而名字是平台的产物、不是事实：平台按合并请求的
`head.ref` 决定分支名，NPC 会话既可以建 `auto/*`，也可以建 `fix/*` / `fix-*`。
于是同一形态（一个已合并的归档分支仍留在远端）在一种命名下被拦、在另一种命名下
被放行 —— 实测漏判见 `mergedSourceTips()` 的 docstring。

判定不由"squash 合并后是否还能对上 sha"给出——平台合并（merge commit）会保留原提交，
`--is-ancestor` 即可回答；本仓的合并请求全部走 merge commit（见 `git log --merges`），
不存在 squash 形态。

## 取数（网络边界的唯一处）

本模块有两处触碰网络：`listRemoteHeads`（远端分支列表）与 `mergedSourceTips`
（主线的合并记录）。两者**只在被显式调用时发生**（`main()` 里），
常驻守卫不调它们，只比对台账与仓内事实（见 `tests/unit/ci/test_npc_branch_cleanup.py`），
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

#: 主线引用。判定「已合并」即「这个提交是不是它的祖先」。
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
    """取远端分支列表（本模块两处网络取数之一）。失败抛 `RuntimeError`，不静默空集。"""
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


def mergedSourceTips(main_ref: str = MAIN_REF) -> set:
    """主线里「作为某个合并请求的源分支头」出现过的提交集合。

    取数即主线全部 merge commit 的**第二父位**：按本仓约定（平台生成本仓全部
    合并请求，走 merge commit —— `git log --merges` 可复核），合并提交的主题形如
    `合并来自 <分支> 的合并请求 #<号>`，其第一父是主线、**第二父就是被并进来的
    那个分支当时的分支头**。所以「某分支头出现在这个集合里」＝
    「该分支正是某个已合并请求的源分支」这一**事实**本身。

    为什么不用分支名判定（本轮实测的根因）：
      先前口径把「是不是 NPC 工作分支」等同于「名字是否以 `auto/` 开头」。
      但名字是平台的产物、不是事实：平台按合并请求的 `head.ref` 决定分支名，
      NPC 会话既可以建 `auto/*`，也可以建 `fix/*` / `fix-*`。于是同一形态
      （一个已合并的归档分支仍留在远端）在一种命名下被拦、在另一种命名下被放行。
      实测：`fix-caliber-generated`（#217 的 head，作者是 NPC）已是 `origin/main`
      的祖先，而名字前缀口径给它 `keep`；同形态的 `auto/code-exec-sandbox-555c`
      （#212）则被正确判为 `stale`。

    这条事实还天然排除仓库默认分支：`main` 的头是那些 merge commit 的**后代**，
    永远不会成为其中任何一个的第二父。

    这是本模块**第二个**触碰网络的动作，与 `listRemoteHeads` 同属取数边界，
    只在显式调用时发生；常驻守卫只喂合成输入，故 CI 不因远端不可达而红。
    """
    result = subprocess.run(
        ["git", "log", "--merges", "--format=%P", main_ref],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"读取主线合并记录失败：{result.stderr.strip()[-500:]}")
    tips = set()
    for line in result.stdout.splitlines():
        parents = line.split()
        # 只认 merge commit：第一父主线、第二父源分支头；单父行（非 merge）跳过。
        if len(parents) >= 2:
            tips.add(parents[1])
    return tips


def classifyBranches(
    heads: Dict[str, str],
    mergedSourceTips: set,
    main_ref: str = MAIN_REF,
    ancestorOfMain: Optional[Dict[str, bool]] = None,
) -> List[Dict[str, object]]:
    """逐条分支判定：`keep`（在途或不由本判据裁决）/ `stale`（归档，应当删除）。

    两个 **git 事实**同时成立才算 `stale`：

    1. 该分支头出现在主线某个 merge commit 的第二父位
       （＝它正是某个已合并请求的源分支头，见 `mergedSourceTips()`）；
    2. 该分支头是 `main_ref` 的祖先（＝它的提交已在主线里，删掉不丢成果）。

    第 2 条不放宽：头不是祖先（合并后又推了新提交）仍是 `keep` —— 删掉就是丢成果。

    `ancestorOfMain` / `mergedSourceTips` 允许调用方注入判定结果，使**纯逻辑可离线
    单测**——否则测试就要依赖真远端，那是「判据随环境漂红」。不传时现算。

    早先的实现对 `main` 自己也去跑一次祖先判定，而在只拿到远端头的检出里
    `origin/main` 可能还没建（浅克隆 / 首次 fetch 前），于是判据在"不存在的东西"上
    报错——那是把环境前置条件混进判据，不是契约。新口径下 `main` 的头不会是任何
    merge commit 的第二父，故它自然落在「非归档候选」一侧，不依赖任何环境前置条件。
    """
    verdicts: List[Dict[str, object]] = []
    for name in sorted(heads):
        tip = heads[name]
        if tip not in mergedSourceTips:
            verdicts.append({"branch": name, "sha": tip, "verdict": "keep",
                             "reason": "不是任何已合并请求的源分支头，不由本判据裁决"})
            continue
        if ancestorOfMain is not None:
            merged = bool(ancestorOfMain.get(name))
        else:
            merged = isMergedIntoMain(f"{remoteRefFor(main_ref, name)}")
        verdicts.append({
            "branch": name,
            "sha": tip,
            "verdict": "stale" if merged else "keep",
            "reason": ("已合并进主线，按 AGENTS.md §0 应当立即删除"
                       if merged else "源分支已归档但分支头已前移，保留待确认"),
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
        sourceTips = mergedSourceTips()
    except RuntimeError as exc:
        print(f"取数失败：{exc}", file=sys.stderr)
        return 2

    verdicts = classifyBranches(heads, sourceTips)
    stale = staleBranches(verdicts)

    if args.json:
        print(json.dumps({
            "total_heads": len(heads),
            "merged_source_tips": len(sourceTips),
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
