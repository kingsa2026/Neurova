# -*- coding: utf-8 -*-
"""安装器版本号必须单一定义，不得在壳里手抄第二份。

为什么要有本守卫（实测断裂）：自定义界面壳 `MainWindow.cs` 的欢迎页把版本
硬编码成字面量 `v1.0.0`，而产品版本事实源（`NeurUI/src-tauri/tauri.conf.json`
与 `NeurUI/package.json`）已经跑到 `1.0.0-beta5`。结果是**装出来的包自己
显示的版本号与实际版本不符** —— 用户下载 beta5、装上看见 v1.0.0，
无法据此判断自己装的是哪一版。这类"只写不读的字面量"不会有任何红：
编译通过、装包成功、界面也正常渲染，只是显示了一个错的值。

判据两条：
  1. 壳源码里不得出现形如 `v1.0.0` 的**硬编码版本字面量**（版本只能来自构建期）；
  2. 版本事实源（tauri.conf.json / package.json）与 NSIS 模板的 `{{version}}`
     占位符必须咬合 —— 三方任意两方分叉即红。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SHELL = _REPO / "NeurUI" / "src-tauri" / "installer-wpf" / "MainWindow.cs"
_TAURI_CONF = _REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
_PKG = _REPO / "NeurUI" / "package.json"
_NSI = _REPO / "NeurUI" / "src-tauri" / "nsis" / "installer.nsi"

# 形如 v1.0.0 / 1.0.0-beta5 的版本字面量
_VERSION_LITERAL = re.compile(r'v?1\.0\.0(?:-[\w.]+)?')


def _shell_source() -> str:
    return _SHELL.read_text(encoding="utf-8")


def _product_version() -> str:
    return json.loads(_TAURI_CONF.read_text(encoding="utf-8"))["version"]


def testShellHasNoHardcodedVersionLiteral():
    """壳源码不得写死版本字面量（版本必须来自构建期注入）。"""
    offenders = [
        line.strip()
        for line in _shell_source().splitlines()
        if _VERSION_LITERAL.search(line)
    ]
    assert offenders == [], (
        "WPF 壳里写死了版本字面量，与实际产品版本会分叉：\n"
        + "\n".join(offenders)
    )


def testVersionFactsAgreeAcrossSources():
    """tauri.conf.json 与 package.json 的版本必须一致。"""
    tauri_ver = _product_version()
    pkg_ver = json.loads(_PKG.read_text(encoding="utf-8"))["version"]
    assert tauri_ver == pkg_ver, (
        f"版本事实源分叉：tauri.conf.json={tauri_ver} / package.json={pkg_ver}"
    )


def testNsiTemplateKeepsVersionPlaceholder():
    """NSIS 模板的版本必须走 bundler 注入的 {{version}} 占位符，不得写死。"""
    src = _NSI.read_text(encoding="utf-8")
    assert re.search(r'!define\s+VERSION\s+"\{\{version\}\}"', src), \
        "NSIS 模板的 VERSION 必须保持 {{version}} 占位符（bundler 注入）"
    hardcoded = [
        line.strip()
        for line in src.splitlines()
        if _VERSION_LITERAL.search(line) and "{{" not in line
    ]
    assert hardcoded == [], (
        "NSIS 模板写死了版本字面量：\n" + "\n".join(hardcoded)
    )
