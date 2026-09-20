"""已提交树必须自洽：本包不能 import 一个没进版本库的模块。

工单 004 期间真实踩过——`neurova/core/content_identity.py` 当时只在工作树里，
`admission/reconcile/redundancy` 三个已提交模块都 import 它，跑测试全绿（工作树里有文件），
但 HEAD 单独检出即 ImportError。工作树永远掩盖这类缺失，所以判据必须问 git 而不是问磁盘。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_LANES = ("neurova/knowledge/",)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=_REPO, capture_output=True).stdout


def _trackedAtHead(path: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", "HEAD:" + path],
                          cwd=_REPO, capture_output=True).returncode == 0


def _resolve(module: str) -> str | None:
    for suffix in (".py", "/__init__.py"):
        candidate = module.replace(".", "/") + suffix
        if (_REPO / candidate).exists():
            return candidate
    return None


def _importsOf(relPath: str) -> list[str]:
    raw = _git("show", "HEAD:" + relPath)
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[str] = []
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
    offenders: list[str] = []
    for rel in _git("ls-files").decode("utf-8").split():
        if not rel.startswith(_LANES):
            continue
        for module in _importsOf(rel):
            target = _resolve(module)
            if target and not _trackedAtHead(target):
                offenders.append("%s  import 了未入库的 %s" % (rel, target))

    assert not offenders, "已提交树缺依赖，单独检出即 ImportError:\n" + "\n".join(sorted(set(offenders)))
