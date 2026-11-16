#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""commit-msg 提交门：修复教义第 2/3 条的**提交期**落点。

判据（常驻反证在 tests/unit/ci/test_commitMsgDoctrineGate.py）：
1. feat/fix 正文必须含「红灯」与「绿灯」证据，且红灯先于绿灯（先红后绿的顺序性）；
2. 生产池净增 LOC > 0 时，正文必须含池口径的 `+N/−M` 声明**且**写明「去向」。
   数字与 numstat 的逐池相等由 tests/unit/ci/test_commitLocClaimMatchesOwnNumstat.py
   在推送窗口复算——本门只挡"没写"，不重复造第二份复算（教义第 6 条：两道判据各守一段）。
3. Merge/Revert 全豁免；docs/chore/test/style/refactor/perf/ci/build 豁免红绿
   （不新增生产行为），**不豁免** LOC 去向（教义第 2 条不分提交类型）。

用法（由 .git/hooks/commit-msg 壳调起）：commit_msg_check.py <commit-msg 文件>
退出码：0 放行；1 拒绝（stderr 点名缺什么）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: feat/fix 才强制红绿证据；其余 conventional 类型不新增生产行为，豁免红绿。
FEAT_FIX_RE = re.compile(r"^(feat|fix)(\([^)]*\))?!?:")
#: 合并与回退提交全豁免（回退笔的证据在它回退的那一笔里）。
EXEMPT_RE = re.compile(r"^(Merge |Revert )")
#: 红绿**证据段**的引导词（带冒号）。顺序判据只认这两形：正文其他位置的"红灯/绿灯"
#: 字样（动机引述"补个绿灯测试充数"、比喻等）不参与定位——首日实测首现判序把
#: 教义自己的提交说明都拒了（见 testEvidenceKeywordMentionInMotivationDoesNotDecideOrder）。
RED_EVIDENCE_RE = re.compile(r"红灯[：:]")
GREEN_EVIDENCE_RE = re.compile(r"绿灯[：:]")
#: 池口径的 LOC 声明行（词汇与 numstat 复算守卫同源：生产池/本笔/本格/净 LOC + `+N/−M`）。
LOC_CLAIM_RE = re.compile(r"(净 LOC|生产池|本笔|本格)[^\n]*\+\d+\s*/\s*[−-]\s*\d+")
#: 测试/基建路径：不计入生产池（与 numstat 复算守卫的「测试/基建池」同语义的保守近似：
#: tests/ 全根、test_*/​*_test/​*.test.*、__tests__、conftest、scripts/ci 与 scripts/githooks）。
_TEST_PATH_RE = re.compile(
    r"(^tests/|/test_[^/]*\.(py|ts)$|_test\.(py|ts)$|\.test\.[jt]sx?$"
    r"|/__tests__/|^scripts/ci/|^scripts/githooks/|/conftest\.py$)")


def productionNetFromNumstat(rows) -> int:
    """numstat 行（`adds\\tdels\\tpath`）→ 生产池净增。测试/基建与二进制行不计。"""
    net = 0
    for row in rows:
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        adds, dels, path = parts
        if not (adds.isdigit() and dels.isdigit()):
            continue  # 二进制文件是 `-	-`；畸形行跳过，不猜
        if _TEST_PATH_RE.search(path.replace("\\", "/")):
            continue
        net += int(adds) - int(dels)
    return net


def check(message: str, productionNet: int) -> list:
    """返回违规清单（空＝放行）。productionNet 是暂存区生产池净增行数。"""
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    body = message[len(subject):] if subject else message
    violations = []
    if EXEMPT_RE.match(subject):
        return violations
    if FEAT_FIX_RE.match(subject):
        red, green = RED_EVIDENCE_RE.search(body), GREEN_EVIDENCE_RE.search(body)
        if not red:
            violations.append(
                "缺「红灯」证据：先写断言缺陷的失败测试并实证它真的红，把失败输出原文贴进正文（AGENTS.md §1 教义第 3 条）")
        if not green:
            violations.append(
                "缺「绿灯」证据：把最小实现转绿的实测输出贴进正文（AGENTS.md §1 教义第 3 条）")
        if red and green and red.start() > green.start():
            violations.append(
                "「绿灯」写在「红灯」前面——先红后绿，顺序反了的证据不算数（AGENTS.md §1 教义第 3 条）")
    if productionNet > 0:
        if not LOC_CLAIM_RE.search(body):
            violations.append(
                f"生产池净增 +{productionNet} 行，正文却没有池口径的 +N/−M 声明——"
                "补「净 LOC：生产池 +N/−M」一段（AGENTS.md §1 教义第 2 条）")
        if "去向" not in body:
            violations.append(
                f"生产池净增 +{productionNet} 行，正文没写「去向」——逐条列明新增行数花在哪（AGENTS.md §1 教义第 2 条）")
    return violations


def _stagedNumstat(repo: Path) -> list:
    """暂存区 numstat。取数失败必须报错，不许静默当空（教义第 2 条：不吞失败）。"""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--numstat"], cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git diff --cached --numstat 失败（exit {proc.returncode}）：{proc.stderr.strip()}")
    return proc.stdout.splitlines()


def main(argv) -> int:
    if len(argv) != 2:
        print("用法：commit_msg_check.py <commit-msg 文件>", file=sys.stderr)
        return 1
    message = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    repo = Path(__file__).resolve().parents[2]
    net = productionNetFromNumstat(_stagedNumstat(repo))
    violations = check(message, productionNet=net)
    if violations:
        print("[提交门] 这一笔没过修复教义（AGENTS.md §1），拒绝提交：", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        print("  （逃生门只有 git 本身的 --no-verify：平台级手段，用了必须在 PR 里说明偏离点）",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))
