# -*- coding: utf-8 -*-
"""审计台账 commit 号必须可达（并发会话会重写历史，号会静默失效）。

判据本体在 `scripts/ci/audit_ledger_commit_guard.py`，本文件只做三件事：
① 用一条**真造的悬空 commit** 证明扫描器咬得住（防"扫描器写错→永远绿"）；
② 把常驻判定接进跑测：扫描面（`audit-reports/` + `docs/`）里任何 `` `xxxxxxxx` ``
   引用一旦不在 HEAD 历史里就红；
③ 钉住**扫描面本身**——面若被缩小（只扫台账、或 docs 只扫平铺一层、或路径在 import
   时冻成写死的绝对目录），上面两件事会安静地变成"对已经不存在的档全绿"。

为什么需要这条守卫（实测成因）：2026-10-07 一轮并发会话 rebase/merge 重写历史后，
台账里 4 个号已不可达，而 `git cat-file -e` 对它们**仍然成功**——对象还在 `.git` 里，
只是不在任何分支上。也就是说"号存在"根本证明不了"号在历史里"，读台账的人无从发现。
可达性判据只能是 `git merge-base --is-ancestor <h> HEAD`。
"""

import contextlib
import importlib
import io
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


def _runMain(argv):
    """调生产 `main()` 并取回它的 stdout——扫描面「到底扫了谁」只能从出口读。

    不用 capsys：本文件的会话级夹具与模块级缓存都要在同一次真实扫描上复用同一份出口。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ledger.main(argv)
    return rc, buf.getvalue()

#: 本档两枚 git 落点（rev-parse / commit-tree）的预算唯一出处，毫秒级。取**低于全局 30s**
#: 的这一形，且此前两处根本没有 `timeout=`——无界等待配 thread 法全局墙时，先到点的那一层
#: 报的是"整场跑测没了"（§6-402 批 K 口径）。
GIT_WALL_S = 20


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=GIT_WALL_S).stdout


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
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=GIT_WALL_S)
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


#: 本轮扫描的父墙（唯一出处）。**实测一场 2.5–3.5s**（§6-495 之后）：可达性改成一次
#: `git log` 取回祖先全号内存判、对象类型改成一次 `git cat-file --batch-check` 问完整批，
#: 两条"逐号起进程"都没了。历史读数 48.64s（单树逐号 merge-base）→ 79.38s（§6-477 扩到
#: 两棵树）→ 2.5s（本批）。
#:
#: 墙从 180 收到 **60** 是这笔降成本的验收项：留着 180 等于把"合法超墙"的记账留在一个已经不
#: 存在的问题上，而下一次真变慢时，宽墙会把回归读成正常。余量仍是实测的 17 倍——这台机器上
#: git 进程调度的抖动比代码变化大。
#:
#: 常驻闸 `test_nestedPytestBudgetWallsAreOrdered.py` 看不见这一处：它的边界写明「只在
#: 同文件闭包内认落点」，而真正阻塞的那次 subprocess 在 `scripts/ci/audit_ledger_commit_guard.py`
#: 里（批 P-2 的归账面）。故这里按 §6-402 同一口径把父墙显式声明上。
LEDGER_SCAN_WALL_S = 60


@pytest.fixture(scope="module")
def realScan():
    """真仓根**只扫一次**，供「扫描面覆盖」与「无悬空号」两格共用。

    全仓扫描是几十秒级（逐号一次 git），逐格复算等于把同一笔成本付两遍；
    共用一份出口读数后，两格判的是同一场的同一事实。
    """
    return _runMain([])


@pytest.mark.timeout(LEDGER_SCAN_WALL_S)
def test_scanSurfaceCoversLedgerAndDocsTrees(realScan):
    """扫描面必须含 `docs/` 树下的档，且是**递归**进去的。

    为什么 docs 也要进面：文档同样以 `` `xxxxxxxx` `` 引 commit 号，而并发会话重写历史
    不挑目录——台账侧 §6-468 已量过 0 悬空，docs 侧此前**从未被核验过**（本批实测 268 对
    引用、0 不可达 ⇒ 扩面第一天 0 红，所以这道判据只会因"面被缩小"而红，不会因存量而红）。
    """
    rc, out = realScan
    scanned = [line.strip().split(" ")[0] for line in out.splitlines() if "引用" in line]
    docsDeep = [p for p in scanned if p.startswith("docs/") and "/" in p[len("docs/"):]]
    assert any(p.startswith("audit-reports/") for p in scanned), (
        "扫描面里连台账目录都没有：%s" % (scanned[:3],))
    assert docsDeep, (
        "扫描面没进 docs 树的深层目录——`docs/*.md` 只扫平铺一层就等于没扩面"
        "（实测引用落在 docs/03-user-guide/i18n/ 这类嵌套档里）；当前扫到 %d 档：%s"
        % (len(scanned), scanned[:3]))


@pytest.mark.timeout(LEDGER_SCAN_WALL_S)
def test_auditLedger_hasNoUnreachableReference(realScan):
    """常驻判定：扫描面内全部 commit 引用必须可达 HEAD。"""
    rc, _ = realScan
    assert rc == 0, (
        "台账存在不可达的 commit 引用（并发会话重写历史所致）——"
        "按扫描器给出的替代号回写，替代号为空的须人工判定，不得留悬空号"
    )


@pytest.mark.timeout(LEDGER_SCAN_WALL_S)
def test_scanDirsComeFromRepoRootAtCallTime(tmp_path, monkeypatch, danglingCommit):
    """扫描面得在**调用期**从仓根派生：挂一个假仓根，两棵目录树的悬空号都要被点到。

    这一格同时钉两件曾被导入期常量悄悄做错的事：①目录集合写死成单个 `audit-reports`；
    ②绝对路径在 import 时就冻结（改根不生效 ⇒ 守卫与真仓脱钩，只在生产装配点坏时才发现）。
    """
    (tmp_path / "audit-reports").mkdir()
    deep = tmp_path / "docs" / "03-user-guide" / "i18n"
    deep.mkdir(parents=True)
    reachable = _git("rev-parse", "HEAD").strip()[:8]
    (tmp_path / "audit-reports" / "ledgerProbe.md").write_text(
        "失效 `%s`\n" % danglingCommit, encoding="utf-8")
    (deep / "guideProbe.md").write_text(
        "可达 `%s`、失效 `%s`\n" % (reachable, danglingCommit), encoding="utf-8")
    monkeypatch.setattr(ledger, "PROJECT_ROOT", tmp_path)

    rc, out = _runMain([])

    assert "audit-reports/ledgerProbe.md" in out, (
        "假仓根下的台账树没进扫描面（挂根不生效＝路径在导入期就冻住了）：%s" % out)
    assert "docs/03-user-guide/i18n/guideProbe.md" in out, (
        "假仓根下 docs 的深层档没进扫描面——扩面若只到 `docs/*.md` 一层，"
        "真仓里绝大多数引用仍然无人核验：%s" % out)
    assert rc == 1, (
        "两棵树里的悬空号都没让判定变红，扫描器在新面上恒绿：%s" % out)


def test_nonCommitHexTokensAreNotTreatedAsReferences(tmp_path):
    """反引号里的十六进制串未必是 commit——`isCommit` 预筛是扩面不假红的前提。

    实测 docs 面有 274 枚这样的串（树号、对象 ID、色值残片）。撤掉预筛的那一刻，
    它们整批以「不可达」名义报红，而红的是判据自己，不是历史。
    """
    treeToken = _git("rev-parse", "HEAD^{tree}").strip()[:8]
    report = tmp_path / "notACommit.md"
    report.write_text("`%s`、`ffffffff`、`zzzzzzzz`\n" % treeToken, encoding="utf-8")
    assert not ledger.isCommit(treeToken), "探针选中的竟是 commit，本格的反向前提不成立"

    tokens, stale = ledger.scanReport(report, ledger.headIndex())

    assert tokens == [], "非 commit 形态的十六进制串被当成了引用：%s" % (tokens,)
    assert stale == []
