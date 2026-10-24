"""已提交树必须自洽：本包不能 import 一个没进版本库的模块。

工单 004 期间真实踩过——`neurova/core/content_identity.py` 当时只在工作树里，
`admission/reconcile/redundancy` 三个已提交模块都 import 它，跑测试全绿（工作树里有文件），
但 HEAD 单独检出即 ImportError。工作树永远掩盖这类缺失，所以判据必须问 git 而不是问磁盘。

成本控制：整棵 HEAD 用一次 `ls-tree -r` 取回，逐文件只 `git show` 一次。
第一版按"每个 import 起一个 cat-file 进程"写，副进程数量把同一会话里一个
时序敏感的锁测试拖到了超时——结构守卫不该有这种副作用。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from tests import ast_scan  # noqa: E402
from typing import Dict, List, Optional, Set

_REPO = Path(__file__).resolve().parents[3]
_LANES = ("neurova/knowledge/",)

#: `_git()` 的预算唯一出处（§6-402 批 K 口径）。跑的是 `ls-tree` / `ls-files`，毫秒级；
#: 此前没有 `timeout=`＝无界等待，而缺省 30s 的全局墙在 Windows 侧走 thread 法，
#: 先到点就是整场跑测没了。取**低于全局墙**的 20s，整档不必另抬父墙。
GIT_WALL_S = 20


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=_REPO, capture_output=True,
                          timeout=GIT_WALL_S).stdout


def _trackedAtHead() -> Set[str]:
    """一次进程取回 HEAD 的全部文件清单。"""
    listing = _git("ls-tree", "-r", "--name-only", "HEAD").decode("utf-8")
    return {line for line in listing.splitlines() if line}


def _resolveImports(module: str, exists: Dict[str, bool]) -> Optional[str]:
    for suffix in (".py", "/__init__.py"):
        candidate = module.replace(".", "/") + suffix
        if exists.setdefault(candidate, Path(_REPO / candidate).exists()):
            return candidate
    return None


def _importsOf(relPath: str) -> List[str]:
    """HEAD 版源码里被取用的 `neurova.*` 模块名（相对形按发起文件位置解析成绝对名）。

    "把 `from .x import a` 解成绝对名"这件事在 `tests/ast_scan.resolveImportModule` 已有单点。
    这里原先自己抄了一份层数算术（`package[: len(package) - (node.level - 1)]`）——两份实现
    迟早对 `from . import x` 这类形状分叉，而分叉的代价是这条判据**看不见**：它只会报
    "import 了未入库的模块"，不会报"我把相对形解错了"。
    """
    raw = _git("show", "HEAD:" + relPath)
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = ast_scan.resolveImportModule(relPath, node)
            if module:
                found.append(module)
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return [m for m in found if m.startswith("neurova.")]


def test_everyImportedByKnowledgePackageIsCommitted():
    tracked = _trackedAtHead()
    exists: Dict[str, bool] = {}
    offenders: List[str] = []
    for rel in ast_scan.trackedPaths():
        if not rel.startswith(_LANES):
            continue
        for module in _importsOf(rel):
            target = _resolveImports(module, exists)
            if target and target not in tracked:
                offenders.append("%s  import 了未入库的 %s" % (rel, target))

    assert not offenders, (
        "已提交树缺依赖，单独检出即 ImportError:\n" + "\n".join(sorted(set(offenders))))
