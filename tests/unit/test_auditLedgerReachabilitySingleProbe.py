# -*- coding: utf-8 -*-
"""可达性探测必须**一次性建集合再内存判**（§6-495；§6-414 挂了很久的那一票）。

现装形态（本批修前实测）：`scripts/ci/audit_ledger_commit_guard.py` 的 `isReachable()` 对
**每一个号**起一次 `git merge-base --is-ancestor`，`isCommit()` 又对**每一个候选号**起一次
`git cat-file -t`——扫描面里有多少枚 commit 引用就起多少次进程，一场 **79.38s**
（§6-477 把面从一棵树扩到两棵树之后；扩面前单树 48.64s）。这笔成本只买到"号还在不在历史里"
一个比特。

一次 `git log --format=%H HEAD` 就能拿到 HEAD 的全部祖先全号（本仓 3428 个提交，0.1s 量级），
把它做成集合在内存里判，进程调用从 O(号数) 降到常数。**但内存判有一条真风险**：短号前缀歧义。
`git merge-base` 遇到"同一前缀解析到两个对象"会直接报错（= 判不可达），而"祖先集合里有且只有一个
匹配"读起来像可达——另一个同前缀对象可能挂在别的 ref 上而不在 HEAD 历史里。⇒ 本格第 3 格钉死
「歧义一律保守判不可达」，不许因为"碰撞概率极低"就猜。

四格分工：
① 扫描一场里**不许再出现逐号 `merge-base`**（主格，红在调用次数上，不红在时间上——时间读数
   在 CI 上抖，判据不能靠它）；
② 一次性建集合：探测类 git 调用数不随号数增长（同一场扫描只取一次祖先集合）；
③ 前缀歧义必须判不可达（把判定抽成可注入的纯函数，喂合成集合验语义，不依赖真 git）；
④ 反向钉：真造的悬空 commit 仍必须判不可达——省了进程调用不许把语义弄松。
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ledger = importlib.import_module("scripts.ci.audit_ledger_commit_guard")

#: 与守卫档同一口径的父墙（唯一出处见 `test_audit_ledger_commit_guard.py`）。本批把逐号 fork
#: 收掉后一场实测 2.5–3.5s，故两边一起收到 60——降成本不顺手收墙，等于把宽墙留给下一次回归。
SCAN_WALL_S = 60

#: 本档每一次 `subprocess.run` 的**子等待上界**（必须严格小于上面的父墙，同 §6-402 口径）：
#: 无界的那一层先到点时，Windows 侧 thread 法报的是"整场跑测没了"，而不是这一格红。
CHILD_WAIT_S = 30


class _RunSpy:
    """只给 `ledger.subprocess` 用的替身：记命令，真调用照旧。

    换的是 **ledger 模块命名空间里的 subprocess 名字**，不是全局 `subprocess.run`——
    后者会把 pytest 自己的进程调用一起记进账，读数就成了别人的噪声。
    """

    def __init__(self):
        self.calls = []

    def run(self, *args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, (list, tuple)):
            self.calls.append([str(part) for part in cmd])
        # 父墙一降，这层"没带上界的转发"就是无界等待的洞。先 pop 再显式传：既不让 timeout
        # 与被测方自己传的重复（那是 TypeError），也让常驻闸能在 AST 里看到这个关键字——
        # 它按关键字认上界，不认运行期默认值。
        timeout = kwargs.pop("timeout", None) or CHILD_WAIT_S
        return subprocess.run(*args, timeout=timeout, **kwargs)


@pytest.fixture(scope="module")
def oneScan():
    """真扫全仓**一次**，四格共用同一份调用记录。

    首版写成 function 级，于是"共用一次扫描"只写在 docstring 里：实测四格各扫一场，
    红灯那轮跑了 `329.42s`——判据自己成了这场扫描成本的四倍来源。手工 setattr/还原而不是
    用 `monkeypatch`，因为 `monkeypatch` 是 function 级夹具，module 夹具里拿不到它。
    """
    spy = _RunSpy()
    realSubprocess = ledger.subprocess
    ledger.subprocess = spy
    for cache in ("_objectTypeCache", "_numstatCache"):
        getattr(ledger, cache).clear()
    buf = []
    realWrite = sys.stdout.write
    sys.stdout.write = lambda text: (buf.append(text), len(text))[1]
    try:
        rc = ledger.main([])
    finally:
        sys.stdout.write = realWrite
        ledger.subprocess = realSubprocess
    return rc, spy.calls, "".join(buf)


def _shellsNamed(calls, *words):
    return [c for c in calls if len(c) > 1 and c[0] == "git" and any(w in c[1] for w in words)]


@pytest.mark.timeout(SCAN_WALL_S)
def test_reachabilityDoesNotShellOutPerNumber(oneScan):
    """主格：一场扫描里 `git merge-base` 的调用次数必须是 0。"""
    _rc, calls, _out = oneScan
    mergeBases = _shellsNamed(calls, "merge-base")
    cited = _shellsNamed(calls, "cat-file")
    assert mergeBases == [], (
        "可达性仍逐号起 `git merge-base`（本场 %d 次、号探测 %d 次）——"
        "一次 `git log --format=%H HEAD` 就能把 HEAD 祖先全部取回，"
        "逐号起进程是这场扫描 79s 的唯一来源" % (len(mergeBases), len(cited)))


@pytest.mark.timeout(SCAN_WALL_S)
def test_ancestorSetIsTakenOncePerScan(oneScan):
    """第 2 格：祖先集合的 git 取数与号数无关（常数级，不许随引用数增长）。"""
    _rc, calls, _out = oneScan
    probes = _shellsNamed(calls, "log", "rev-list")
    assert len(probes) <= 4, (
        "探测类 git 调用有 %d 次——一次性建集合的口径是常数级（祖先集 + 全库集），"
        "每个号各取一次就是 §6-414 那笔没做完" % len(probes))


@pytest.mark.timeout(SCAN_WALL_S)
def test_objectTypeProbeShellsOutOnceNotPerNumber(oneScan):
    """同一条根因的第二处命中点：`isCommit()` 也**逐号**起 `git cat-file -t`。

    本格是第一版漏掉的：那时我只把 `merge-base` 收进内存就以为完事，实测一场仍要 40.5s——
    因为 1232 枚候选号各自起了一次 cat-file。"逐号起进程"这件事在同一个文件里有**两个**
    命中点，只扫荡一个就是把教义第 5 条做了一半。正解是一次 `git cat-file --batch-check`
    把全部候选喂进去。
    """
    _rc, calls, _out = oneScan
    probes = [c for c in calls if len(c) > 1 and c[0] == "git" and c[1] == "cat-file"
              and "--batch-check" not in c]
    assert len(probes) <= 2, (
        "对象类型探测仍逐号起进程（本场 %d 次）——一次 `git cat-file --batch-check` 就够；"
        "判据不许把'每个号问一次'当成正常成本" % len(probes))


@pytest.mark.timeout(SCAN_WALL_S)
def test_ambiguousPrefixIsNeverGuessedReachable(oneScan):
    """第 3 格：前缀同时落在"祖先"与"非祖先对象"上时必须判**不可达**。

    `git merge-base --is-ancestor` 在这种情况下自己就会拒绝解析；内存判若只看祖先集合，
    会把这条读成"可达"——那是把保守判断换成运气（本仓口径：宁可空着由人判，不许猜）。
    """
    probe = getattr(ledger, "reachabilityDecides", None)
    assert probe is not None, (
        "守卫里没有具名纯函数 `reachabilityDecides(token, ancestors, others)`——"
        "判定与取数搅在一起时，歧义这条语义没法单独证伪")
    ancestorPrefixes = {"a" * 8, "b" * 8}
    otherPrefixes = {"a" * 8}     # 同一 8 位前缀上，还有一个不在 HEAD 历史里的对象
    assert probe("a" * 8, ancestorPrefixes, otherPrefixes) is False, (
        "前缀歧义被判成可达——内存版比 git 本身更宽松，这是假绿")
    assert probe("b" * 8, ancestorPrefixes, otherPrefixes) is True, "无歧义的祖先前缀应判可达"
    assert probe("c" * 8, ancestorPrefixes, otherPrefixes) is False, "不在祖先集合里的号必须判不可达"
    assert probe("", ancestorPrefixes, otherPrefixes) is False, "空号不许判可达"


@pytest.mark.timeout(SCAN_WALL_S)
def test_danglingCommitStillJudgedUnreachable(oneScan, danglingCommit):
    """第 4 格（反向钉）：省调用不许把语义弄松——真造的悬空 commit 必须仍判不可达。"""
    _rc, _calls, _out = oneScan
    assert ledger.isCommit(danglingCommit), "探针对象不是 commit，本格前提不成立"
    assert not ledger.isReachable(danglingCommit), (
        "悬空 commit 在新探测下被判可达——可达性守卫从此对重写历史失去牙齿")
    assert ledger.isReachable(_gitHead8()), "HEAD 自身的号被判不可达，祖先集合取错了"


def _runGit(*args: str) -> str:
    """本档 git 读数的唯一出口：必带 `timeout=`。

    父墙收到 60 之后，这些"没带上界的子等待"就是常驻闸
    `test_nestedPytestBudgetWallsAreOrdered.py` 点名的那一形——无界的那一层先到点时，
    Windows 侧 thread 法报的是"整场跑测没了"，而不是这一格红（§6-402 口径）。
    """
    proc = subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(PROJECT_ROOT), timeout=CHILD_WAIT_S)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _gitHead8() -> str:
    return _runGit("rev-parse", "HEAD").strip()[:8]


@pytest.fixture()
def danglingCommit() -> str:
    """与守卫档同法造一枚真实存在、但不在任何分支历史里的 commit。"""
    head = _runGit("rev-parse", "HEAD").strip()
    tree = _runGit("rev-parse", "HEAD^{tree}").strip()
    return _runGit("commit-tree", tree, "-p", head,
                   "-m", "reachability-probe-dangling").strip()[:8]
