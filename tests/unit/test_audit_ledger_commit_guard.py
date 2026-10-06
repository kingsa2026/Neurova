# -*- coding: utf-8 -*-
"""审计台账 commit 号必须可达（并发会话会重写历史，号会静默失效）。

判据本体在 `scripts/ci/audit_ledger_commit_guard.py`，本文件只做两件事：
① 用一条**真造的悬空 commit** 证明扫描器咬得住（防"扫描器写错→永远绿"）；
② 把常驻判定接进跑测：`audit-reports/` 里任何 `` `xxxxxxxx` `` 引用一旦不在
   HEAD 历史里就红。

为什么需要这条守卫（实测成因）：2026-10-07 一轮并发会话 rebase/merge 重写历史后，
台账里 4 个号已不可达，而 `git cat-file -e` 对它们**仍然成功**——对象还在 `.git` 里，
只是不在任何分支上。也就是说"号存在"根本证明不了"号在历史里"，读台账的人无从发现。
可达性判据只能是 `git merge-base --is-ancestor <h> HEAD`。
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# scripts/ci 无 __init__.py，按仓内既有做法走 namespace 包导入
# （tests/performance/test_perf_gate_under_node.sh / test_perf_gate_contract.py 同款）
ledger = importlib.import_module("scripts.ci.audit_ledger_commit_guard")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


@pytest.fixture
def danglingCommit() -> str:
    """造一个真实存在、但不在任何分支历史里的 commit 对象。

    用 `commit-tree` 直挂一棵空树，父指向 HEAD——它是合法 commit，`cat-file -t`
    返回 commit，却必然不可达。比"拿一个历史遗留号"稳：那种号在 `git gc` 之后
    连对象都会消失，测试会红在错误的原因上。
    """
    head = _git("rev-parse", "HEAD").strip()
    tree = _git("rev-parse", "HEAD^{tree}").strip()
    out = subprocess.run(
        ["git", "commit-tree", tree, "-p", head, "-m", "ledger-guard-dangling-probe"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert out.returncode == 0, out.stderr
    token = out.stdout.strip()[:8]
    assert ledger.isCommit(token), "探针造的对象不是 commit，判据前提不成立"
    assert not ledger.isReachable(token), "探针造的 commit 竟然可达，探针无效"
    return token


def test_scanner_flagsUnreachableReference(tmp_path, danglingCommit):
    """扫描器必须把不可达号点出来，可达号放过。"""
    report = tmp_path / "ledgerProbe.md"
    reachable = _git("rev-parse", "HEAD").strip()[:8]
    report.write_text("可达 `%s`、失效 `%s`、非号 `zzzzzzzz`\n"
                      % (reachable, danglingCommit), encoding="utf-8")

    tokens, stale = ledger.scanReport(report, ledger.headIndex())

    assert sorted(tokens) == sorted({reachable, danglingCommit}), tokens
    assert [s[0] for s in stale] == [danglingCommit], (
        "不可达号没被点出来（扫描器失灵即整条守卫恒绿）：%s" % (stale,)
    )


def test_replacementIsOfferedOnlyWhenSafe(tmp_path, danglingCommit):
    """替代号只在"同标题且 diffstat 逐行一致且唯一"时给出——否则宁可空着。"""
    report = tmp_path / "ledgerProbe2.md"
    report.write_text("`%s`" % danglingCommit, encoding="utf-8")
    _, stale = ledger.scanReport(report, ledger.headIndex())
    assert stale and stale[0][1] == "", (
        "悬空探针被赋予了替代号，说明映射没有校验标题/diffstat：%s" % (stale,)
    )


def test_auditLedger_hasNoUnreachableReference():
    """常驻判定：`audit-reports/` 全部 commit 引用必须可达 HEAD。"""
    rc = ledger.main([])
    assert rc == 0, (
        "台账存在不可达的 commit 引用（并发会话重写历史所致）——"
        "按扫描器给出的替代号回写，替代号为空的须人工判定，不得留悬空号"
    )
