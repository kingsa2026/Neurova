# -*- coding: utf-8 -*-
"""G5 路径守卫测试：符号链接感知的逐级 realpath 规约（fail-closed）。

覆盖：符号链接逃逸拒绝 / 断链拒绝 / 合法嵌套放行 / 越界拒绝 / 根自身规约。
"""
import os
import subprocess

import pytest

from neurova.security.path_guard import (
    PathGuardError,
    assertWithinRoots,
    normalizeDir,
    resolvePath,
)


def makeDirLink(link, target):
    """建目录链接：优先符号链接，Windows 无特权时退回 junction（mklink /J，
    无需特权且 os.path.realpath 同样解析）——保证逃逸/断链用例在任何
    Windows 环境可测。"""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except OSError:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "keep.txt").write_text("ok", encoding="utf-8")
    return root


def test_resolve_path_returns_realpath_for_plain_dir(workspace):
    assert resolvePath(str(workspace / "sub")) == os.path.realpath(str(workspace / "sub"))


def test_symlink_escape_is_rejected(workspace):
    # root/sub/link -> tmp_path（越出允许根的目录链接/junction）
    link = workspace / "sub" / "link"
    makeDirLink(link, workspace.parent)
    with pytest.raises(PathGuardError):
        assertWithinRoots(str(link / "sub" / "keep.txt"), [str(workspace)])


def test_symlink_to_inside_is_resolved(workspace):
    # 指向根内的目录链接：规约到真实路径后放行
    link = workspace / "sub" / "inside"
    makeDirLink(link, workspace / "sub")
    resolved = assertWithinRoots(str(link / "keep.txt"), [str(workspace)])
    assert resolved == os.path.realpath(str(workspace / "sub" / "keep.txt"))


def test_broken_symlink_fails_closed(workspace):
    link = workspace / "sub" / "broken"
    makeDirLink(link, workspace / "does-not-exist")
    with pytest.raises(PathGuardError):
        normalizeDir(str(link))


def test_outside_root_rejected(workspace):
    outside = tmp_outside(workspace)
    with pytest.raises(PathGuardError):
        assertWithinRoots(str(outside), [str(workspace)])


def tmp_outside(workspace):
    outside = workspace.parent / "outside-area"
    outside.mkdir(exist_ok=True)
    return outside


def test_nonexistent_leaf_under_root_resolves_to_root_prefix(workspace):
    # 叶子不存在：按最长存在前缀规约，仍必须落在根内
    resolved = assertWithinRoots(str(workspace / "sub" / "new-dir" / "f.txt"), [str(workspace)])
    assert resolved.startswith(os.path.realpath(str(workspace)))


def test_normalize_dir_rejects_file(workspace):
    with pytest.raises(PathGuardError):
        normalizeDir(str(workspace / "sub" / "keep.txt"))
