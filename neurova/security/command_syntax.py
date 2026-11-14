"""语法级命令分析——guarded 危险命令门与只读 argv 白名单（P1-3）。

对照 ZCode guarded 模式的两条经验：
- 危险命令用 **argv 语法结构**判定（动词+旗标组合），不是对原始字符串做黑名单
  正则——`rm  -r`（多空格）、`rm --recursive`、引号包裹的路径都逃不掉；
- 只读命令靠 argv 级白名单免审批，扩大无人值守面。

三类判定（按序）：
1. DESTRUCTIVE——语法结构即危险：递归删除、git 破坏性子命令、系统级命令、
   Windows/PowerShell 删除、find -delete/-exec rm、chmod 777 等；
2. READONLY——动词在只读白名单且无输出重定向（`>`/`>>` 即失格）；
3. UNKNOWN——其余（含 python/node 等执行型动词）。

本模块只做纯分析，不裁决；消费方是 governance.evaluate（危险命令审批先于
白名单放行）与只读自动放行设置项。
"""

from __future__ import annotations

import enum
import shlex
from dataclasses import dataclass
from typing import Iterable


class ArgvClass(str, enum.Enum):
    READONLY = "readonly"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ArgvVerdict:
    classification: ArgvClass
    reason: str
    verb: str


@dataclass(frozen=True)
class SegmentAnalysis:
    text: str
    argv: tuple
    verdict: ArgvVerdict


@dataclass(frozen=True)
class CommandAnalysis:
    segments: tuple

    @property
    def destructiveHits(self) -> tuple:
        return tuple(s for s in self.segments if s.verdict.classification == ArgvClass.DESTRUCTIVE)

    @property
    def allReadonly(self) -> bool:
        return bool(self.segments) and all(
            s.verdict.classification == ArgvClass.READONLY for s in self.segments
        )


#: 输出重定向记号：出现即丧失只读资格（写文件系统）
_OUTPUT_REDIRECT_TOKENS = frozenset({">", ">>"})

#: rm/ri 家族的递归删除旗标（小写比较；-r 前缀族一律算递归）
_RECURSIVE_DELETE_FLAGS = ("-r", "-rf", "-fr", "-ri", "-ir", "-rd", "-dr", "--recursive")

#: 只读动词白名单（git/npm/pip 等带子命令的动词在 _classify_special 内另判）
_READONLY_VERBS = frozenset({
    "ls", "ll", "la", "pwd", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg",
    "less", "more", "wc", "sort", "uniq", "cut", "file", "stat", "du", "df", "ps",
    "id", "whoami", "groups", "uname", "hostname", "date", "which", "whereis",
    "env", "printenv", "locale", "free", "uptime", "seq", "basename", "dirname",
    "realpath", "md5sum", "sha256sum", "cksum", "test", "type", "echo", "printf",
    "find", "git", "npm", "pip",
})

#: 系统级/不可逆命令动词：命中即危险
_DESTRUCTIVE_VERBS = frozenset({
    "dd", "fdisk", "sfdisk", "parted", "shutdown", "reboot", "halt", "poweroff",
    "telinit", "truncate", "shred",
})

#: git 只读子命令（checkout/restore/clean 等破坏性子命令在危险规则里先判）
_GIT_READONLY_SUBS = frozenset({
    "status", "log", "diff", "show", "blame", "rev-parse", "ls-files", "describe",
    "remote", "tag", "branch", "grep", "cat-file", "ls-remote", "shortlog",
})


def tokenizeArgv(text: str) -> tuple:
    """把一段 shell 命令切成 argv；引号内空格不切分，引号不平衡退化为按空白切。"""
    try:
        parts = shlex.split(text, posix=True)
    except ValueError:
        parts = text.split()
    return tuple(p for p in parts if p)


def _flags(argv: Iterable[str]) -> tuple:
    return tuple(a for a in argv if a.startswith("-"))


def _hasRecursiveDelete(argv) -> bool:
    return any(
        f.lower() in _RECURSIVE_DELETE_FLAGS or f.lower().startswith("--recursive")
        for f in _flags(argv[1:])
    )


def _classifyGit(argv) -> ArgvVerdict:
    sub = (argv[1] if len(argv) > 1 else "").lower()
    rest = argv[2:] if len(argv) > 2 else ()
    flagLetters = [set(f.lower().lstrip("-")) for f in _flags(rest)]
    if sub == "push" and any(
        f.lower() in {"-f", "--force", "-ff"} or f.lower().startswith("--force")
        for f in rest
    ):
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "git push 强制推送", "git")
    if sub == "reset" and "--hard" in [f.lower() for f in rest]:
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "git reset --hard 丢弃工作区", "git")
    if sub == "clean" and any(letters & {"f", "x"} for letters in flagLetters):
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "git clean 强制清理", "git")
    if sub in {"branch", "tag"} and any(letters & {"d"} for letters in flagLetters):
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, f"git {sub} 删除引用", "git")
    if sub in {"checkout", "restore"} and "." in rest:
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "git 整树丢弃本地改动", "git")
    if sub in {"filter-branch", "filter-repo"}:
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "git 重写历史", "git")
    if sub in _GIT_READONLY_SUBS:
        if sub == "remote" and any(f.lower() not in {"-v"} for f in rest):
            return ArgvVerdict(ArgvClass.UNKNOWN, "git remote 变更操作", "git")
        return ArgvVerdict(ArgvClass.READONLY, f"git 只读子命令 {sub}", "git")
    return ArgvVerdict(ArgvClass.UNKNOWN, f"git 子命令 {sub or '?'} 未列入只读面", "git")


def _classifySpecial(verb: str, argv) -> ArgvVerdict:
    """git/npm/pip/find 等带子命令或结构化语义的动词（大小写不敏感）。"""
    lv = verb.lower()
    if lv == "git":
        return _classifyGit(argv)
    if lv == "npm":
        sub = (argv[1] if len(argv) > 1 else "").lower()
        if sub in {"ls", "list", "outdated", "view", "search"}:
            return ArgvVerdict(ArgvClass.READONLY, f"npm 只读子命令 {sub}", "npm")
        return ArgvVerdict(ArgvClass.UNKNOWN, f"npm 子命令 {sub or '?'} 未列入只读面", "npm")
    if lv == "pip":
        sub = (argv[1] if len(argv) > 1 else "").lower()
        if sub in {"list", "show", "freeze", "check"}:
            return ArgvVerdict(ArgvClass.READONLY, f"pip 只读子命令 {sub}", "pip")
        return ArgvVerdict(ArgvClass.UNKNOWN, f"pip 子命令 {sub or '?'} 未列入只读面", "pip")
    if lv == "find":
        rest = argv[1:]
        if "-delete" in rest:
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "find -delete 删除文件", "find")
        if any(marker in rest for marker in ("-exec", "-execdir")) and "rm" in rest:
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "find -exec rm 删除文件", "find")
        if any(marker in rest for marker in ("-exec", "-execdir")):
            return ArgvVerdict(ArgvClass.UNKNOWN, "find -exec 外部命令", "find")
        return ArgvVerdict(ArgvClass.READONLY, "find 检索", "find")
    if lv in {"rm", "ri"}:
        if _hasRecursiveDelete(argv):
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "递归删除（rm -r 族）", lv)
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "删除命令", lv)
    if lv in {"del", "erase", "rd", "rmdir"}:
        if any(f.lower() in {"/s", "-s", "/q"} for f in argv[1:]):
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "Windows 递归删除", lv)
        return ArgvVerdict(ArgvClass.UNKNOWN, f"{lv} 未带 /s，按未知处理", lv)
    if lv == "remove-item":
        if any(f.lower() == "-recurse" for f in argv[1:]):
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "PowerShell 递归删除", lv)
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "PowerShell 删除命令", lv)
    if lv in {"stop-computer", "restart-computer"}:
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "PowerShell 系统电源操作", lv)
    if lv == "chmod":
        if any(a.strip().lstrip("0") == "777" for a in argv[1:]):
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "chmod 777 全局可写", lv)
        return ArgvVerdict(ArgvClass.UNKNOWN, "chmod 未列白名单", lv)
    if lv == "kubectl":
        sub = (argv[1] if len(argv) > 1 else "").lower()
        if sub == "delete":
            return ArgvVerdict(ArgvClass.DESTRUCTIVE, "kubectl delete 删除工作负载", lv)
        return ArgvVerdict(ArgvClass.UNKNOWN, "kubectl 子命令未列入只读面", lv)
    if lv == "sudo":
        return ArgvVerdict(ArgvClass.UNKNOWN, "sudo 提权，按未知处理", lv)
    if lv in _DESTRUCTIVE_VERBS or lv.startswith("mkfs"):
        return ArgvVerdict(ArgvClass.DESTRUCTIVE, "系统级/不可逆命令", lv)
    return ArgvVerdict(ArgvClass.UNKNOWN, "", lv)


def classifyArgv(argv) -> ArgvVerdict:
    """对一条 argv 做三级判定：DESTRUCTIVE > READONLY > UNKNOWN。"""
    if not argv:
        return ArgvVerdict(ArgvClass.UNKNOWN, "空命令", "")
    verb = argv[0]

    # 1) 语法结构即危险：先于只读判定（rm -rf x > log 依旧是危险命令）
    special = _classifySpecial(verb, argv)
    if special.classification == ArgvClass.DESTRUCTIVE:
        return special

    # 2) 只读白名单：动词命中且无输出重定向
    verbLower = verb.lower()
    if verbLower in _READONLY_VERBS or verb in _READONLY_VERBS:
        if _OUTPUT_REDIRECT_TOKENS & set(argv):
            return ArgvVerdict(ArgvClass.UNKNOWN, "输出重定向（写文件系统）", verb)
        return ArgvVerdict(ArgvClass.READONLY, "只读动词白名单", verb)

    # 3) 其余未知（含执行型动词与输出重定向）
    if _OUTPUT_REDIRECT_TOKENS & set(argv):
        return ArgvVerdict(ArgvClass.UNKNOWN, "输出重定向（写文件系统）", verb)
    return special if special.reason else ArgvVerdict(ArgvClass.UNKNOWN, "动词未列入只读面", verb)


def analyzeCommand(command: str, segmented: bool = False) -> CommandAnalysis:
    """分析整条命令：segmented=True 时按 &&/||/;/| 分段逐段判定。"""
    if not command or not command.strip():
        return CommandAnalysis(segments=())
    if segmented:
        from neurova.security.command_segments import parse_command_segments

        pieces = [(s.text, s.text) for s in parse_command_segments(command)]
    else:
        pieces = [(command, command)]
    analyses = []
    for text, _ in pieces:
        argv = tokenizeArgv(text)
        analyses.append(SegmentAnalysis(text=text, argv=argv, verdict=classifyArgv(argv)))
    return CommandAnalysis(segments=tuple(analyses))
