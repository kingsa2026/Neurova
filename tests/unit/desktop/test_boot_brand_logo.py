# -*- coding: utf-8 -*-
"""boot 页品牌 LOGO 契约（用户 2026-09-21：LOGO 不对，要同安装器的白色 LOGO）。

三个不变式：
1. boot 页与安装器壳共用同一张白色 LOGO 资源（LOGO_SRC 与 build.rs 首选候选
   解析到同一文件）——「同我提供给你的白色 LOGO」的契约位；
2. 该资源是「图标 + 文字」构图的白色 LOGO（aspect≈3.9 且中部有图标/文字分隔空列），
   不是 2026-09-11 的纯文字字标 WORDMARK；
3. boot_page.html 仍保留 __NEUROVA_WORDMARK_B64__ 占位符（build.rs 注入点）。
"""
import re
from pathlib import Path

import pytest
from PIL import Image

_REPO = Path(__file__).resolve().parents[3]
_BUILD_RS = _REPO / "NeurUI" / "src-tauri" / "build.rs"
_BOOT_HTML = _REPO / "NeurUI" / "src-tauri" / "src" / "boot_page.html"
_PACKAGER = _REPO / "scripts" / "desktop" / "package_installer_zip.py"

_WHITE_LOGO = "NEUROVA-LOGO350white.png"
_PURE_WORDMARK = "NEUROVA-WORDMARK-white.png"


def _boot_candidates() -> list[str]:
    """build.rs 里 inject_boot_icon_env 的候选清单（按优先级）。"""
    src = _BUILD_RS.read_text(encoding="utf-8")
    m = re.search(r"let candidates = \[(.*?)\];", src, re.S)
    assert m, "build.rs 找不到 inject_boot_icon_env 的 candidates 清单"
    return re.findall(r'"([^"]+)"', m.group(1))


def _installer_logo_src() -> Path:
    """package_installer_zip.py 里 WPF 壳内嵌的 LOGO_SRC。"""
    src = _PACKAGER.read_text(encoding="utf-8")
    m = re.search(r'^LOGO_SRC = REPO((?: / "[^"]+")+)', src, re.M)
    assert m, "package_installer_zip.py 找不到 LOGO_SRC 定义"
    return _REPO.joinpath(*re.findall(r'"([^"]+)"', m.group(1))).resolve()


class TestBootLogoContract:
    def test_boot_page_prefers_white_logo(self):
        assert _boot_candidates()[0].endswith(_WHITE_LOGO), (
            f"boot 页首选候选应是 {_WHITE_LOGO}，实际 {_boot_candidates()}"
        )

    def test_boot_logo_matches_installer_shell_logo(self):
        """boot 页与安装器欢迎页必须是同一张白色 LOGO（字节级同源）。"""
        boot = (_REPO / "NeurUI" / "src-tauri" / _boot_candidates()[0]).resolve()
        installer = _installer_logo_src()
        assert boot == installer, f"boot 页 LOGO {boot} 与安装器 LOGO {installer} 不是同一文件"

    def test_white_logo_is_icon_plus_wordmark(self):
        """白色 LOGO 必须是图标+文字构图：350x90 量级 + 图标与文字之间有分隔空列。
        纯文字字标（WORDMARK）没有这条空列——曾于 2026-09-11 误植 boot 页。"""
        asset = (_REPO / "NeurUI" / "src-tauri" / _boot_candidates()[0]).resolve()
        assert asset.exists(), f"boot 页 LOGO 资源缺失：{asset}"
        im = Image.open(asset).convert("RGBA")
        w, h = im.size
        assert abs(w / h - 350 / 90) < 0.2, f"LOGO 比例异常：{im.size}"
        px = im.load()
        cols = [sum(1 for y in range(h) if px[x, y][3] > 60) for x in range(w)]
        # 最长连续全空列 = 图标与文字之间的分隔带（纯文字字标没有这条带）
        gap = run = 0
        for c in cols:
            run = run + 1 if c == 0 else 0
            gap = max(gap, run)
        assert gap >= 8, f"未检出图标/文字分隔空列（gap={gap}px），疑似纯文字字标"

    def test_white_logo_pixels_are_light(self):
        """白色 LOGO：不透明像素均值亮度必须高（黑图会落在深色 boot 背景上不可见）。"""
        asset = _REPO / "NeurUI" / "src-tauri" / _boot_candidates()[0]
        im = Image.open(asset).convert("RGBA")
        px = im.load()
        lum = [
            0.2126 * px[x, y][0] + 0.7152 * px[x, y][1] + 0.0722 * px[x, y][2]
            for x in range(im.size[0])
            for y in range(im.size[1])
            if px[x, y][3] > 128
        ]
        assert lum, "LOGO 无可见像素"
        assert sum(lum) / len(lum) > 180, f"LOGO 不是白色（均值亮度 {sum(lum) / len(lum):.0f}）"

    def test_boot_page_keeps_injection_placeholder(self):
        assert "__NEUROVA_WORDMARK_B64__" in _BOOT_HTML.read_text(encoding="utf-8")

    def test_dev_boot_page_uses_white_logo(self):
        """dev 态 boot 页（public/boot.html，直连 public 资产）同根因第二命中点：
        曾引用纯文字字标，与打包态 boot 页构图不一致。"""
        dev = _REPO / "NeurUI" / "public" / "boot.html"
        assert dev.exists(), f"dev boot 页缺失：{dev}"
        src = dev.read_text(encoding="utf-8")
        assert f"/img/{_WHITE_LOGO}" in src, f"dev boot 页应引用 {_WHITE_LOGO}"
        assert _PURE_WORDMARK not in src, f"dev boot 页不应再引用 {_PURE_WORDMARK}"
