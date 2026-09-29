# -*- coding: utf-8 -*-
"""NSIS 模板的安装器美术资产必须与 bundler 目标目录布局解耦。

为什么要有本守卫（实测断裂）：安装器模板（`NeurUI/src-tauri/nsis/installer.nsi`）
把 Hero/按钮位图的编译期路径写死成"相对上行四级"
（`..\\..\\..\\..\\nsis\\assets\\hero_zh.bmp`），它只在原生构建的
`target/release/nsis/x64` 布局下成立；交叉编译（cargo-xwin，Tauri 官方支持的
Linux/macOS 构建 Windows 安装包路径）布局多一层目标三元组
（`target/x86_64-pc-windows-msvc/release/nsis/x64`），四级解析到 `target/`，
makensis 即报 `File: ... -> no files found` 并中止，整包产不出来。

判据：资产引用一律走 `${NSIS_ART}` 单一定义，且该定义同时覆盖两种布局
（四级与五级相对路径都要在候选里），禁止任何 File 指令再写死单一深度。
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_NSI = _REPO / "NeurUI" / "src-tauri" / "nsis" / "installer.nsi"


def _source() -> str:
    return _NSI.read_text(encoding="utf-8")


def testAssetFileDirectivesAreLayoutAgnostic():
    """所有指向 nsis/assets 的 File 指令必须经 ${NSIS_ART}，不得写死相对深度。"""
    offenders = [
        line.strip()
        for line in _source().splitlines()
        if re.search(r'\bFile\b.*nsis\\assets', line) and "NSIS_ART" not in line
    ]
    assert offenders == [], (
        "以下 File 指令写死了单一目录布局（交叉编译时 makensis 找不到资产）：\n"
        + "\n".join(offenders)
    )


def testAssetRootCoversBothNativeAndCrossLayouts():
    """资产根定义必须同时给出原生（四级）与交叉编译（五级）两种候选。"""
    src = _source()
    assert re.search(r'!define\s+NSIS_ART\s+"\.\.\\\.\.\\\.\.\\\.\.\\nsis\\assets"', src), \
        "缺少原生布局候选：..\\..\\..\\..\\nsis\\assets"
    assert re.search(r'!define\s+NSIS_ART\s+"\.\.\\\.\.\\\.\.\\\.\.\\\.\.\\nsis\\assets"', src), \
        "缺少交叉编译布局候选：..\\..\\..\\..\\..\\nsis\\assets"
