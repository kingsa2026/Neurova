# -*- coding: utf-8 -*-
"""G5 路径守卫：符号链接感知的路径规约（fail-closed）。

借鉴点（研究文档 reference_ac_ide_integration_gap_analysis G5）：路径校验做
符号链接感知的逐级 realpath 规约，任何解析错误 fail-closed 拒绝——「校验时
的路径」不等于「进程实际打开的路径」，中间符号链接是经典逃逸面。

语义：
- `resolvePath`：os.path.realpath 解析所有现存层级的符号链接；解析失败
  （OSError）→ PathGuardError，绝不静默返回原路径；
- `normalizeDir`：在 resolvePath 之上要求「存在且为目录」（断链/不存在/
  指向文件 → PathGuardError）；
- `assertWithinRoots`：规约后被允许根（同样规约）包含，否则越界拒绝。
"""
import os
from typing import Iterable

class PathGuardError(RuntimeError):
    """路径规约失败（断链/越界/解析错误）——fail-closed 拒绝。"""


def resolvePath(path: str) -> str:
    """符号链接感知的真实路径规约；解析失败 fail-closed。"""
    text = str(path or "").strip()
    if not text:
        raise PathGuardError("路径为空")
    try:
        return os.path.realpath(text)
    except OSError as exc:  # noqa: PERF203 - 解析错误按契约显式拒绝
        raise PathGuardError(f"路径解析失败 {text!r}: {exc}") from exc


def normalizeDir(path: str) -> str:
    """规约并要求「存在且为目录」；断链/不存在/指向文件 → PathGuardError。"""
    resolved = resolvePath(path)
    if not os.path.isdir(resolved):
        raise PathGuardError(f"路径不是已存在的目录（或断链）: {str(path)!r} -> {resolved!r}")
    return resolved


def assertWithinRoots(path: str, roots: Iterable[str]) -> str:
    """规约 path 并要求落在任一允许根（同样规约）之内；越界 fail-closed。

    叶子不存在时按最长存在前缀规约（realpath 语义），仍必须落在根内。
    """
    resolved = resolvePath(path)
    normalizedRoots = []
    for root in roots or []:
        rootText = str(root or "").strip()
        if rootText:
            normalizedRoots.append(resolvePath(rootText))
    if not normalizedRoots:
        raise PathGuardError("允许根列表为空——fail-closed 拒绝")
    for rootResolved in normalizedRoots:
        if resolved == rootResolved or resolved.startswith(rootResolved + os.sep):
            return resolved
    raise PathGuardError(
        f"路径越界: {str(path)!r} ({resolved!r}) 不在任何允许根 {normalizedRoots!r} 内")
