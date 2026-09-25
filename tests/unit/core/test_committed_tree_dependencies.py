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
from typing import Dict, List, Optional, Set

_REPO = Path(__file__).resolve().parents[3]
_LANES = ("neurova/knowledge/",)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=_REPO, capture_output=True).stdout


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
    raw = _git("show", "HEAD:" + relPath)
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: List[str] = []
    package = Path(relPath).parent.parts
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append(node.module)
            elif node.level:
                base = list(package[: len(package) - (node.level - 1)])
                found.append(".".join(base + ([node.module] if node.module else [])))
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return [m for m in found if m.startswith("neurova.")]


def test_everyImportedByKnowledgePackageIsCommitted():
    tracked = _trackedAtHead()
    exists: Dict[str, bool] = {}
    offenders: List[str] = []
    for rel in _git("ls-files").decode("utf-8").split():
        if not rel.startswith(_LANES):
            continue
        for module in _importsOf(rel):
            target = _resolveImports(module, exists)
            if target and target not in tracked:
                offenders.append("%s  import 了未入库的 %s" % (rel, target))

    assert not offenders, (
        "已提交树缺依赖，单独检出即 ImportError:\n" + "\n".join(sorted(set(offenders))))
