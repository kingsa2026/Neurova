# -*- coding: utf-8 -*-
"""包根与仓根不得留 0 字节的"重定向残留"文件（§9 序 1 的收口面，防再生）。

来历：`neurova/expected` 是 0 字节、无后缀、非模块的文件，由 `98b5422a`「清理临时文件」
引入——那一笔同时新增仓根 `missing`(0 字节) 并删掉 471 行 `missing_files.txt`，形态就是
**shell 重定向把命令名当成了文件名**（`... > expected`、`... > missing`）。仓根那件已没了，
包内这件留到 2026-10-09 才删（`git rm`）。

只删一次不算闭环：同一形态再来一次没人会红。所以本守卫按**类**判——
包目录树与仓根下，0 字节且无扩展名的普通文件一律不许存在（`__init__.py` 一类合法空文件
有后缀，不在射程内）。反向对照自证扫描器不是恒绿。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.timeout(60)


def _isResidue(p: Path) -> bool:
    """0 字节、无扩展名的普通文件才算残留（`__init__.py`/`empty.txt` 有后缀，不在射程）。"""
    if not p.is_file():
        return False
    try:
        return p.stat().st_size == 0 and not p.suffix
    except OSError:
        return False


def _zeroByteResidues(root: Path) -> list[str]:
    """`root` 树内 0 字节无后缀的普通文件（相对路径，排序稳定）。"""
    return [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if _isResidue(p)]


def _topLevelResidues(root: Path) -> list[str]:
    """只看仓根一层：整树 rglob 会踩进 node_modules/.venv，既慢又满是无关命中。"""
    return [p.name for p in sorted(root.iterdir()) if p.is_file() and _isResidue(p)]


class TestNoZeroByteResidueInPackage:
    def test_neurovaTreeHasNoNamelessEmptyFile(self):
        found = _zeroByteResidues(REPO / "neurova")
        assert found == [], (
            "包树里出现 0 字节无后缀文件（重定向残留形态，来历见本文件 docstring）："
            f"{found}")

    def test_repoRootHasNoNamelessEmptyFile(self):
        rootLevel = _topLevelResidues(REPO)
        assert rootLevel == [], f"仓根有同类残留：{rootLevel}"

    def test_scannerCatchesASyntheticResidue(self, tmp_path):
        """反向对照：造一枚出来必须被抓到，否则上面两条绿是空的。"""
        (tmp_path / "neurova").mkdir()
        (tmp_path / "neurova" / "expected").touch()
        (tmp_path / "neurova" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "neurova" / "empty.txt").touch()
        assert _zeroByteResidues(tmp_path / "neurova") == ["expected"], (
            "扫描器没抓到残留，或把合法空文件（有后缀）也算进去了")
        (tmp_path / "top").mkdir()
        (tmp_path / "top" / "missing").touch()
        assert _topLevelResidues(tmp_path / "top") == ["missing"], "仓根那半的扫描面是空的"

    def test_theHistoricalCulpritIsGoneFromGitIndex(self):
        """`git rm` 之后索引里不能再有它——工作树删了但索引留着等于没退役。"""
        tracked = subprocess.run(
            ["git", "ls-files", "--", "neurova/expected", "missing"],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout.split()
        assert tracked == [], f"仍在 git 索引里：{tracked}"
