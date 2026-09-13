# -*- coding: utf-8 -*-
"""跨平台 no-follow 安全路径原语（Yuxi 对比 P2 #10）。

对位 Yuxi `utils/paths.py` 的逐段 `dir_fd + O_NOFOLLOW` openat 链，按
Neurova 的 Windows-first 桌面形态提供等价语义：

  1. 语法层拒绝：绝对路径 / 盘符(C:\\) / UNC(\\\\srv) / ``..`` / 空段
     (``a//b``) / ``.`` / NUL；
  2. 组件层 no-follow：自 root 起逐段 lstat，任一新段是 symlink 或
     junction（Windows 重解析点，is_symlink 对 junction 恒 False，必须
     is_junction 单独判）即拒——**防"先 resolve 再通过外层链接逃逸"与
     resolve 后被替换的 TOCTOU**；
  3. 终态双保险：resolve 后仍做 containment（root 自身可含链接，由调用方
     负责，故 containment 只在 root 已定形后做）。

POSIX 的 `open_within` 额外以 ``O_NOFOLLOW`` 打开末段文件，杜绝"检查后、
打开前"把目标换成软链的竞态；Windows 无 O_NOFOLLOW，靠组件层 lstat 链 +
`os.stat(follow_symlinks=False)` 末段复核补偿（桌面威胁模型下充分）。

拒绝策略统一抛 UnsafePathError；消费方（如 workspace_files）映射为 400，
保持 fail-closed。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Union

__all__ = ["UnsafePathError", "resolve_within", "open_within"]

_IS_WINDOWS = sys.platform == "win32"


class UnsafePathError(ValueError):
    """路径穿越 / 软链 / 非法组件——调用方须 fail-closed（拒绝而非降级）。"""


def _split_rel(rel: Union[str, Path, None]) -> list:
    """把相对路径拆成合法组件列表；非法形态直接抛 UnsafePathError。

    "" / "." / "/" → []（表示 root 本身）。
    """
    s = str(rel or "").strip()
    if s in ("", ".", "/", "\\"):
        return []
    if "\x00" in s:
        raise UnsafePathError("路径含 NUL 字节")
    # 统一分隔符后逐段检查；反斜杠开头的 UNC、含盘符的一律拒绝绝对形态
    normalized = s.replace("\\", "/")
    if normalized[:1] == "/":
        raise UnsafePathError(f"拒绝绝对路径/UNC: {rel!r}")
    # 盘符检测（C:/...）——str("C:\\x").replace → "C:/x"
    if len(normalized) >= 2 and normalized[1] == ":":
        raise UnsafePathError(f"拒绝盘符路径: {rel!r}")
    parts = []
    for raw in normalized.split("/"):
        if raw == "":  # 空段（连续斜杠 / 尾斜杠）
            raise UnsafePathError(f"拒绝空路径段: {rel!r}")
        if raw == ".":
            raise UnsafePathError(f"拒绝 '.' 段: {rel!r}")
        if raw == "..":
            raise UnsafePathError(f"拒绝 '..' 段（路径穿越）: {rel!r}")
        if "\x00" in raw:
            raise UnsafePathError("路径段含 NUL 字节")
        parts.append(raw)
    return parts


def _is_link(p: Path) -> bool:
    """该路径节点是否为符号链接或重解析点（junction / symlink-to-dir）。"""
    try:
        if p.is_symlink():
            return True
    except OSError:
        return True  # lstat 失败保守判为不安全
    is_junction = getattr(p, "is_junction", None)  # py>=3.12
    if is_junction is not None:
        try:
            if bool(is_junction()):
                return True
        except OSError:
            return True
    elif _IS_WINDOWS:
        # 3.11 及以前无 is_junction：用 reparse point 属性粗判
        try:
            st = os.stat(p, follow_symlinks=False)
            import stat as _stat

            if getattr(st, "st_file_attributes", 0) & _stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return True
        except OSError:
            pass
    return False


def resolve_within(
    root: Union[str, Path],
    rel: Union[str, Path, None],
    *,
    reject_hidden: bool = True,
) -> Path:
    """把相对路径解析到 root 内并返回 Path；任何非法形态抛 UnsafePathError。

    reject_hidden=True 时以 ``.`` 开头的组件整棵拒绝（.git/.env 等）。
    rel 为 ""/"."/"/" → 返回已定形的 root（列根目录等）。
    """
    root_resolved = Path(root).resolve()
    parts = _split_rel(rel)
    cur = root_resolved
    for part in parts:
        if reject_hidden and part.startswith("."):
            raise UnsafePathError(f"隐藏路径不允许访问: {part!r}")
        nxt = cur / part
        # 组件级 no-follow：新增段是链接即拒（含 junction）
        if _is_link(nxt):
            raise UnsafePathError(f"拒绝符号链接/重解析点组件: {part!r}")
        cur = nxt
    # 终态 containment 双保险（防 root 定形后的相对性漂移）
    final = cur.resolve()
    try:
        final.relative_to(root_resolved)
    except ValueError:
        raise UnsafePathError(f"路径越界: {rel!r}") from None
    return final


def open_within(
    root: Union[str, Path],
    rel: Union[str, Path],
    mode: str = "rb",
    *,
    must_exist: bool = True,
):
    """在 root 边界内打开文件（no-follow）。POSIX 末段加 O_NOFOLLOW。

    返回已打开的文件对象（调用方 with 管理）。rel 解析失败抛
    UnsafePathError；must_exist 且不存在 → UnsafePathError。
    """
    target = resolve_within(root, rel)
    if must_exist and not target.exists():
        raise UnsafePathError(f"文件不存在: {rel!r}")
    if _IS_WINDOWS:
        # 末段复核：target 若是链接仍拒（resolve_within 已查，但 exists() 与
        # open 之间可能被替换——桌面模型下二次 lstat 足够）
        if _is_link(target):
            raise UnsafePathError(f"拒绝打开链接: {rel!r}")
        return open(target, mode)
    flags = os.O_RDONLY
    if "w" in mode or "a" in mode or "x" in mode:
        flags = os.O_WRONLY | os.O_CREAT
        if "a" in mode:
            flags |= os.O_APPEND
        if "x" in mode:
            flags |= os.O_EXCL
    else:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(target), flags)
    return os.fdopen(fd, mode)
