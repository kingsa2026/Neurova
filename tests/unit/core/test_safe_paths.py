# -*- coding: utf-8 -*-
"""safe_paths 跨平台 no-follow 路径原语（Yuxi 对比 P2 #10）。

对位 Yuxi utils/paths.py 的 openat(dir_fd+O_NOFOLLOW) 链，按 Neurova 的
Windows-first 桌面形态移植等价语义：
- 组件级 symlink/junction 拒绝（Windows is_junction 覆盖 mklink /J 重解析点，
  is_symlink 覆盖符号链接；POSIX 走 O_NOFOLLOW 真原语）
- 拒绝绝对路径/盘符/UNC/../空组件/NUL
- 逐段 lstat 检查 + 最终 realpath containment 双保险
- workspace_files._resolve_inside 改为消费本原语（单源，隐藏目录策略保留）
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from neurova.core.safe_paths import UnsafePathError, open_within, resolve_within


def _make_link(link: Path, target: Path) -> bool:
    """尽力创建一个符号链或 Windows junction；两者都无权限时返回 False（skip）。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        if sys.platform == "win32":
            try:
                r = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                    capture_output=True, text=True, timeout=10,
                )
                return r.returncode == 0 and link.exists()
            except Exception:
                return False
        return False


def test_rejects_traversal_and_absolute(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    for bad in ["../escape", "a/../../b", "/etc/passwd", "C:\\Windows\\x",
                "\\\\server\\share", "..", "./../x"]:
        with pytest.raises(UnsafePathError):
            resolve_within(root, bad)
    # 合法相对段（含普通单段）必须放行
    assert resolve_within(root, "a").name == "a"


def test_rejects_nul_and_empty_parts(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    with pytest.raises(UnsafePathError):
        resolve_within(root, "a\x00b")
    with pytest.raises(UnsafePathError):
        resolve_within(root, "a//b")


def test_hidden_component_policy(tmp_path):
    root = tmp_path / "ws"
    (root / "sub" / ".git").mkdir(parents=True)
    with pytest.raises(UnsafePathError):
        resolve_within(root, "sub/.git/config", reject_hidden=True)
    # 关策略时可过（默认拒绝，显式放行）
    ok = resolve_within(root, "sub/.git", reject_hidden=False)
    assert ok.name == ".git"


def test_normal_paths_resolve(tmp_path):
    root = tmp_path / "ws"
    (root / "a" / "b").mkdir(parents=True)
    assert resolve_within(root, "") == root.resolve()
    assert resolve_within(root, "a/b").is_dir()
    assert resolve_within(root, Path("a") / "b")  # 接受 Path 形态相对入参


def test_symlink_or_junction_escape_rejected(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "crown-jewels.txt").write_text("secret", encoding="utf-8")
    link = root / "link"
    if not _make_link(link, outside):
        pytest.skip("本机无创建符号链/junction 权限（Windows 需开发者模式/管理员）")
    with pytest.raises(UnsafePathError):
        resolve_within(root, "link/crown-jewels.txt")
    with pytest.raises(UnsafePathError):
        open_within(root, "link/crown-jewels.txt")


def test_open_within_reads_regular_file(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "f.txt").write_text("hello", encoding="utf-8")
    with open_within(root, "f.txt") as fh:  # 默认二进制读
        assert fh.read() == b"hello"
    with pytest.raises(UnsafePathError):
        open_within(root, "missing.txt", must_exist=True)
