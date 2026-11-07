#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计台账 commit 号可达性扫描器（判据唯一出处，守卫与人共用）。

为什么要有这个扫描器：`audit-reports/*.md` 与 `docs/**/*.md` 都以 commit 号（裸写或 `` `xxxxxxxx` ``
两种写法同等）引用提交，而并发会话的 rebase / merge 会**重写历史**——号对应的对象仍留在 `.git` 里，
于是 `git cat-file -e` 照样成功，但那个号已经不在任何分支历史上了。只查"对象存在"
证明不了"号还在"，台账会长期指向不在历史里的提交，而读的人无从发现。

认号的口径**不绑 markdown 语法**：要求反引号等于把判据的生效与否交给「别人怎么写」——
实测一次连反引号一起替换的批量回写，就让识别数从 1150 枚掉到 5 枚而全档照绿。

可达性判据：`git merge-base --is-ancestor <h> HEAD`。
替代号判据：同标题 **且** `git show --numstat` 逐行一致，且唯一——只凭标题相同就替换
不安全（遇到"同题重做"会张冠李戴），不满足则宁可留空由人工判定。

扫描面（`SCAN_DIRS`）在**调用期**从仓根派生：绝对路径若在 import 时冻进常量，
换根不生效，守卫与真仓脱钩的那一刻只有生产装配点知道（§6-477）。docs 必须**递归**——
实测引用落在 `docs/03-user-guide/i18n/` 这类嵌套档里，只扫一层等于没扩面。
`isCommit` 预筛是扩面不假红的前提：docs 面实测 274 枚十六进制串根本不是 commit（树号、
对象 ID、色值残片），撤掉预筛它们会整批以「不可达」名义报红。

性能口径（§6-495）：一趟 `git log --format=%H%x09%h%x09%s HEAD` 同时供起「HEAD 祖先全号集合」
与「替代号索引」，可达性在内存里判；`git rev-list --all` 只多取一次，专门用来识短号前缀歧义。
diffstat 只对同标题候选计算。这已经是第二次返工：最早逐提交起 `git log`/`git show`，在万级仓库
直接超时；上一版改成逐号起 `git merge-base`（实测一场 79.38s），本质仍是把 O(号数) 当成本。

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
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: 扫描面唯一出处（相对仓根的目录，均递归）。
SCAN_DIRS = ("audit-reports", "docs")
#: 引用形态：**不要求反引号**。裸写与 `` `xxxxxxxx` `` 两种写法同等对待——可达性判据一旦绑在
#: markdown 语法上，任何人改掉引用写法就能让整台守卫静默空转。实测现场：11-04 11:03 那笔
#: 「台账号面随批回写」把整枚 `` `旧号` `` 连反引号一起替换成裸新号，识别数从该笔之前的
#: 现算 1150 枚（台账 882 ＋ docs 268）塌到 5 枚，而当天三档在册闸 31 passed。
#: 界只禁十六进制邻接（长号的一段不算独立引用），不禁反引号本身。
REF_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{8,40})(?![0-9a-f])")
HEX_ONLY = re.compile(r"^[0-9a-f]{8,40}$")
#: 已判定过的不可达号清单——例外只在这一份里署名，不在判据代码里另开一份（教义第 6 条）。
EXCEPTIONS_REL = ("scripts", "ci", "audit_ledger_unreachable_refs.txt")

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


def _objectType(token: str) -> str:
    """对象类型（`commit` / `tree` / `blob` / 空串=本仓没有这个对象）。"""
    if token not in _objectTypeCache:
        _objectTypeCache[token] = _git("cat-file", "-t", token).strip()
    return _objectTypeCache[token]


def isCommit(token: str) -> bool:
    if token not in _objectTypeCache:
        _objectTypeCache[token] = _git("cat-file", "-t", token).strip()
    return _objectTypeCache[token] == "commit"


#: 一次性取数缓存（§6-495）。旧形态是**逐号**起 `git merge-base --is-ancestor`——扫描面里
#: 有多少枚 commit 引用就起多少次进程，实测一场 79.38s（§6-477 扩面后）。一次 `git log`
#: 就能拿回 HEAD 的全部祖先全号（本仓 3428 个提交），集合建在内存里判即可。
#: ⚠ 缓存是**进程级**的：守卫是一次性脚本，跑测里同场多格共用一趟取数正是省时间的来源；
#: 若将来把它做成常驻服务，得先问"HEAD 会不会在一场内移动"，别拿旧读数当新事实。
_headLogRowsCache: "list | None" = None
_ancestorCache: "frozenset | None" = None
_otherRefCache: "frozenset | None" = None
_prefixBuckets: dict = {}


def _headLogRows() -> list:
    """一次 `git log` 同时取回 (全号, 短号, 标题)——祖先集合与替代号索引共用这一趟。"""
    global _headLogRowsCache
    if _headLogRowsCache is None:
        rows = []
        for line in _git("log", "--format=%H%x09%h%x09%s", "HEAD").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and HEX_ONLY.match(parts[0]):
                rows.append((parts[0], parts[1], "\t".join(parts[2:]).strip()))
        _headLogRowsCache = rows
    return _headLogRowsCache


def ancestorHashes() -> frozenset:
    """HEAD 的全部祖先全号（含 HEAD 自身）。"""
    global _ancestorCache
    if _ancestorCache is None:
        _ancestorCache = frozenset(full for full, _short, _subj in _headLogRows())
    return _ancestorCache


def otherRefHashes() -> frozenset:
    """挂在别的 ref 上、却不在 HEAD 历史里的全号——**只用来识别短号前缀歧义**。"""
    global _otherRefCache
    if _otherRefCache is None:
        others = frozenset(h for h in _git("rev-list", "--all").split() if HEX_ONLY.match(h))
        _otherRefCache = others - ancestorHashes()
    return _otherRefCache


def _prefixSet(names, length: int) -> set:
    """按号长分桶的前缀集合（桶只在被问到那一刻建，一次建、多次用）。"""
    key = (id(names), length)
    bucket = _prefixBuckets.get(key)
    if bucket is None:
        bucket = {h[:length] for h in names if len(h) >= length}
        _prefixBuckets[key] = bucket
    return bucket


def reachabilityDecides(token: str, ancestorPrefixes: set, otherPrefixes: set) -> bool:
    """判定本体——具名纯函数，只收**前缀集合**，好让"歧义"这条语义能被单独证伪。

    规则：**前缀落在祖先里、且不与别的 ref 上的对象撞前缀**才算可达。撞前缀时
    `git merge-base --is-ancestor` 自己就会因短号歧义拒绝解析（= 判不可达），
    内存判若只看祖先集合会把它读成"可达"——判据可以变便宜，**不许比 git 更宽松**。

    取数与缓存留在上游 `isReachable()`：判定只有一份、缓存也只有一份（教义第 6 条）。
    """
    token = str(token).strip()
    if not token:
        return False
    return token in ancestorPrefixes and token not in otherPrefixes


def batchProbe(tokens) -> None:
    """一次 `git cat-file --batch-check` 把整批候选的类型填进缓存（§6-495 第二处命中点）。

    为什么必须有这一处：`isCommit()` 逐号起进程，本仓扫描面里唯一候选号 1232 枚 ⇒ 实测一场
    光这一件事就 1254 次 fork。`--batch-check` 对每个输入行**恰好输出一个行**（`<全号> <类型>
    [<size>]`，不存在的对象输出 `<输入> missing`），所以按顺序 zip 就能回填，不必解析行首号——
    按号匹配反而会错：请求的是 8 位短号，回的是 40 位全号。
    """
    pending = [t for t in tokens if t not in _objectTypeCache]
    if not pending:
        return
    proc = subprocess.run(["git", "cat-file", "--batch-check"],
                          input="\n".join(pending) + "\n",
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=GIT_WALL_S)
    lines = proc.stdout.splitlines()
    for index, token in enumerate(pending):
        parts = lines[index].split() if index < len(lines) else []
        # `missing` 不是对象类型，统一记成空串：`isCommit` 只认 "commit"，其余一律不进判据面
        _objectTypeCache[token] = "" if (not parts or parts[-1] == "missing") else parts[1]


def isReachable(token: str) -> bool:
    token = str(token).strip()
    length = len(token)
    return reachabilityDecides(token,
                               _prefixSet(ancestorHashes(), length),
                               _prefixSet(otherRefHashes(), length))


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
    """[(短号, 标题)]——不可逐提交再起进程（万级仓库会超时）。

    取数与祖先集合**共用同一趟 `git log`**（`_headLogRows()`）：两条判据原来各起一次，
    等于把同一份历史读两遍（教义第 6 条：一次取数一处存）。
    """
    return [(short, subj) for _full, short, subj in _headLogRows()]


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


def scanDirs() -> List[Path]:
    """扫描面目录**调用期**从仓根派生；目录清单的唯一出处是 `SCAN_DIRS`。"""
    return [PROJECT_ROOT / name for name in SCAN_DIRS]


def markdownFiles(base: Path) -> List[Path]:
    """该目录树下的 markdown，**递归**——docs 的 commit 引用实测藏在嵌套目录里。"""
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def displayName(path: Path) -> str:
    """相对仓根的 posix 路径：两棵树里的同名档必须能看出是谁。"""
    return path.relative_to(PROJECT_ROOT).as_posix()


def exceptionsPath() -> Path:
    """例外清单路径**调用期**从仓根派生——与 `scanDirs()` 同一个道理：挂假仓根得真生效。"""
    return PROJECT_ROOT.joinpath(*EXCEPTIONS_REL)


def signedExceptions() -> dict:
    """{短号: 理由}。注释行与空行不算条目；清单不存在即空例外（不放行任何号）。"""
    path = exceptionsPath()
    if not path.is_file():
        return {}
    signed = {}
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        token, _, reason = line.partition(" ")
        signed[token.strip()] = reason.strip()
    return signed


def scanReport(path: Path, index: list, signed=frozenset()):
    """返回 (该报告引用的 commit 号列表, [(失效号, 替代号)])。

    `signed` 里的号仍算**引用**（识别数不许因例外而虚低），但不再逐枚去凑替代号——
    那件事已经人工做过一次并署名了，机器重复付钱没有意义。
    """
    text = io.open(path, encoding="utf-8", errors="replace").read()
    candidates, seen = [], set()
    for match in REF_RE.finditer(text):
        if not HEX_ONLY.match(match.group(1)):
            continue
        short = match.group(1)[:8]
        if short in seen:
            continue
        seen.add(short)
        candidates.append(short)
    batchProbe(candidates)          # 一次进程问完整批；逐号 fork 是这场扫描的成本主体
    tokens = [short for short in candidates if isCommit(short)]
    stale = [(t, findReplacement(t, index)) for t in tokens
             if not isReachable(t) and t not in signed]
    return tokens, stale


def main(argv=None) -> int:
    # Windows 宿主默认 cp936：本脚本会 print 中文与箭头，出口不钉 utf-8 就会在一句 print 上
    # 抛 UnicodeEncodeError、退出码 1，让"红"指向脚本自己而不是被测行为（§6-496）。
    # 放在 main 里而不是模块级：这几档会被 pytest 以 importlib 加载，模块级钉等于改宿主进程。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="审计台账 commit 号可达性")
    parser.add_argument("--porcelain", action="store_true",
                        help="每行 `<报告>|<失效号>|<替代号>`，供守卫比对")
    args = parser.parse_args(argv)

    index = headIndex()
    signed = signedExceptions()
    batchProbe(sorted(signed))
    totalRefs, staleRows = 0, []
    for base in scanDirs():
        for report in markdownFiles(base):
            tokens, stale = scanReport(report, index, signed)
            totalRefs += len(tokens)
            for bad, repl in stale:
                staleRows.append((displayName(report), bad, repl))
            if not args.porcelain:
                print("%-46s 引用 %3d 个号，失效 %d"
                      % (displayName(report), len(tokens), len(stale)))
                for bad, repl in stale:
                    print("    失效 %s%s" % (bad, "  → 可回写为 " + repl if repl
                                             else "  （无可安全回写的替代号）"))

    # 例外清单的第二个方向：署过名不等于永远成立。号若**已回到主线**，这一行就是过期
    # 署名——留着它，下次真有号失联也没人能看出来。
    #
    # 但「本机压根没有这个对象」是另一件事，不能读成「署名过期」：例外清单署名的号
    # 本就是被并发重写带走的对象，CI 检出的是**远端当前历史**——那批对象在远端早已被
    # gc，本机一个字节都取不到。旧写法把这种"取不到"判成"过期"，于是同一条清单
    # 本机（对象还在 .git 里）绿、CI 红，而 CI 给的修法是"把这行删了"——那是拿
    # 抹掉证据换绿，正是教义第 2 条禁止的形态。
    # 判据改为：**对象存在**且（不是 commit 或已可达）才算过期署名；对象不存在时
    # 本仓对这件事没有发言权，如实不计。
    retired = sorted(t for t in signed if _objectType(t) and (not isCommit(t) or isReachable(t)))
    if args.porcelain:
        for row in staleRows:
            print("|".join(row))
        for token in retired:
            print("|".join(("<例外清单>", token, "该行已不成立，须删除")))
    if retired:
        print("例外清单里有 %d 行已不成立（号已可达或已不是 commit），该行须删除：%s"
              % (len(retired), " ".join(retired)), file=sys.stderr)
    if staleRows or retired:
        print("失效引用 %d 条 / 共 %d 条引用（扫描面 %s，例外清单署名 %d 条）"
              % (len(staleRows), totalRefs, " + ".join(SCAN_DIRS), len(signed)),
              file=sys.stderr)
        return 1
    print("commit 号全部可达（共 %d 条引用，扫描面 %s，例外清单署名 %d 条）"
          % (totalRefs, " + ".join(SCAN_DIRS), len(signed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
